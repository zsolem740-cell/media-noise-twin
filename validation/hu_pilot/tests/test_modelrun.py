"""A pilot modellfuttatója hamis átvitellel: közös prompt/séma, lezárási kapu, kvótaleállás és folytatás, naplózás. Hálózat, kulcs és modell nélkül."""
import ast
import copy
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from validation.hu_pilot import modelrun as mr
from validation.hu_pilot import prompt as P
from validation.hu_pilot import providers as V
from validation.hu_pilot import quota as Q
from validation.hu_pilot import run
from validation.hu_pilot.freeze import NotFrozen
from validation.hu_pilot.paths import REPO_ROOT
from .test_hu_pilot import full_flow

MOD = Path(mr.__file__).resolve().parent
UTC = timezone.utc
T0 = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)          # november: PST (UTC-8)
CANARY = "AIzaSyFAKEFAKEFAKEFAKEFAKE12345"
GEM, GRQ = "gemini-3.5-flash-lite", "openai/gpt-oss-120b"


@pytest.fixture
def frozen(tmp_path, cfg, feed_path):
    res, sel, exp = full_flow(tmp_path, cfg, feed_path)
    run.do_analyze(cfg, [exp], base=res)
    run.do_freeze(cfg, [exp], base=res)
    return res, mr.load_titles(res, cfg)


class Clock:
    def __init__(self, t=T0):
        self.t, self.mono, self.sleeps = t, 1000.0, []

    def now(self):
        return self.t

    def monotonic(self):
        return self.mono

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += timedelta(seconds=s)
        self.mono += s


def post_of(body):
    t = body["contents"][0]["parts"][0]["text"] if "contents" in body else body["messages"][1]["content"]
    return t.removeprefix("<post>\n").removesuffix("\n</post>")


def sig(post, scores=(1, 0, 0, 0)):
    first = post.split()[0]
    return {n: {"span": first if s else "", "reason": "röviden", "score": s} for n, s in zip(P.SIGNALS, scores)}


def ok_raw(provider, body, scores=(1, 0, 0, 0), usage=(100, 50, 0)):
    obj = json.dumps(sig(post_of(body), scores), ensure_ascii=False)
    if provider == "gemini":
        d = {"candidates": [{"content": {"parts": [{"text": obj}]}, "finishReason": "STOP"}], "modelVersion": GEM,
             "usageMetadata": {"promptTokenCount": usage[0], "candidatesTokenCount": usage[1], "thoughtsTokenCount": usage[2], "totalTokenCount": sum(usage)}}
    else:
        d = {"model": GRQ, "choices": [{"finish_reason": "stop", "message": {"content": obj}}],
             "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1], "total_tokens": sum(usage)}}
    return mr.Raw(200, json.dumps(d), None, 120)


def err(status, message="x", details=None, code="", retry=None):
    return mr.Raw(status, json.dumps({"error": {"code": code or status, "message": message, "details": details or []}}), retry, 40)


DAY_DET = [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]


def quota_day(provider="gemini"):
    return err(429, "Rate limit reached for model on tokens per day (TPD). " + CANARY, DAY_DET if provider == "gemini" else None)


class Script:
    def __init__(self, provider, steps=()):
        self.provider, self.steps, self.calls = provider, list(steps), []

    def __call__(self, model, body):
        self.calls.append((model, body))
        if self.steps:
            x = self.steps.pop(0)
            if isinstance(x, Exception):
                raise x
            return x(body) if callable(x) else x
        return ok_raw(self.provider, body)


def go(frozen, cfg, tr, provider="gemini", clock=None, name="r1"):
    res, titles = frozen
    clock = clock or Clock()
    model = GEM if provider == "gemini" else GRQ
    return mr.run_measurement(titles, provider, tr, cfg, res, name, model, now=clock.now, sleep=clock.sleep, monotonic=clock.monotonic), res / "model_runs" / name, clock


def jl(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]


# ---------------------------------------------------------------- közös prompt és séma

def test_prompt_and_schema_are_the_existing_gemini_ones():
    import hashlib
    h = lambda t: hashlib.sha256(t.encode()).hexdigest()
    assert h(P.SYSTEM_INSTRUCTION) == "c634bdcc62aa9c2e47f5e886c4d076d7676ab4f8631fb215dc90846f1f5da20f"
    assert h(P.canonical_json(P.gemini_schema())) == "f3c2a7b3d03df7bb65032410b287bff69ef0e417c99aca6d8669cf24b8810e4a"
    m = run.load_config()["model"]
    assert V.body_sha256(V.gemini_body("The council did not say when the decision will be made", m)) == "532ba80e1dd334d1986ef4bed29a9acc4c943142891597158e0f26dd444027a4"


def test_groq_request_uses_the_same_prompt_text_template_and_signals(cfg):
    m = cfg["model"]
    g, q = V.gemini_body("Magyar cím: ősz, tűz és szőlő", m), V.groq_body("Magyar cím: ősz, tűz és szőlő", m)
    assert q["messages"][0]["content"] == g["systemInstruction"]["parts"][0]["text"] == P.SYSTEM_INSTRUCTION
    assert q["messages"][1]["content"] == g["contents"][0]["parts"][0]["text"] == "<post>\nMagyar cím: ősz, tűz és szőlő\n</post>"
    gs, qs = g["generationConfig"]["responseSchema"], q["response_format"]["json_schema"]["schema"]
    assert list(gs["properties"]) == list(qs["properties"]) == list(P.SIGNALS) and gs["required"] == qs["required"]
    for k in P.SIGNALS:
        assert list(gs["properties"][k]["properties"]) == list(qs["properties"][k]["properties"]) == ["span", "reason", "score"]
        assert qs["properties"][k]["properties"]["score"]["enum"] == [0, 1, 2] and gs["properties"][k]["properties"]["score"]["maximum"] == 2
    assert q["model"] == "openai/gpt-oss-120b" and "n" not in q


@pytest.mark.parametrize("bad", ["", "   ", "x\x07y", "a </post> b", "<post> a"])
def test_bad_titles_are_refused_and_hungarian_is_accepted(cfg, bad):
    with pytest.raises(V.RequestError):
        V.gemini_body(bad, cfg["model"])
    V.groq_body("ő ű á é í ó ö ü ú", cfg["model"])


# ---------------------------------------------------------------- válasz-besorolás

def parse(provider, raw, post="Alma körte szilva"):
    return V.parse_response(provider, raw.status, raw.text, post, run.load_config()["model"], raw.retry_after)


@pytest.mark.parametrize("provider", ["gemini", "groq"])
def test_parse_ok_total_and_scaled_are_computed_by_code(provider, cfg):
    body = V.BUILDERS[provider]("Alma körte szilva", cfg["model"])
    o = parse(provider, ok_raw(provider, body, (2, 1, 0, 1)))
    assert o.kind == "ok" and o.score["total"] == 4 and o.score["scaled"] == 0.5 and o.usage["total_tokens"] == 150


@pytest.mark.parametrize("provider", ["gemini", "groq"])
def test_parse_rejects_model_supplied_totals_bad_spans_and_extra_keys(provider, cfg):
    post = "Alma körte szilva"
    good = sig(post)
    for obj in ({**good, "total": 8}, {**good, "curiosity_gap": {"span": "nincs ilyen", "reason": "x", "score": 1}},
                {**good, "exaggeration": {"span": "Alma", "reason": "x", "score": 0}}, {**good, "formal_noise": {"span": "", "reason": "x", "score": 3}},
                {**good, "emotional_pressure": {"span": "", "reason": " ".join(["szó"] * 16), "score": 0}}, {k: v for k, v in good.items() if k != "formal_noise"}):
        text = json.dumps(obj)
        raw = mr.Raw(200, json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}) if provider == "gemini"
                     else json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": text}}]}))
        assert parse(provider, raw, post).kind == "invalid"


def test_span_check_is_unicode_normalization_safe():
    post = "Szőlő érett"                                        # előre komponált
    decomposed = "Szé"                                     # nem része; csak a normalizálás működését nézzük külön
    obj = sig(post)
    obj["curiosity_gap"]["span"] = "Szőlő"          # szétbontott ő (o + kettős ékezet): NFC-ben megfelel
    o = V.validate_signals(obj, post, run.load_config()["model"])
    assert o[1] is None or "span" in o[1]


@pytest.mark.parametrize("provider,raw,kind", [
    ("gemini", mr.Raw(200, json.dumps({"candidates": []})), "empty"),
    ("gemini", mr.Raw(200, json.dumps({"candidates": [{"content": {"parts": [{"text": ""}]}, "finishReason": "STOP"}]})), "empty"),
    ("gemini", mr.Raw(200, json.dumps({"candidates": [{"content": {"parts": [{"text": "{nem json"}]}, "finishReason": "STOP"}]})), "invalid"),
    ("gemini", mr.Raw(200, json.dumps({"candidates": [{"finishReason": "MAX_TOKENS"}]})), "truncated"),
    ("gemini", mr.Raw(200, json.dumps({"promptFeedback": {"blockReason": "SAFETY"}})), "blocked"),
    ("groq", mr.Raw(200, json.dumps({"choices": []})), "empty"),
    ("groq", mr.Raw(200, json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": None}}]})), "empty"),
    ("groq", mr.Raw(200, json.dumps({"choices": [{"finish_reason": "length", "message": {"content": "{"}}]})), "truncated"),
    ("groq", err(400, "bad", code="json_validate_failed"), "invalid"),
    ("gemini", err(503, "overloaded"), "transient"), ("groq", err(502), "transient"),
    ("gemini", err(401, "API key not valid"), "fatal"), ("groq", err(404, "no model"), "fatal"),
    ("gemini", err(400, "Please enable billing for this project"), "billing"), ("groq", err(403, "upgrade your plan"), "billing"),
    ("gemini", err(429, "Quota exceeded for metric per minute"), "quota_minute"), ("gemini", err(429, "x", DAY_DET), "quota_day"),
    ("groq", err(429, "Rate limit reached on tokens per minute (TPM). Please try again in 7.5s."), "quota_minute"),
    ("groq", err(429, "Rate limit reached on tokens per day (TPD). Please try again in 3h2m."), "quota_day"),
])
def test_parse_classification(provider, raw, kind):
    assert parse(provider, raw).kind == kind


def test_a_quota_message_mentioning_billing_is_still_a_quota_error_not_a_billing_stop():
    o = parse("gemini", err(429, "You exceeded your current quota, please check your plan and billing details.", DAY_DET))
    assert o.kind == "quota_day"
    assert parse("gemini", err(429, "check your plan and billing details")).kind == "quota_minute"


def test_retry_hints_are_read():
    assert parse("groq", err(429, "tokens per minute (TPM). Please try again in 7.5s.")).retry_after == 7.5
    assert parse("groq", err(429, "tokens per day (TPD) try again in 3h2m")).retry_after == pytest.approx(3 * 3600 + 120)
    assert parse("gemini", err(429, "x", [{"retryDelay": "12s"}])).retry_after == 12.0
    assert parse("groq", err(429, "per minute", retry="9")).retry_after == 9.0


def test_secrets_are_redacted():
    for s in (CANARY, "gsk_abcdefghijklmnop12", "Bearer abc.def", "x-goog-api-key: foo", "?key=abc123"):
        assert "[REDACTED]" in V.sanitize("hiba " + s) and s.split()[-1] not in V.sanitize("hiba " + s)


# ---------------------------------------------------------------- visszaállási idők

def test_next_reset_times_are_zone_aware():
    cfg = run.load_config()["model"]["providers"]
    g, q = cfg["gemini"], cfg["groq"]
    assert Q.next_reset_utc(g, datetime(2026, 11, 14, 10, 0, tzinfo=UTC)) == datetime(2026, 11, 15, 8, 0, tzinfo=UTC)       # PST
    assert Q.next_reset_utc(g, datetime(2026, 7, 14, 10, 0, tzinfo=UTC)) == datetime(2026, 7, 15, 7, 0, tzinfo=UTC)         # PDT
    assert Q.next_reset_utc(q, datetime(2026, 11, 14, 10, 0, tzinfo=UTC)) == datetime(2026, 11, 15, 0, 0, tzinfo=UTC)
    assert Q.next_reset_utc(q, datetime(2026, 7, 14, 23, 59, tzinfo=UTC)) == datetime(2026, 7, 15, 0, 0, tzinfo=UTC)
    assert Q.next_reset_utc(g, datetime(2026, 11, 15, 7, 59, tzinfo=UTC)) == datetime(2026, 11, 15, 8, 0, tzinfo=UTC)      # a visszaállás előtt egy perccel
    assert Q.next_reset_utc(g, datetime(2026, 11, 15, 8, 0, tzinfo=UTC)) == datetime(2026, 11, 16, 8, 0, tzinfo=UTC)       # pontosan a visszaálláskor már a következő
    assert Q.next_reset_utc(g, datetime(2027, 3, 14, 12, 0, tzinfo=UTC)) == datetime(2027, 3, 15, 7, 0, tzinfo=UTC)        # a váltás napja után PDT
    assert Q.resume_after_utc(g, T0, 5) == datetime(2026, 11, 15, 8, 5, tzinfo=UTC) and Q.quota_day_key(g, T0) == "2026-11-14"


# ---------------------------------------------------------------- kapuk

def test_the_gate_failover_flag_and_title_list(frozen, cfg, tmp_path):
    res, titles = frozen
    clock = Clock()
    s = Script("gemini")
    with pytest.raises(NotFrozen):
        mr.run_measurement(titles, "gemini", s, cfg, tmp_path / "masik", "r", GEM, now=clock.now, sleep=clock.sleep, monotonic=clock.monotonic)
    bad = copy.deepcopy(cfg)
    bad["model"]["failover"]["enabled"] = True
    with pytest.raises(mr.RunRefused):
        mr.run_measurement(titles, "gemini", s, bad, res, "r", GEM)
    bad = copy.deepcopy(cfg)
    bad["model"]["failover"]["measurement_allowed"] = True
    with pytest.raises(mr.RunRefused):
        mr.run_measurement(titles, "gemini", s, bad, res, "r", GEM)
    with pytest.raises(mr.RunRefused):
        mr.run_measurement(titles[:-1], "gemini", s, cfg, res, "r", GEM)
    with pytest.raises(mr.RunRefused):
        mr.run_measurement(titles, "masik", s, cfg, res, "r", GEM)
    assert s.calls == []                                                            # egyik elutasított indítás sem küldött kérést


def test_freeze_is_checked_again_when_files_change(frozen, cfg):
    res, titles = frozen
    (res / "human_reference.csv").write_text("x", encoding="utf-8")
    with pytest.raises(NotFrozen):
        mr.run_measurement(titles, "gemini", Script("gemini"), cfg, res, "r", GEM)


# ---------------------------------------------------------------- normál futás és naplózás

@pytest.mark.parametrize("provider", ["gemini", "groq"])
def test_full_run_logs_the_provider_on_every_line_and_never_a_key(frozen, cfg, provider):
    s = Script(provider)
    rep, d, clock = go(frozen, cfg, s, provider)
    assert rep["status"] == "complete" and rep["n_ok"] == 50 and rep["requests_total"] == 50 and len(s.calls) == 50 and rep["failover_allowed"] is False
    log = jl(d / "log.jsonl")
    assert len(log) == 50 and all(l["provider"] == provider and l["workload"] == "measurement" and l["key_alias"].endswith("_API_KEY") for l in log)
    assert all(l["outcome"] == "ok" and l["model_returned"] in (GEM, GRQ) for l in log)
    rows = list(csv.DictReader((d / "results.csv").open(encoding="utf-8", newline="")))
    assert len(rows) == 50 and {r["provider"] for r in rows} == {provider} and all(r["status"] == "ok" and float(r["scaled"]) == 0.125 for r in rows)
    assert rep["providers_used"] == [provider] and rep["tokens"]["total_tokens"] == 50 * 150
    blob = "".join(p.read_text(encoding="utf-8") for p in d.iterdir())
    assert CANARY not in blob and "Bearer" not in blob and "gsk_" not in blob
    assert rows[0]["provider"] and list(rows[0]) == mr.CSV_FIELDS


def test_pacing_follows_the_provider_interval(frozen, cfg):
    rep, d, clock = go(frozen, cfg, Script("gemini"))
    assert clock.sleeps == [13.0] * 49


# ---------------------------------------------------------------- hibák, amelyek nem állítanak le és nem váltanak

def test_invalid_json_gets_one_retry_on_the_same_provider_then_fails(frozen, cfg):
    bad = lambda b: mr.Raw(200, json.dumps({"candidates": [{"content": {"parts": [{"text": "{nem json"}]}, "finishReason": "STOP"}]}))
    s = Script("gemini", [bad, bad])
    rep, d, _ = go(frozen, cfg, s)
    assert rep["n_failed"] == 1 and rep["n_ok"] == 49 and len(s.calls) == 51 and rep["outcomes"]["invalid"] == 2
    rows = list(csv.DictReader((d / "results.csv").open(encoding="utf-8", newline="")))
    assert [r["status"] for r in rows].count("invalid") == 1 and rep["status"] == "complete"
    assert {c[0] for c in s.calls} == {GEM}


def test_empty_then_ok_is_accepted_on_retry(frozen, cfg):
    empty = mr.Raw(200, json.dumps({"candidates": []}))
    rep, d, _ = go(frozen, cfg, Script("gemini", [empty]))
    assert rep["n_ok"] == 50 and rep["requests_total"] == 51


def test_truncated_and_blocked_are_not_retried(frozen, cfg):
    cut = mr.Raw(200, json.dumps({"candidates": [{"finishReason": "MAX_TOKENS"}]}))
    blk = mr.Raw(200, json.dumps({"promptFeedback": {"blockReason": "SAFETY"}}))
    s = Script("gemini", [cut, blk])
    rep, d, _ = go(frozen, cfg, s)
    assert len(s.calls) == 50 and rep["n_failed"] == 2 and rep["outcomes"]["truncated"] == 1 and rep["outcomes"]["blocked"] == 1


def test_per_minute_429_waits_and_retries_but_does_not_stop(frozen, cfg):
    s = Script("gemini", [err(429, "per minute", retry="20")])
    rep, d, clock = go(frozen, cfg, s)
    assert rep["status"] == "complete" and rep["n_ok"] == 50 and 20.0 in clock.sleeps and rep["requests_total"] == 51
    assert not (d / "quota_stops.jsonl").exists()


def test_a_very_long_per_minute_wait_stops_the_run(frozen, cfg):
    rep, d, clock = go(frozen, cfg, Script("gemini", [err(429, "per minute", retry="500")]))
    assert rep["status"] == "stopped_long_wait" and rep["n_ok"] == 0 and rep["resume_after_utc"] == Q.iso(T0 + timedelta(seconds=500, minutes=5))


def test_timeout_is_retried_then_ok(frozen, cfg):
    rep, d, clock = go(frozen, cfg, Script("groq", [mr.TransportTimeout(), mr.TransportTimeout()]), "groq")
    assert rep["n_ok"] == 50 and rep["requests_total"] == 52 and 2 in clock.sleeps and 8 in clock.sleeps


def test_a_title_with_exhausted_transient_retries_is_requeued_once_and_stays_pending_if_it_still_fails(frozen, cfg):
    res, titles = frozen
    first = titles[0]["title"]

    def flaky(model, body):
        return err(503) if post_of(body) == first else ok_raw("gemini", body)
    s = Script("gemini")
    s.__class__ = type("S", (Script,), {"__call__": lambda self, model, body: (self.calls.append((model, body)), flaky(model, body))[1]})
    rep, d, _ = go(frozen, cfg, s)
    assert rep["n_ok"] == 49 and rep["status"] == "incomplete" and len(s.calls) == 49 + 3 + 3
    rows = list(csv.DictReader((d / "results.csv").open(encoding="utf-8", newline="")))
    assert [r["status"] for r in rows].count("transient_failed") == 1
    # a következő folytatás újra próbálja (nem végleges hiba), és csak ezt az egy címet küldi
    s2 = Script("gemini")
    rep2, d2, _ = go(frozen, cfg, s2, clock=Clock(T0 + timedelta(minutes=1)))
    assert rep2["status"] == "complete" and rep2["n_ok"] == 50 and len(s2.calls) == 1 and post_of(s2.calls[0][1]) == first


def test_three_consecutive_final_failures_pause_then_outage_stop(frozen, cfg):
    c = copy.deepcopy(cfg)
    s = Script("gemini", [err(503)] * 60)
    rep, d, clock = go(frozen, c, s)
    assert rep["status"] == "stopped_outage" and 600 in clock.sleeps and rep["n_ok"] == 0


def test_fatal_and_billing_stop_the_run_without_switching(frozen, cfg):
    s = Script("gemini", [err(401, "API key not valid")])
    rep, d, _ = go(frozen, cfg, s)
    assert rep["status"] == "stopped_fatal" and len(s.calls) == 1 and rep["n_pending"] == 50
    s = Script("groq", [err(402, "payment required: upgrade to the paid tier")])
    rep, d, _ = go(frozen, cfg, s, "groq", name="r2")
    assert rep["status"] == "stopped_billing" and len(s.calls) == 1


def test_request_cap_stops_the_run(frozen, cfg):
    c = copy.deepcopy(cfg)
    c["model"]["run"]["max_requests"] = 5
    s = Script("gemini")
    rep, d, _ = go(frozen, c, s)
    assert rep["status"] == "stopped_request_cap" and len(s.calls) == 5 and rep["n_ok"] == 5


# ---------------------------------------------------------------- napi kvóta: megállás, folytatás, próbák

@pytest.mark.parametrize("provider,resume", [("gemini", "2026-11-15T08:05:00Z"), ("groq", "2026-11-15T00:05:00Z")])
def test_daily_quota_stops_keeps_done_titles_and_sets_the_resume_time(frozen, cfg, provider, resume):
    s = Script(provider, [None] * 0)
    s.steps = [lambda b, p=provider: ok_raw(p, b)] * 7 + [quota_day(provider)]
    rep, d, _ = go(frozen, cfg, s, provider)
    assert rep["status"] == "stopped_quota" and rep["n_ok"] == 7 and rep["n_pending"] == 43 and rep["n_failed"] == 0 and len(s.calls) == 8
    assert rep["resume_after_utc"] == resume
    qs = jl(d / "quota_stops.jsonl")
    assert len(qs) == 1 and qs[0]["provider"] == provider and qs[0]["failover"].startswith("nincs") and qs[0]["done"] == 7 and qs[0]["pending"] == 43 and CANARY not in json.dumps(qs)
    assert len(jl(d / "scores.jsonl")) == 7
    rows = list(csv.DictReader((d / "results.csv").open(encoding="utf-8", newline="")))
    assert [r["status"] for r in rows].count("ok") == 7 and [r["status"] for r in rows].count("pending") == 43


def stopped_run(frozen, cfg, provider="gemini", done=7):
    s = Script(provider)
    s.steps = [lambda b, p=provider: ok_raw(p, b)] * done + [quota_day(provider)]
    go(frozen, cfg, s, provider)
    return s


def test_resume_is_refused_before_the_resume_time_and_never_resends_done_titles(frozen, cfg):
    first = stopped_run(frozen, cfg)
    done_ids = {post_of(b) for _, b in first.calls[:7]}
    s = Script("gemini")
    with pytest.raises(mr.RunRefused, match="még nem jött el"):
        go(frozen, cfg, s, clock=Clock(datetime(2026, 11, 15, 8, 4, 59, tzinfo=UTC)))
    assert s.calls == []
    rep, d, _ = go(frozen, cfg, s, clock=Clock(datetime(2026, 11, 15, 8, 5, tzinfo=UTC)))
    assert rep["status"] == "complete" and rep["n_ok"] == 50 and len(s.calls) == 43
    assert not done_ids & {post_of(b) for _, b in s.calls}                          # a kész címek nem mennek ki újra
    assert len(rep["probes"]) == 1 and rep["probes"][0]["quota_day"] == "2026-11-15"
    assert [l["probe"] for l in jl(d / "log.jsonl")][-43:].count(True) == 1 and jl(d / "log.jsonl")[-43]["probe"] is True


def test_a_failed_probe_stops_again_and_at_most_three_probes_per_quota_day(frozen, cfg):
    stopped_run(frozen, cfg)
    t = datetime(2026, 11, 15, 8, 6, tzinfo=UTC)
    seen = []
    for k in range(3):
        s = Script("gemini", [quota_day()])
        rep, d, _ = go(frozen, cfg, s, clock=Clock(t))
        seen.append(rep["resume_after_utc"])
        assert rep["status"] == "stopped_quota" and len(s.calls) == 1 and len(rep["probes"]) == k + 1
        t = datetime.fromisoformat(rep["resume_after_utc"].replace("Z", "+00:00"))
    assert seen[0] == "2026-11-15T09:11:00Z"                                          # próba + 60 perc + 5 perc, a következő visszaállásnál nem később
    with pytest.raises(mr.RunRefused, match="elfogyott"):
        go(frozen, cfg, Script("gemini"), clock=Clock(t + timedelta(minutes=1)))
    # a következő kvótanapon újra szabad próbálni
    rep, d, _ = go(frozen, cfg, Script("gemini"), clock=Clock(datetime(2026, 11, 16, 8, 6, tzinfo=UTC)))
    assert rep["status"] == "complete"


def test_the_failed_probe_wait_uses_the_provider_hint_but_never_passes_the_next_reset(frozen, cfg):
    stopped_run(frozen, cfg, "groq")
    t = datetime(2026, 11, 15, 0, 6, tzinfo=UTC)
    rep, d, _ = go(frozen, cfg, Script("groq", [err(429, "tokens per day (TPD). Please try again in 90h")]), "groq", clock=Clock(t))
    assert rep["resume_after_utc"] == "2026-11-16T00:05:00Z"


def test_resume_refuses_a_different_provider_model_or_title_list(frozen, cfg):
    stopped_run(frozen, cfg)
    res, titles = frozen
    clock = Clock(datetime(2026, 11, 15, 9, 0, tzinfo=UTC))
    with pytest.raises(mr.RunRefused):
        mr.run_measurement(titles, "groq", Script("groq"), cfg, res, "r1", GRQ, now=clock.now, sleep=clock.sleep, monotonic=clock.monotonic)
    with pytest.raises(mr.RunRefused):
        mr.run_measurement(titles, "gemini", Script("gemini"), cfg, res, "r1", "gemini-3.1-flash-lite", now=clock.now, sleep=clock.sleep, monotonic=clock.monotonic)
    with pytest.raises(mr.RunRefused):
        mr.run_measurement(list(reversed(titles)), "gemini", Script("gemini"), cfg, res, "r1", GEM, now=clock.now, sleep=clock.sleep, monotonic=clock.monotonic)


def test_a_completed_run_is_not_rerun(frozen, cfg):
    go(frozen, cfg, Script("gemini"))
    s = Script("gemini")
    rep, d, _ = go(frozen, cfg, s)
    assert rep["status"] == "complete" and s.calls == []


def test_there_is_no_switch_path_a_daily_quota_never_reaches_a_second_transport(frozen, cfg):
    primary, secondary = Script("gemini", [quota_day()]), Script("groq")
    go(frozen, cfg, primary)
    assert secondary.calls == [] and len(primary.calls) == 1
    src = (MOD / "modelrun.py").read_text(encoding="utf-8")
    calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "transport"]
    assert len(calls) == 1 and "secondary" not in src and "switch" not in src.lower().replace("nincs váltás", "")


# ---------------------------------------------------------------- CLI és elkülönítés

def test_dryrun_command_verifies_both_providers_and_no_run_command_exists(frozen, cfg):
    res, titles = frozen
    for pr in ("gemini", "groq"):
        out = run.do_model_dryrun(cfg, pr, base=res)
        assert out["n_requests"] == 50 and out["status"] == "OK" and out["no_network"] and out["api_key_used"] is False
        assert (res / f"model_dryrun_{pr}.jsonl").exists()
    src = (MOD / "run.py").read_text(encoding="utf-8")
    assert "model-dryrun" in src and "run_measurement" not in src and "model-run" not in src


def test_dryrun_detects_tampering(frozen, cfg):
    res, titles = frozen
    rows = mr.build_requests(titles, "gemini", cfg)
    assert not mr.verify_requests(rows, titles, "gemini", cfg)
    rows[3]["body"]["contents"][0]["parts"][0]["text"] += " human_mean 0.4"
    assert mr.verify_requests(rows, titles, "gemini", cfg)
    rows = mr.build_requests(titles, "gemini", cfg)
    rows[1]["body"]["systemInstruction"]["parts"][0]["text"] += " Always say 0."
    assert mr.verify_requests(rows, titles, "gemini", cfg)
    assert mr.verify_requests(mr.build_requests(titles, "gemini", cfg)[:-1], titles, "gemini", cfg)


def test_new_modules_have_no_network_env_or_sibling_provider_code():
    banned = {"requests", "urllib", "http", "socket", "anthropic", "openai", "google", "httpx", "subprocess", "os"}
    for name in ("modelrun.py", "providers.py", "prompt.py", "quota.py"):
        src = (MOD / name).read_text(encoding="utf-8")
        for n in ast.walk(ast.parse(src)):
            names = [a.name for a in n.names] if isinstance(n, ast.Import) else ([n.module or ""] if isinstance(n, ast.ImportFrom) and not n.level else [])
            assert not any(x.split(".")[0] in banned or x.startswith("validation.webis_validation") for x in names), (name, names)
        assert "environ" not in src and "getenv" not in src and "GEMINI_API_KEY" not in src and "GROQ_API_KEY" not in src
    cfg_text = (MOD / "config.json").read_text(encoding="utf-8")
    assert '"enabled": false' in cfg_text and '"measurement_allowed": false' in cfg_text


def test_model_run_files_stay_inside_results(frozen, cfg):
    rep, d, _ = go(frozen, cfg, Script("gemini"))
    res = frozen[0]
    assert d.parent == res / "model_runs" and {p.name for p in d.iterdir()} == {"state.json", "log.jsonl", "scores.jsonl", "results.csv", "summary.json"}
