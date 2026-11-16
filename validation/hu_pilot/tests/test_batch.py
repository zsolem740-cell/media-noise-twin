"""Csomagos mód (kísérlet): kérésépítés, válasz-értelmezés címenként, felezés, újrapróba, kvótamegállás és folytatás, az egy-cím-egy-kérés móddal való összevetés. Hálózat nélkül (hamis átvitel)."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from validation.hu_pilot import batchrun as BR
from validation.hu_pilot import bundle as B
from validation.hu_pilot import compare as CMP
from validation.hu_pilot import modelrun as mr
from validation.hu_pilot import prompt as P
from validation.hu_pilot import providers as V
from validation.hu_pilot import run
from validation.hu_pilot.freeze import NotFrozen
from validation.hu_pilot.live import run_live as RL
from .test_live import DAY_DET, Fake, KEY, bundle_path, fake  # noqa: F401
from .test_modelrun import CANARY, Clock, GEM, GRQ, Script, frozen, jl, ok_raw, sig  # noqa: F401

UTC = timezone.utc
T0 = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)
POST = re.compile(r'<post id="(\d+)">\n(.*?)\n</post>', re.S)


def posts_of(body):
    t = body["contents"][0]["parts"][0]["text"] if "contents" in body else body["messages"][1]["content"]
    return [(int(k), p) for k, p in POST.findall(t)]


def provider_of(body):
    return "gemini" if "contents" in body else "groq"


def batch_raw(body, scores=lambda k, p: (1, 0, 0, 0), drop=(), mutate=None, finish="STOP"):
    prov = provider_of(body)
    items = [{"id": k, **sig(p, scores(k, p))} for k, p in posts_of(body) if k not in drop]
    if mutate:
        items = mutate(items)
    text = json.dumps({"results": items}, ensure_ascii=False)
    n = len(posts_of(body))
    if prov == "gemini":
        d = {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}], "modelVersion": GEM,
             "usageMetadata": {"promptTokenCount": 150 + 12 * n, "candidatesTokenCount": 60 * n, "totalTokenCount": 150 + 72 * n}}
    else:
        d = {"model": GRQ, "choices": [{"finish_reason": "stop" if finish == "STOP" else "length", "message": {"content": text}}],
             "usage": {"prompt_tokens": 150 + 12 * n, "completion_tokens": 60 * n, "total_tokens": 150 + 72 * n}}
    return mr.Raw(200, json.dumps(d), None, 100)


class BScript:
    def __init__(self, steps=(), default=None):
        self.steps, self.calls, self.default = list(steps), [], default or (lambda body: batch_raw(body))

    def __call__(self, model, body):
        self.calls.append((model, body))
        x = self.steps.pop(0) if self.steps else self.default
        if isinstance(x, Exception):
            raise x
        return x(body) if callable(x) else x


def go(frozen_fx, cfg, tr, provider="gemini", size=10, clock=None, name="b1"):
    res, titles = frozen_fx
    clock = clock or Clock()
    model = GEM if provider == "gemini" else GRQ
    return BR.run_batch_measurement(titles, provider, tr, cfg, res, name, model, size, now=clock.now, sleep=clock.sleep, monotonic=clock.monotonic), res / "model_runs" / name


# ---------------------------------------------------------------- kérés és séma

def test_the_system_instruction_is_unchanged_and_the_batch_text_marks_independent_posts(cfg):
    import hashlib
    assert hashlib.sha256(P.SYSTEM_INSTRUCTION.encode()).hexdigest() == "c634bdcc62aa9c2e47f5e886c4d076d7676ab4f8631fb215dc90846f1f5da20f"
    t = P.batch_user_text(["Egy cím", "Másik {cím}"])
    assert t.startswith("Below are 2 independent posts") and '<post id="1">\nEgy cím\n</post>' in t and '<post id="2">\nMásik {cím}\n</post>' in t and "exactly 2 entries" in t


@pytest.mark.parametrize("prov", ["gemini", "groq"])
def test_batch_body_uses_the_same_system_text_and_an_id_plus_four_signal_schema(cfg, prov):
    m = cfg["model"]
    body = V.BATCH_BUILDERS[prov](["Alma körte", "Szilva barack", "Dió mogyoró"], m)
    sys_txt = body["systemInstruction"]["parts"][0]["text"] if prov == "gemini" else body["messages"][0]["content"]
    assert sys_txt == P.SYSTEM_INSTRUCTION and [k for k, _ in posts_of(body)] == [1, 2, 3]
    sch = body["generationConfig"]["responseSchema"] if prov == "gemini" else body["response_format"]["json_schema"]["schema"]
    item = sch["properties"]["results"]["items"]
    assert list(item["properties"]) == ["id", *P.SIGNALS] and item["required"] == ["id", *P.SIGNALS]
    if prov == "groq":
        assert body["response_format"]["json_schema"]["strict"] is True and item["additionalProperties"] is False and body["model"] == GRQ


def test_output_token_budget_scales_with_the_batch_and_is_capped(cfg):
    m = cfg["model"]
    one = V.gemini_batch_body(["a b"] * 1, m)["generationConfig"]["maxOutputTokens"]
    ten = V.gemini_batch_body(["a b"] * 10, m)["generationConfig"]["maxOutputTokens"]
    assert ten == 10 * one == 10 * m["providers"]["gemini"]["max_output_tokens"]
    big = json.loads(json.dumps(m)); big["batch"]["token_cap"] = 3000
    assert V.gemini_batch_body(["a b"] * 10, big)["generationConfig"]["maxOutputTokens"] == 3000


@pytest.mark.parametrize("bad", [[], ["x"] * 21, ["ok", ""], ["ok", "a <post id=\"1\"> b"], ["ok", "a </post> b"], ["ok", "a\x07b"]])
def test_bad_batches_are_refused(cfg, bad):
    with pytest.raises(V.RequestError):
        V.gemini_batch_body(bad, cfg["model"])


# ---------------------------------------------------------------- válasz-értelmezés címenként

def parse(body_posts, raw, prov="gemini"):
    return V.parse_batch_response(prov, raw.status, raw.text, body_posts, run.load_config()["model"], raw.retry_after)


@pytest.mark.parametrize("prov", ["gemini", "groq"])
def test_ok_batch_gives_one_outcome_per_post_in_order(cfg, prov):
    posts = ["Alma körte szilva", "Dió mogyoró barack", "Cseresznye meggy"]
    body = V.BATCH_BUILDERS[prov](posts, cfg["model"])
    out = parse(posts, batch_raw(body, scores=lambda k, p: (k - 1, 0, 0, 0)), prov)
    assert out.kind == "ok" and [i.kind for i in out.items] == ["ok"] * 3 and [i.score["total"] for i in out.items] == [0, 1, 2] and out.usage["total_tokens"] == 150 + 72 * 3


def test_per_title_failures_do_not_fail_the_batch_and_the_reasons_are_specific(cfg):
    posts = ["Alma körte szilva", "Dió mogyoró barack", "Cseresznye meggy", "Citrom lime"]
    body = V.gemini_batch_body(posts, cfg["model"])

    def mut(items):
        items[0]["curiosity_gap"]["span"] = "nincs ilyen szó"                    # a span nem része a címnek
        items[1] = {**items[1], "total": 5}                                       # extra kulcs
        items.append({**items[2]})                                                # duplikált azonosító
        items.append({**items[3], "id": 99})                                      # ismeretlen azonosító: figyelmen kívül marad
        return items
    out = parse(posts, batch_raw(body, mutate=mut))
    kinds = [i.kind for i in out.items]
    assert out.kind == "ok" and kinds == ["invalid", "invalid", "invalid", "ok"] and "többször" in out.items[2].detail and "span" in out.items[0].detail
    miss = parse(posts, batch_raw(body, drop=(2,)))
    assert [i.kind for i in miss.items] == ["ok", "invalid", "ok", "ok"] and "hiányzik" in miss.items[1].detail


@pytest.mark.parametrize("text", ["nem json", "[]", json.dumps({"results": "x"}), json.dumps({"results": [], "extra": 1}), json.dumps({"items": []})])
def test_a_broken_envelope_structure_is_an_invalid_batch(cfg, text):
    posts = ["Alma körte szilva", "Dió mogyoró"]
    d = {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}
    out = parse(posts, mr.Raw(200, json.dumps(d)))
    assert out.kind == "invalid" and out.items == []


@pytest.mark.parametrize("raw,kind", [
    (mr.Raw(200, json.dumps({"candidates": [{"finishReason": "MAX_TOKENS"}]})), "truncated"),
    (mr.Raw(200, json.dumps({"promptFeedback": {"blockReason": "SAFETY"}})), "blocked"),
    (mr.Raw(200, json.dumps({"candidates": []})), "empty"),
    (mr.Raw(429, json.dumps({"error": {"code": 429, "message": "x", "details": DAY_DET}})), "quota_day"),
    (mr.Raw(503, json.dumps({"error": {"message": "over"}})), "transient"),
])
def test_envelope_errors_are_classified_like_in_single_mode(raw, kind):
    assert parse(["Alma körte szilva", "Dió mogyoró"], raw).kind == kind


# ---------------------------------------------------------------- csomagok és futás

def test_partition_is_deterministic_complete_and_independent_of_input_order(cfg, frozen):
    res, titles = frozen
    ids = [t["id"] for t in titles]
    a, b = BR.partition(ids, 10, cfg["seed"]), BR.partition(list(reversed(ids)), 10, cfg["seed"])
    assert a == b and sorted(i for x in a for i in x) == sorted(ids) and [len(x) for x in a] == [10] * 5
    assert BR.partition(ids, 5, cfg["seed"]) != BR.partition(ids, 10, cfg["seed"])[:1] * 2
    assert a != [ids[i:i + 10] for i in range(0, 50, 10)] and a != [sorted(ids)[i:i + 10] for i in range(0, 50, 10)]      # nem a feed és nem az azonosító sorrendje: a szomszédok véletlenek


@pytest.mark.parametrize("prov", ["gemini", "groq"])
def test_full_batch_run_scores_every_title_once_with_few_requests(frozen, cfg, prov):
    tr = BScript()
    rep, d = go(frozen, cfg, tr, prov, size=10)
    assert rep["status"] == "complete" and rep["n_ok"] == 50 and len(tr.calls) == 5 == rep["requests_total"] and rep["failover_allowed"] is False
    assert rep["workload"] == "measurement_batch" and rep["batch_size"] == 10 and rep["providers_used"] == [prov]
    sc = jl(d / "scores.jsonl")
    assert len(sc) == 50 and len({s["id"] for s in sc}) == 50 and all(s["batch_size"] == 10 for s in sc)
    for l in jl(d / "log.jsonl"):
        assert l["provider"] == prov and l["workload"] == "measurement_batch" and len(l["ids"]) == 10 and l["usage"] and l["outcome"] == "ok"
    assert rep["prompt_sha256"] == V.sha256_text(P.SYSTEM_INSTRUCTION)


def test_invalid_title_is_retried_once_in_a_smaller_batch_then_fails_for_good(frozen, cfg):
    res, titles = frozen
    bad_post = titles[7]["title"]

    def responder(body):                                                         # ez a cím mindig rossz spant kap
        def mut(items):
            for it in items:
                pass
            return items
        raw = batch_raw(body, scores=lambda k, p: (1, 0, 0, 0))
        d = json.loads(raw.text); txt = d["candidates"][0]["content"]["parts"][0]["text"] if "candidates" in d else d["choices"][0]["message"]["content"]
        obj = json.loads(txt)
        for it, (k, p) in zip(obj["results"], posts_of(body)):
            if p == bad_post:
                it["curiosity_gap"] = {"span": "nincs", "reason": "x", "score": 1}
        txt2 = json.dumps(obj, ensure_ascii=False)
        d["candidates"][0]["content"]["parts"][0]["text"] = txt2
        return mr.Raw(200, json.dumps(d), None, 100)
    tr = BScript(default=responder)
    rep, d = go(frozen, cfg, tr, size=10)
    assert rep["n_ok"] == 49 and rep["n_failed"] == 1 and rep["status"] == "complete"
    assert len(tr.calls) == 5 + 1 + 0 and len(posts_of(tr.calls[-1][1])) == 1       # öt csomag + egy 1 elemű újrapróba csomag
    rows = {r["id"]: r for r in __import__("csv").DictReader((d / "results.csv").open(encoding="utf-8", newline=""))}
    assert rows[titles[7]["id"]]["status"] == "invalid"


def test_truncated_batches_are_halved_until_they_fit(frozen, cfg):
    d_raw = lambda body: mr.Raw(200, json.dumps({"candidates": [{"finishReason": "MAX_TOKENS"}]})) if len(posts_of(body)) > 3 else batch_raw(body)
    tr = BScript(default=d_raw)
    rep, d = go(frozen, cfg, tr, size=10)
    sizes = __import__("collections").Counter(len(posts_of(b)) for _, b in tr.calls)
    assert rep["status"] == "complete" and rep["n_ok"] == 50 and dict(sizes) == {10: 5, 5: 10, 3: 10, 2: 10} and rep["requests_total"] == 35
    assert {s["batch_size"] for s in jl(d / "scores.jsonl")} <= {2, 3}                      # a végső pontszámok kis csomagokból jöttek


def test_a_blocked_batch_is_split_so_only_the_offending_title_fails(frozen, cfg):
    res, titles = frozen
    poison = titles[11]["title"]
    block = lambda body: mr.Raw(200, json.dumps({"promptFeedback": {"blockReason": "SAFETY"}})) if any(p == poison for _, p in posts_of(body)) else batch_raw(body)
    rep, d = go(frozen, cfg, BScript(default=block), size=10)
    rows = {r["id"]: r for r in __import__("csv").DictReader((d / "results.csv").open(encoding="utf-8", newline=""))}
    assert rep["n_ok"] == 49 and rows[titles[11]["id"]]["status"] == "blocked" and sum(1 for r in rows.values() if r["status"] == "ok") == 49


def test_daily_quota_stops_keeps_done_batches_and_resume_does_not_resend(frozen, cfg):
    quota = mr.Raw(429, json.dumps({"error": {"code": 429, "message": "per day " + CANARY, "details": DAY_DET}}), None, 40)
    tr = BScript([lambda b: batch_raw(b), lambda b: batch_raw(b), quota])
    rep, d = go(frozen, cfg, tr, size=10, clock=Clock(T0))
    assert rep["status"] == "stopped_quota" and rep["n_ok"] == 20 and rep["n_pending"] == 30 and rep["resume_after_utc"] == "2026-11-15T08:05:00Z"
    done = {p for _, b in tr.calls[:2] for _, p in posts_of(b)}
    with pytest.raises(mr.RunRefused, match="még nem jött el"):
        go(frozen, cfg, BScript(), size=10, clock=Clock(datetime(2026, 11, 15, 8, 4, 59, tzinfo=UTC)))
    tr2 = BScript()
    rep2, d = go(frozen, cfg, tr2, size=10, clock=Clock(datetime(2026, 11, 15, 8, 5, tzinfo=UTC)))
    assert rep2["status"] == "complete" and rep2["n_ok"] == 50 and len(tr2.calls) == 3 and len(rep2["probes"]) == 1
    assert not done & {p for _, b in tr2.calls for _, p in posts_of(b)}
    assert CANARY not in (d / "log.jsonl").read_text(encoding="utf-8") + (d / "quota_stops.jsonl").read_text(encoding="utf-8")


def test_resume_refuses_a_different_batch_size_or_a_single_mode_state(frozen, cfg):
    res, titles = frozen
    quota = mr.Raw(429, json.dumps({"error": {"code": 429, "message": "per day", "details": DAY_DET}}), None, 40)
    go(frozen, cfg, BScript([quota]), size=10, clock=Clock(T0))
    with pytest.raises(mr.RunRefused, match="eltér"):
        go(frozen, cfg, BScript(), size=5, clock=Clock(datetime(2026, 11, 15, 8, 5, tzinfo=UTC)))
    s = Script("gemini", [quota_raw := mr.Raw(429, json.dumps({"error": {"code": 429, "message": "per day", "details": DAY_DET}}), None, 40)])
    clock = Clock(T0)
    mr.run_measurement(titles, "gemini", s, cfg, res, "egyes", GEM, now=clock.now, sleep=clock.sleep, monotonic=clock.monotonic)
    with pytest.raises(mr.RunRefused, match="eltér"):
        BR.run_batch_measurement(titles, "gemini", BScript(), cfg, res, "egyes", GEM, 10, now=Clock(datetime(2026, 11, 15, 8, 5, tzinfo=UTC)).now)


def test_gates_freeze_size_and_no_switch_path(frozen, cfg, tmp_path):
    res, titles = frozen
    for size in (0, 1, 21, True, "10"):
        with pytest.raises(mr.RunRefused):
            go(frozen, cfg, BScript(), size=size)
    with pytest.raises(NotFrozen):
        BR.run_batch_measurement(titles, "gemini", BScript(), cfg, tmp_path / "ures", "x", GEM, 10)
    src = (Path(BR.__file__)).read_text(encoding="utf-8")
    import ast
    calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "transport"]
    assert len(calls) == 1 and "secondary" not in src and "switch" not in src.lower().replace("nincs szolgáltatóváltás", "")


def test_the_batch_dryrun_verifies_every_request_and_detects_tampering(frozen, cfg):
    res, titles = frozen
    batches, rows = BR.build_requests(titles, "gemini", cfg, 10)
    assert len(rows) == 5 and not BR.verify_requests(rows, titles, "gemini", cfg)
    rows[2]["body"]["contents"][0]["parts"][0]["text"] += " human_mean 0.4"
    assert BR.verify_requests(rows, titles, "gemini", cfg)
    batches, rows = BR.build_requests(titles, "gemini", cfg, 10)
    rows[1]["ids"] = rows[1]["ids"][:-1]
    assert BR.verify_requests(rows, titles, "gemini", cfg)


# ---------------------------------------------------------------- összevetés az egy-cím-egy-kérés móddal

def single_ok(model_body):
    return ok_raw(provider_of(model_body), model_body)


def two_runs(frozen, cfg, bscript_default=None):
    res, titles = frozen
    c1 = Clock()
    s = Script("gemini")
    mr.run_measurement(titles, "gemini", s, cfg, res, "egyes", GEM, now=c1.now, sleep=c1.sleep, monotonic=c1.monotonic)
    go(frozen, cfg, BScript(default=bscript_default), size=10, name="csomag")
    return res / "model_runs" / "egyes", res / "model_runs" / "csomag"


def test_spearman_and_ranks_are_computed_correctly():
    assert CMP.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert CMP.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert CMP.spearman([1, 1, 2, 2], [1, 2, 1, 2]) == pytest.approx(0.0)
    assert CMP.spearman([1, 2], [1, 2]) is None and CMP.spearman([3, 3, 3], [1, 2, 3]) is None
    assert CMP._ranks([5, 1, 1, 9]) == [3.0, 1.5, 1.5, 4.0]


def test_compare_identical_scores_show_full_agreement_and_fewer_requests_and_tokens(frozen, cfg):
    a, b = two_runs(frozen, cfg)                                                 # mindkét mód a cím első szavát jelöli: azonos pontszámok
    r = CMP.compare(a, b, cfg["model"]["batch"]["accept"])
    assert r["n_common_ok"] == 50 and r["exact_total_agreement"] == 1.0 and r["mean_abs_total_diff"] == 0 and r["spearman_total"] in (None, 1.0) or abs(r["spearman_total"] - 1) < 1e-9
    assert r["requests_ratio_B_over_A"] == pytest.approx(5 / 50) and r["tokens_per_title_ratio_B_over_A"] < 1 and r["B"]["batch_size"] == 10 and r["A"]["batch_size"] == 1
    assert all(v == 1.0 for v in r["per_signal_exact_agreement"].values())


def test_compare_detects_a_systematic_shift_and_fails_the_acceptance(frozen, cfg):
    res, titles = frozen
    c1 = Clock()
    varied = lambda body: ok_raw(provider_of(body), body, scores=(1 + (len(posts_one(body)) % 2), 0, 0, 0))
    mr.run_measurement(titles, "gemini", Script("gemini", [varied] * 50), cfg, res, "egyes", GEM, now=c1.now, sleep=c1.sleep, monotonic=c1.monotonic)
    shifted = lambda body: batch_raw(body, scores=lambda k, p: (0, 2, 2, 2))
    go(frozen, cfg, BScript(default=shifted), size=10, name="csomag")
    r = CMP.compare(res / "model_runs/egyes", res / "model_runs/csomag", cfg["model"]["batch"]["accept"])
    assert r["mean_abs_total_diff"] > 2 and r["mean_signed_total_diff_B_minus_A"] > 2 and r["accept"]["mean_abs_diff_ok"] is False and r["accept"]["all_ok"] is False


def posts_one(body):
    t = body["contents"][0]["parts"][0]["text"] if "contents" in body else body["messages"][1]["content"]
    return t


def test_compare_command_reads_only_the_two_run_folders(frozen, cfg, capsys):
    a, b = two_runs(frozen, cfg)
    out = run.main(["compare-runs", str(a), str(b)])
    j = json.loads(capsys.readouterr().out)
    assert out == 0 and j["n_common_ok"] == 50 and "accept" in j and run.main(["compare-runs", str(a)]) == 2


# ---------------------------------------------------------------- a futtató parancs csomagos módja

def test_live_check_and_run_with_batch_size_over_real_http_to_a_local_server(fake, cfg, bundle_path, tmp_path, monkeypatch, capsys):
    f = fake(lambda n, path, body: (200, batch_raw(body).text, None))
    for k in ("GEMINI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    base = ["--provider", "gemini", "--bundle", str(bundle_path), "--out-dir", str(tmp_path / "o"), "--run-name", "r", "--model", GEM]
    assert RL.main(base + ["--mode", "check", "--batch-size", "10"]) == 0
    c = json.loads(capsys.readouterr().out)
    assert c["n_requests"] == 5 and c["batch_size"] == 10 and c["network_used"] is False and c["status"] == "OK"
    for bad in ("1", "21", "-3"):
        assert RL.main(base + ["--mode", "check", "--batch-size", bad]) == 2
    capsys.readouterr()
    real = RL.HttpTransport
    monkeypatch.setattr(RL, "HttpTransport", lambda p, k, t, base_url=None: real(p, k, t, base_url=f.url))
    orig = RL.run
    monkeypatch.setattr(RL, "run", lambda *a, **k: orig(*a, **k, **{"now": Clock().now, "sleep": Clock().sleep, "monotonic": Clock().monotonic}))
    code = RL.main(base + ["--mode", "run", "--live", "--confirm", RL.CONFIRM, "--batch-size", "10"])
    out = capsys.readouterr().out
    j = json.loads(out)
    assert code == 0 and j["status"] == "complete" and j["batch_size"] if "batch_size" in j else True
    assert len(f.calls) == 5 and KEY not in out


def test_workflow_passes_the_batch_size_through_env_only_and_defaults_to_single():
    import yaml
    y = yaml.safe_load((Path(BR.__file__).resolve().parents[2] / ".github/workflows/pilot-model-run.yml").read_text(encoding="utf-8"))
    ins = (y.get("on") or y.get(True))["workflow_dispatch"]["inputs"]
    assert ins["batch_size"]["default"] == "0"
    for s in y["jobs"]["run"]["steps"]:
        if "run_live" in s.get("run", ""):
            assert '--batch-size "$BATCH_SIZE"' in s["run"] and s["env"]["BATCH_SIZE"] == "${{ inputs.batch_size }}" and "inputs." not in s["run"]
