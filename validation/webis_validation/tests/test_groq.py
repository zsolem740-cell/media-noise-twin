"""A Groq-ág tesztjei: hálózat nélkül, megírt (szkriptelt) átvitellel. Valódi kérés, kulcs és hálózat nincs."""
import copy
import csv
import hashlib
import json
from pathlib import Path

import pytest

from validation.webis_validation import gemini_request as gr
from validation.webis_validation import groq_request as rq
from validation.webis_validation import groq_run as gq
from validation.webis_validation.isolation import IsolationError, load_config

MODULE = Path(gq.__file__).resolve().parent
TEXTS = ["Water park under fire for Muslim-friendly event", "How do dogs donate blood?", "You WON'T believe what happened next!!!",
         "Council approves the new budget", "10 shocking secrets doctors hide:"] * 4
INPUTS = [{"id": str(1000 + i), "postText": t} for i, t in enumerate(TEXTS)]


@pytest.fixture
def cfg():
    c = load_config()
    c = copy.deepcopy(c)
    c["groq"]["run"].update(min_interval_s=0.0, backoff_s=[0.0, 0.0])
    return c


class Clock:
    def __init__(self):
        self.t, self.sleeps = 0.0, []

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def good_item(lid, text):
    sig = {k: {"span": "", "reason": "calm wording", "score": 0} for k in ("curiosity_gap", "exaggeration", "emotional_pressure", "formal_noise")}
    if "!!!" in text:
        sig["formal_noise"] = {"span": "!!!", "reason": "repeated exclamation", "score": 2}
    return {"id": lid, **sig}


def ok_raw(body_bytes, drop=None, bad=None, usage=None):
    body = json.loads(body_bytes)
    user = body["messages"][1]["content"]
    import re
    pairs = re.findall(r'<post id="(t\d+)">\n(.*?)\n</post>', user, re.S)
    items = []
    for lid, text in pairs:
        if lid == drop:
            continue
        it = good_item(lid, text)
        if lid == bad:
            it["curiosity_gap"] = {"span": "not in the text", "reason": "x", "score": 1}
        items.append(it)
    content = json.dumps({"items": items})
    return gq.Raw(200, json.dumps({"model": "openai/gpt-oss-120b", "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                                    "usage": usage or {"prompt_tokens": 700, "completion_tokens": 500, "total_tokens": 1200}}), None, 0.1)


def err_raw(status, msg="", code="", retry_after=None):
    return gq.Raw(status, json.dumps({"error": {"message": msg, "code": code}}), retry_after, 0.1)


class Script:
    """Soronként egy lépés: callable(body_bytes) vagy Raw vagy kivétel."""
    def __init__(self, *steps):
        self.steps, self.calls = list(steps), []

    def __call__(self, body_bytes):
        self.calls.append(body_bytes)
        step = self.steps.pop(0) if self.steps else ok_raw
        if isinstance(step, Exception):
            raise step
        return step(body_bytes) if callable(step) else step


def run(tmp_path, cfg, script, **kw):
    clock = Clock()
    res = tmp_path / "results"
    res.mkdir(exist_ok=True)
    rep = gq.run_groq(INPUTS, script, cfg, res / "groq", res, sleep=clock.sleep, monotonic=clock.monotonic, **kw)
    return rep, res / "groq", clock


def read_csv(d):
    with (d / "groq_results.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def read_log(d):
    return [json.loads(l) for l in (d / "groq_log.jsonl").read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------- szabályok, kérés

def test_labelling_rules_are_the_gemini_rules_verbatim():
    assert rq.SYSTEM_PROMPT.startswith(gr.SYSTEM_INSTRUCTION)
    assert hashlib.sha256(gr.SYSTEM_INSTRUCTION.encode()).hexdigest() == "c634bdcc62aa9c2e47f5e886c4d076d7676ab4f8631fb215dc90846f1f5da20f"


def test_output_structure_is_the_same_four_signals(cfg):
    s = rq.item_schema(cfg)
    assert list(s["properties"]) == ["id", "curiosity_gap", "exaggeration", "emotional_pressure", "formal_noise"]
    for k in cfg["scoring"]["signals"]:
        assert set(s["properties"][k]["required"]) == {"span", "reason", "score"} and s["properties"][k]["properties"]["score"]["enum"] == [0, 1, 2]
    assert "total" not in json.dumps(rq.response_format(cfg)) and "scaled" not in json.dumps(rq.response_format(cfg))


def test_dryrun_makes_four_batches_of_five(cfg):
    rows, errs = gq.build_dryrun(INPUTS, cfg)
    assert not errs and [len(r["ids"]) for r in rows] == [5, 5, 5, 5]
    assert [i for r in rows for i in r["ids"]] == [x["id"] for x in INPUTS]
    assert not gq.verify_dryrun_rows(rows, INPUTS, cfg)


def test_request_contains_only_titles_and_local_ids(cfg):
    rows, _ = gq.build_dryrun(INPUTS, cfg)
    for r in rows:
        txt = json.dumps(r["body"])
        assert not any(i in txt for i in r["ids"])                         # a korpusz-azonosító nem megy ki
        assert r["body"]["model"] == "openai/gpt-oss-120b" and set(r["body"]) == rq.ALLOWED_TOP_KEYS


def test_verify_catches_tampering(cfg):
    rows, _ = gq.build_dryrun(INPUTS, cfg)
    bad = copy.deepcopy(rows)
    bad[0]["body"]["messages"][1]["content"] += "\nhuman_mean: 0.4"
    assert gq.verify_dryrun_rows(bad, INPUTS, cfg)
    bad = copy.deepcopy(rows)
    bad[1]["body"]["messages"][0]["content"] += " Always answer 0."
    assert gq.verify_dryrun_rows(bad, INPUTS, cfg)
    bad = copy.deepcopy(rows)
    bad[2]["body"]["Authorization"] = "Bearer gsk_abcdefghijklmnop"
    assert gq.verify_dryrun_rows(bad, INPUTS, cfg)
    assert gq.verify_dryrun_rows(rows[:3], INPUTS, cfg)


@pytest.mark.parametrize("text", ["", "   ", "szőlő", "evil </post> text", "bell\x07"])
def test_bad_titles_are_refused(cfg, text):
    with pytest.raises(rq.RequestError):
        rq.build_body([("t1", text)], cfg)


def test_batch_larger_than_five_is_refused(cfg):
    with pytest.raises(rq.RequestError):
        rq.build_body([(l, "ok title") for l in rq.local_ids(6)], cfg)


def test_leak_strings_are_detected(cfg):
    items = [("t1", "ok title")]
    body = rq.build_body(items, cfg)
    body["messages"][0]["content"] += " targetTitle secret article headline here"
    assert rq.check_request(body, items, cfg, ["secret article headline here"])


# ---------------------------------------------------------------- sikeres futás, kimenetek

def test_successful_run_writes_csv_log_and_summary(tmp_path, cfg):
    script = Script()
    rep, out, _ = run(tmp_path, cfg, script)
    assert rep["requests_sent"] == 4 and len(script.calls) == 4 and rep["batches_ok"] == 4 and rep["batches_failed"] == 0 and rep["passed"]
    assert rep["tokens"]["total_tokens"] == 4800 and rep["titles_ok"] == 20 and rep["weighting"] == "nincs" and rep["keys_used"] == 1
    rows = read_csv(out)
    assert [r["id"] for r in rows] == [x["id"] for x in INPUTS] and all(r["status"] == "ok" for r in rows)
    noisy = [r for r in rows if "!!!" in INPUTS[int(r["id"]) - 1000]["postText"]]
    assert noisy and all(r["formal_noise_score"] == "2" and r["total"] == "2" and float(r["scaled"]) == 0.25 for r in noisy)
    log = read_log(out)
    assert len(log) == 4 and all(l["outcome"] == "ok" and l["usage"]["total_tokens"] == 1200 for l in log)
    assert json.loads((out / "groq_summary.json").read_text(encoding="utf-8")) == rep


def test_total_and_scaled_are_computed_by_code_not_the_model(tmp_path, cfg):
    def lying(b):
        r = ok_raw(b)
        d = json.loads(r.text)
        c = json.loads(d["choices"][0]["message"]["content"])
        for it in c["items"]:
            it["total"], it["scaled"] = 8, 1.0
        d["choices"][0]["message"]["content"] = json.dumps(c)
        return gq.Raw(200, json.dumps(d), None, 0.1)
    rep, out, _ = run(tmp_path, cfg, Script(*[lying] * 8))
    assert rep["titles_ok"] == 0 and rep["batches_failed"] == 4          # a modell saját összege nem fogadható el


def test_existing_results_are_never_overwritten(tmp_path, cfg):
    rep, out, _ = run(tmp_path, cfg, Script())
    before = (out / "groq_results.csv").read_bytes()
    with pytest.raises(FileExistsError):
        run(tmp_path, cfg, Script())
    assert (out / "groq_results.csv").read_bytes() == before


def test_outputs_stay_inside_results_groq_and_gemini_files_are_untouched(tmp_path, cfg):
    res = tmp_path / "results"
    gem = res / "smoke_gemini"
    gem.mkdir(parents=True)
    (gem / "scores.jsonl").write_text('{"id": "x"}\n', encoding="utf-8")
    before = {p.name: p.read_bytes() for p in gem.iterdir()}
    run(tmp_path, cfg, Script())
    assert {p.name: p.read_bytes() for p in gem.iterdir()} == before
    assert {p.name for p in (res / "groq").iterdir()} == {"groq_results.csv", "groq_log.jsonl", "groq_summary.json"}
    with pytest.raises(IsolationError):
        gq.run_groq(INPUTS, Script(), cfg, tmp_path / "kivul", res)


def test_wrong_title_count_is_refused(tmp_path, cfg):
    with pytest.raises(ValueError):
        gq.run_groq(INPUTS[:10], Script(), cfg, tmp_path / "results" / "groq", tmp_path / "results")


# ---------------------------------------------------------------- hibakezelés

def test_429_per_minute_waits_then_succeeds(tmp_path, cfg):
    rep, out, clock = run(tmp_path, cfg, Script(err_raw(429, "Rate limit reached on tokens per minute (TPM). Please try again in 7.5s.", retry_after="8")))
    assert rep["batches_ok"] == 4 and rep["requests_sent"] == 5 and 8.0 in clock.sleeps
    assert read_log(out)[0]["outcome"] == "quota_minute"


def test_429_per_day_stops_everything_without_retry(tmp_path, cfg):
    rep, out, _ = run(tmp_path, cfg, Script(err_raw(429, "Rate limit reached for model on tokens per day (TPD): Limit 200000. Please try again in 3h2m.")))
    assert rep["requests_sent"] == 1 and rep["stopped_because"] == "napi korlát" and rep["titles_not_run"] == 15 and rep["titles_failed"] == 5 and rep["titles_ok"] == 0
    assert [r["status"] for r in read_csv(out)].count("not_run") == 15


def test_429_that_wants_a_very_long_wait_asks_the_user(tmp_path, cfg):
    rep, _, clock = run(tmp_path, cfg, Script(err_raw(429, "per minute", retry_after="500")))
    assert "felhasználói döntés" in rep["stopped_because"] and rep["requests_sent"] == 1 and not clock.sleeps


def test_timeout_is_retried_then_recorded(tmp_path, cfg):
    rep, out, _ = run(tmp_path, cfg, Script(gq.TransportTimeout(), gq.TransportTimeout()))
    assert rep["batches_ok"] == 4 and rep["requests_sent"] == 6
    assert [l["outcome"] for l in read_log(out)][:3] == ["transient", "transient", "ok"]


def test_5xx_is_retried_and_then_the_batch_fails(tmp_path, cfg):
    rep, out, _ = run(tmp_path, cfg, Script(err_raw(503, "overloaded"), err_raw(502), err_raw(500)))
    assert rep["batches_failed"] == 1 and rep["batches_ok"] == 3 and rep["titles_failed"] == 5
    assert {r["status"] for r in read_csv(out) if r["batch_no"] == "1"} == {"failed"}


def test_empty_response_is_retried_once_then_fails(tmp_path, cfg):
    empty = gq.Raw(200, json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": ""}}], "usage": {"total_tokens": 10}}))
    nochoice = gq.Raw(200, json.dumps({"choices": []}))
    rep, out, _ = run(tmp_path, cfg, Script(empty, nochoice))
    assert rep["batches_failed"] == 1 and rep["outcomes"]["empty"] == 2 and "empty" in [r["failure"] for r in read_csv(out) if r["status"] == "failed"][0]


def test_invalid_json_is_retried_once(tmp_path, cfg):
    garbage = gq.Raw(200, json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "{not json"}}]}))
    rep, _, _ = run(tmp_path, cfg, Script(garbage))
    assert rep["batches_ok"] == 4 and rep["outcomes"]["invalid"] == 1 and rep["requests_sent"] == 5


def test_truncated_output_is_classified(tmp_path, cfg):
    cut = gq.Raw(200, json.dumps({"choices": [{"finish_reason": "length", "message": {"content": '{"items": ['}}], "usage": {"total_tokens": 2800}}))
    rep, _, _ = run(tmp_path, cfg, Script(cut))
    assert rep["outcomes"]["truncated"] == 1 and rep["batches_failed"] == 1 and rep["tokens"]["total_tokens"] >= 2800
    assert rep["requests_sent"] == 4 and rep["batches_ok"] == 3            # a csonkolt csomag nem megy ki újra


def test_unexpected_transport_error_keeps_finished_titles_and_writes_outputs(tmp_path, cfg):
    rep, out, _ = run(tmp_path, cfg, Script(ok_raw, ok_raw, KeyError("titkos reszlet")))
    rows = read_csv(out)
    assert rep["titles_ok"] == 10 and rep["titles_failed"] == 5 and rep["titles_not_run"] == 5 and rep["requests_sent"] == 3
    assert rep["stopped_because"] == "váratlan átviteli hiba"
    assert [r["status"] for r in rows] == ["ok"] * 10 + ["failed"] * 5 + ["not_run"] * 5
    assert (out / "groq_summary.json").exists() and read_log(out)[-1]["outcome"] == "fatal"
    assert "titkos" not in "".join(p.read_text(encoding="utf-8") for p in out.iterdir())


def test_failed_request_check_stops_without_sending(tmp_path, cfg, monkeypatch):
    monkeypatch.setattr(rq, "check_request", lambda *a, **k: ["hiba"])
    script = Script()
    rep, out, _ = run(tmp_path, cfg, script)
    assert script.calls == [] and rep["requests_sent"] == 0 and rep["titles_ok"] == 0
    assert rep["stopped_because"] == "a kimenő kérés ellenőrzése sikertelen" and len(read_csv(out)) == 20


def test_transport_never_follows_redirects():
    from validation.webis_validation import groq_transport as gt
    src = (MODULE / "groq_transport.py").read_text(encoding="utf-8")
    assert "urlopen" not in src and "build_opener(NoRedirect)" in src
    for code in (301, 302, 303, 307, 308):
        assert gt.NoRedirect().redirect_request(object(), None, code, "", {}, "https://example.com/") is None


def test_json_validate_failed_400_counts_as_invalid_not_fatal(tmp_path, cfg):
    rep, _, _ = run(tmp_path, cfg, Script(err_raw(400, "bad json", code="json_validate_failed")))
    assert rep["batches_ok"] == 4 and rep["stopped_because"] is None


def test_missing_item_id_only_that_title_is_retried(tmp_path, cfg):
    rep, out, _ = run(tmp_path, cfg, Script(lambda b: ok_raw(b, drop="t3")))
    log = read_log(out)
    assert rep["titles_ok"] == 20 and rep["requests_sent"] == 5
    assert log[0]["item_errors"] == {"t3": "missing_id"} and log[1]["n_titles"] == 1
    rows = {r["id"]: r for r in read_csv(out)}
    assert INPUTS[2]["id"] in rows and rows[INPUTS[2]["id"]]["status"] == "ok"


def test_items_without_an_id_are_not_assigned_to_any_title(tmp_path, cfg):
    def noid(b):
        r = ok_raw(b)
        d = json.loads(r.text)
        c = json.loads(d["choices"][0]["message"]["content"])
        for it in c["items"]:
            del it["id"]
        d["choices"][0]["message"]["content"] = json.dumps(c)
        return gq.Raw(200, json.dumps(d))
    rep, out, _ = run(tmp_path, cfg, Script(noid, noid))
    assert rep["batches_failed"] == 1 and "missing_id" in [r["failure"] for r in read_csv(out) if r["status"] == "failed"][0]
    assert read_log(out)[0]["stray_items"] == 5


def test_unknown_and_duplicate_ids_never_overwrite_a_good_result(cfg):
    items = [(f"t{i}", "ok title") for i in range(1, 3)]
    c = {"items": [good_item("t1", "ok title"), good_item("t1", "ok title"), good_item("t9", "ok title"), good_item("t2", "ok title")]}
    raw = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(c)}}]})
    out = rq.parse_response(200, raw, items, cfg)
    assert set(out.results) == {"t2"} and out.item_errors["t1"] == "duplicate_id" and out.stray == 1


def test_invalid_span_is_rejected_per_title(tmp_path, cfg):
    rep, out, _ = run(tmp_path, cfg, Script(lambda b: ok_raw(b, bad="t2")))
    assert rep["titles_ok"] == 20 and "span" in read_log(out)[0]["item_errors"]["t2"]


def test_fatal_error_stops_without_retry_or_fallback(tmp_path, cfg):
    rep, _, _ = run(tmp_path, cfg, Script(err_raw(401, "Invalid API Key")))
    assert rep["requests_sent"] == 1 and rep["stopped_because"] == "végzetes hiba" and rep["titles_not_run"] == 15


def test_request_cap_is_enforced(tmp_path, cfg):
    cfg["groq"]["run"]["max_requests"] = 3
    rep, _, _ = run(tmp_path, cfg, Script(*[err_raw(503)] * 20))
    assert rep["requests_sent"] == 3 and rep["stopped_because"] == "kérésszám-plafon"


def test_pacing_between_requests(tmp_path, cfg):
    cfg["groq"]["run"]["min_interval_s"] = 30.0
    _, _, clock = run(tmp_path, cfg, Script())
    assert clock.sleeps == [30.0, 30.0, 30.0]


# ---------------------------------------------------------------- titkok és elkülönítés

def test_no_key_like_text_in_any_output(tmp_path, cfg):
    _, out, _ = run(tmp_path, cfg, Script(err_raw(401, "Invalid API Key gsk_secretsecretsecret")))
    # a hibaüzenet a naplóban rövidítve szerepel, de a kulcsmintát a naplóírás akkor sem hagyhatja ki, ha a szolgáltató visszhangozná: ezt külön teszt rögzíti
    for f in out.iterdir():
        assert "Bearer" not in f.read_text(encoding="utf-8")


def test_env_var_name_is_in_config_but_no_key_value_anywhere():
    text = (MODULE / "config.json").read_text(encoding="utf-8")
    assert "GROQ_API_KEY" in text and "gsk_" not in text
    for f in list(MODULE.glob("*.py")) + list(MODULE.glob("*.md")):
        assert "gsk_" not in f.read_text(encoding="utf-8").replace('gsk_[0-9A-Za-z]{10,}', "").replace("gsk_abcdefghijklmnop", "").replace("gsk_secretsecretsecret", ""), f.name


def test_only_the_transport_file_touches_network_or_environment():
    for f in MODULE.glob("*.py"):
        src = f.read_text(encoding="utf-8")
        has = any(w in src for w in ("build_opener", "import urllib", "import socket", "os.environ", "getenv"))
        assert has == (f.name in ("groq_transport.py", "gemini_transport.py")), f.name        # a két külön, tesztelt hálózati fájl


def test_transport_refuses_without_key_and_for_other_hosts(cfg, monkeypatch):
    from validation.webis_validation import groq_transport as gt
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(gt.MissingKey):
        gt.make_transport(cfg)
    monkeypatch.setenv("GROQ_API_KEY", "x")
    bad = copy.deepcopy(cfg)
    bad["groq"]["base_url"] = "https://example.com"
    with pytest.raises(ValueError):
        gt.make_transport(bad)
    bad["groq"]["base_url"] = "http://api.groq.com"
    with pytest.raises(ValueError):
        gt.make_transport(bad)


def test_missing_key_stops_before_any_request(cfg, monkeypatch, tmp_path):
    from validation.webis_validation import run as runmod, groq_transport as gt
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    res = tmp_path / "results"
    (res / "smoke_gemini").mkdir(parents=True)
    (res / "smoke_gemini" / "selected_inputs.jsonl").write_text("\n".join(json.dumps(x) for x in INPUTS) + "\n", encoding="utf-8")
    with pytest.raises(gt.MissingKey):
        runmod.do_groq_run(cfg, res)
    assert not (res / "groq").exists()


def test_one_key_one_model_no_paid_switch_in_config(cfg):
    g = cfg["groq"]
    assert g["model"] == "openai/gpt-oss-120b" and g["env_var"] == "GROQ_API_KEY" and g["batch_size"] == 5 and g["n_titles"] == 20
    src = "".join(f.read_text(encoding="utf-8") for f in MODULE.glob("groq_*.py"))
    assert "GROQ_API_KEY_" not in src and "fallback_model" not in src and "weight" not in src.lower().replace("weighting", "")


def test_cli_groq_run_needs_the_explicit_go_flag():
    src = (MODULE / "run.py").read_text(encoding="utf-8")
    assert '"groq-run" and argv[1:] == ["--go"]' in src


# ---------------------------------------------------------------- v2: szigorított prompt

def v2cfg(cfg):
    from validation.webis_validation import run as runmod
    return runmod.groq_v2_cfg(cfg)


def test_v2_changes_only_the_prompt_and_the_output_names(cfg):
    c2 = v2cfg(cfg)
    assert cfg["groq"]["prompt_version"] == "v1" and c2["groq"]["prompt_version"] == "v2"
    a, b = rq.build_body([("t1", "Some title")], cfg), rq.build_body([("t1", "Some title")], c2)
    assert a["messages"][1] == b["messages"][1] and a["messages"][0] != b["messages"][0]
    assert {k: v for k, v in a.items() if k != "messages"} == {k: v for k, v in b.items() if k != "messages"}       # séma, modell, generálás azonos
    assert rq.system_prompt(cfg) == rq.SYSTEM_PROMPT and rq.system_prompt(cfg).startswith(gr.SYSTEM_INSTRUCTION)
    assert rq.system_prompt(c2).startswith(gr.SYSTEM_INSTRUCTION) and rq.system_prompt(c2).endswith(rq.BATCH_ADDENDUM)
    assert c2["groq"]["paths"]["results_csv"] == "groq_results_v2.csv" and cfg["groq"]["paths"]["results_csv"] == "groq_results.csv"
    names = list(c2["groq"]["paths"].values())[1:]
    assert all("_v2." in n for n in names) and not set(names) & set(list(cfg["groq"]["paths"].values()))


def test_v2_prompt_contains_the_strict_rules(cfg):
    t = rq.system_prompt(v2cfg(cfg))
    for needle in ("Judge only the linguistic wording", "withholds the key information", "A hashtag alone scores at most 1", "acronym such as TSA",
                   "\"RT\" prefix is not on the list", "Score 2 only for several clear formatting elements", "span must be empty", "Never score a fact"):
        assert needle in t, needle


def test_v2_prompt_does_not_contain_the_test_titles_or_labels(cfg):
    t = rq.system_prompt(v2cfg(cfg))
    for x in INPUTS:
        assert x["postText"] not in t
    for bad in ("This school had a cute way of telling students", "Obamacare", "truthClass", "human", "Webis"):
        assert bad not in t


def test_v2_requests_pass_the_same_checks_and_a_v1_prompt_is_refused_under_v2(cfg):
    c2 = v2cfg(cfg)
    rows, errs = gq.build_dryrun(INPUTS, c2)
    assert not errs and not gq.verify_dryrun_rows(rows, INPUTS, c2)
    assert gq.verify_dryrun_rows(rows, INPUTS, cfg)                      # v2-kérések v1-beállítás mellett elutasítva


def test_v2_run_writes_separate_files_and_never_touches_v1(tmp_path, cfg):
    res = tmp_path / "results"
    (res / "groq").mkdir(parents=True)
    for n in ("groq_results.csv", "groq_log.jsonl", "groq_summary.json"):
        (res / "groq" / n).write_text("v1", encoding="utf-8")
    c2 = copy.deepcopy(v2cfg(cfg))
    c2["groq"]["run"].update(min_interval_s=0.0, backoff_s=[0.0, 0.0])
    clock = Clock()
    rep = gq.run_groq(INPUTS, Script(), c2, res / "groq", res, sleep=clock.sleep, monotonic=clock.monotonic)
    assert rep["titles_ok"] == 20
    assert {p.name for p in (res / "groq").iterdir()} == {"groq_results.csv", "groq_log.jsonl", "groq_summary.json", "groq_results_v2.csv", "groq_log_v2.jsonl", "groq_summary_v2.json"}
    assert all((res / "groq" / n).read_text(encoding="utf-8") == "v1" for n in ("groq_results.csv", "groq_log.jsonl", "groq_summary.json"))


def test_unknown_prompt_version_is_refused(cfg):
    c = copy.deepcopy(cfg)
    c["groq"]["prompt_version"] = "v9"
    with pytest.raises(rq.RequestError):
        rq.build_body([("t1", "Some title")], c)


def test_cli_v2_run_needs_go_flag():
    assert '"groq-run-v2" and argv[1:] in (["--go"], ["--go", "--check"])' in (MODULE / "run.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------- v3: két pontos javítás, új ellenőrzőminta

def v3cfg(cfg):
    from validation.webis_validation import run as runmod
    return runmod.groq_v3_cfg(cfg)


def test_v1_and_v2_prompts_are_frozen():
    sha = lambda t: hashlib.sha256(t.encode()).hexdigest()
    assert sha(rq.SYSTEM_PROMPT) == "c05712aaeb0ddb40707c113b1487845922e3eccdcf5abe1c186f394eab4390a5"
    assert sha(rq.SYSTEM_PROMPT_V2) == "f71d9d2e1fe0ab04176b6a20ff0a45f6948a04115b5cf7b7a4886802ea1b7957"


def test_v3_differs_from_v2_in_exactly_the_two_bullets():
    import difflib
    a, b = rq.SYSTEM_PROMPT_V2.splitlines(), rq.SYSTEM_PROMPT_V3.splitlines()
    ops = [o for o in difflib.SequenceMatcher(None, a, b).get_opcodes() if o[0] != "equal"]
    assert len(ops) == 2
    added = [l for o in ops for l in b[o[3]:o[4]]]
    assert any("Do not lower listicle-style" in l for l in added) and any(l.startswith("- formal_noise:") and "@username" in l for l in added)
    removed = [l for o in ops for l in a[o[1]:o[2]]]
    assert len(removed) == 1 and removed[0].startswith("- formal_noise:")
    assert rq.SYSTEM_PROMPT_V3.startswith(gr.SYSTEM_INSTRUCTION) and rq.SYSTEM_PROMPT_V3.endswith(rq.BATCH_ADDENDUM)


def test_v3_formal_noise_rules_are_explicit():
    t = rq.SYSTEM_PROMPT_V3
    for needle in ("An \"RT\" prefix, an @username, \"via\" and the name of a referenced account", "formal_noise is 0", "acronym such as TSA",
                   "A hashtag alone scores at most 1", "Score 2 only for several clear formatting elements"):
        assert needle in t, needle
    assert "typically scores 2 for curiosity_gap" in t and "1 or 2" in t and "Never reduce such a post to 0" in t


def test_v3_prompt_contains_none_of_the_check_or_calibration_titles(cfg):
    for x in INPUTS:
        assert x["postText"] not in rq.SYSTEM_PROMPT_V3
    for bad in ("Obamacare", "JurassicWorld", "WWDC", "motion sickness", "OINTB", "Lennon"):
        assert bad not in rq.SYSTEM_PROMPT_V3


def test_v3_cfg_changes_only_prompt_inputs_and_output_names(cfg):
    c3 = v3cfg(cfg)
    a, b = rq.build_body([("t1", "Some title")], cfg), rq.build_body([("t1", "Some title")], c3)
    assert a["messages"][1] == b["messages"][1] and a["messages"][0] != b["messages"][0]
    assert {k: v for k, v in a.items() if k != "messages"} == {k: v for k, v in b.items() if k != "messages"}
    assert list(c3["groq"]["paths"].values())[1:] == ["groq_results_v3.csv", "groq_log_v3.jsonl", "groq_summary_v3.json", "groq_requests_dryrun_v3.jsonl", "groq_dryrun_check_v3.json"]
    assert c3["groq"]["inputs_file"] != cfg["groq"]["inputs_file"] and cfg["groq"]["prompt_version"] == "v1"


def test_check_sample_is_new_stratified_and_seeded(tmp_path, cfg):
    from validation.webis_validation import run as runmod, synthetic
    data, res = tmp_path / "data", tmp_path / "results"
    (res / "smoke_gemini").mkdir(parents=True)
    synthetic.write_corpus(data, n=1200, seed=4)
    c = copy.deepcopy(cfg)
    c["sample"].update(size=240, strata=[dict(s, target=60) for s in cfg["sample"]["strata"]])
    c["groq"]["check_v3"]["per_stratum"] = 5
    runmod.do_sample(c, data, res)
    meta = json.loads((res / "sample_meta.json").read_text(encoding="utf-8"))
    old = [{"id": i, "postText": "x"} for i in meta["sample"]["ids"][:20]]
    (res / "smoke_gemini" / "selected_inputs.jsonl").write_text("\n".join(json.dumps(x) for x in old) + "\n", encoding="utf-8")
    m = runmod.do_groq_select_v3(c, data, res)
    assert m["n"] == 20 and m["overlap_with_old"] == [] and not set(m["ids"]) & {o["id"] for o in old}
    assert set(m["strata_counts"].values()) == {5} and len(m["strata_counts"]) == 4 and set(m["ids"]) <= set(meta["sample"]["ids"])
    rows = [json.loads(l) for l in (res / "groq" / "groq_check_inputs_v3.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(set(r) == {"id", "postText"} for r in rows)
    with pytest.raises(FileExistsError):
        runmod.do_groq_select_v3(c, data, res)                                  # a minta nem íródik felül


def test_cli_v3_commands_are_gated():
    src = (MODULE / "run.py").read_text(encoding="utf-8")
    assert '"groq-run-v3" and argv[1:] == ["--go"]' in src and "groq-select-v3" in src and "groq-dryrun-v3" in src


def test_v2_check_uses_the_v2_prompt_on_the_new_sample_with_separate_files(cfg):
    from validation.webis_validation import run as runmod
    c = runmod.groq_v2_check_cfg(cfg)
    assert rq.system_prompt(c) == rq.SYSTEM_PROMPT_V2 and c["groq"]["inputs_file"] == cfg["groq"]["check_v3"]["inputs_file"]
    assert list(c["groq"]["paths"].values())[1:3] == ["groq_results_v2_check.csv", "groq_log_v2_check.jsonl"] and c["groq"]["paths"]["summary"] == "groq_summary_v2_check.json"
    a, b = rq.build_body([("t1", "Some title")], runmod.groq_v2_cfg(cfg)), rq.build_body([("t1", "Some title")], c)
    assert a == b                                                                   # a kérés bájtra azonos a v2-vel; csak a bemenet és a kimeneti fájlok mások
