"""Gemini-adapter (HAMIS átvitellel; valódi hívás nincs) és felhasználói átiratimport."""
import json
import logging

import pytest
from fastapi.testclient import TestClient

from validation.hu_pilot.modelrun import Raw, TransportTimeout
from video_research.adapters.base import AdapterRegistry
from video_research.api import create_app
from video_research.config import SecretStr, Settings, load_settings
from video_research.db import Store, make_engine, migrate
from video_research.importer import ImportError_, import_job, parse_transcript
from video_research.llm import (LLMQuotaExhausted, LLMRejected, LLMTransient, LLMUnavailable, RetryingLLM)
from video_research.llm_gemini import GeminiLLM
from video_research.models import JobStatus, Limits, ResearchReport
from video_research.pipeline import Pipeline
from video_research.worker import Worker

KEY = "AIzaDUMMYKEYDUMMYKEYDUMMYKEY12345"       # DUMMY: hamis kulcs, soha nem megy sehová


def ok_body(obj, tokens=77):
    return json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}, "finishReason": "STOP"}],
                       "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 27, "totalTokenCount": tokens}, "modelVersion": "fake-v"})


class FakeTransport:
    def __init__(self, *raws):
        self.raws, self.calls = list(raws), []

    def __call__(self, model, body):
        self.calls.append((model, body))
        r = self.raws.pop(0) if len(self.raws) > 1 else self.raws[0]
        if isinstance(r, Exception):
            raise r
        return r


def call(llm, **kw):
    return llm.complete_json(system="S", user="U", schema_name="findings", max_tokens=123, **kw)


def test_model_name_is_required_no_hardcoded_default():
    with pytest.raises(LLMUnavailable):
        GeminiLLM("", FakeTransport(Raw(200, "{}")))
    with pytest.raises(ValueError):
        load_settings({"VR_LLM_PROVIDER": "gemini"})
    assert load_settings({"VR_LLM_PROVIDER": "gemini", "VR_GEMINI_MODEL": "any-configured-name"}).gemini_model == "any-configured-name"
    assert load_settings({}).llm_provider == "baseline"


def test_request_shape_and_neutral_result():
    t = FakeTransport(Raw(200, ok_body({"findings": []}, 91)))
    g = GeminiLLM("cfg-model", t)
    res = call(g)
    model, body = t.calls[0]
    assert model == "cfg-model" and body["systemInstruction"]["parts"][0]["text"] == "S" and body["contents"][0]["parts"][0]["text"] == "U"
    gc = body["generationConfig"]
    assert gc["responseMimeType"] == "application/json" and gc["maxOutputTokens"] == 123 and gc["temperature"] == 0.0
    assert res.data == {"findings": []} and res.tokens == 91                       # a felület nem látja a szolgáltatói borítékot
    assert g.calls == [{"provider": "gemini", "model": "cfg-model", "outcome": "ok", "tokens": 91}]


def test_every_request_logged_with_provider_model_outcome_tokens_and_no_secret(caplog):
    caplog.set_level(logging.INFO)
    g = GeminiLLM("cfg-model", FakeTransport(Raw(200, ok_body({"findings": []}, 5))))
    call(g)
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "provider=gemini" in msg and "model=cfg-model" in msg and "outcome=ok" in msg and "tokens=5" in msg
    assert KEY not in msg and KEY not in repr(g)


def test_error_classification():
    day = json.dumps({"error": {"code": 429, "message": "Quota exceeded per day", "details": [{"violations": [{"quotaId": "RequestsPerDay"}]}]}})
    minute = json.dumps({"error": {"code": 429, "message": "Quota exceeded per minute", "details": [{"retryDelay": "7s"}]}})
    cases = [(Raw(429, day), LLMQuotaExhausted), (Raw(429, minute), LLMTransient), (Raw(503, json.dumps({"error": {"message": "x"}})), LLMTransient),
             (Raw(200, json.dumps({"promptFeedback": {"blockReason": "SAFETY"}})), LLMRejected),
             (Raw(200, json.dumps({"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{"}]}}]})), LLMRejected),
             (Raw(200, json.dumps({"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "nem json"}]}}]})), LLMRejected),
             (Raw(400, json.dumps({"error": {"message": "billing account required, upgrade to paid tier"}})), LLMQuotaExhausted),
             (TransportTimeout("t"), LLMTransient), (ConnectionError("c"), LLMTransient)]
    for raw, exc in cases:
        with pytest.raises(exc):
            call(GeminiLLM("m", FakeTransport(raw)))
    r = pytest.raises(LLMTransient, lambda: call(GeminiLLM("m", FakeTransport(Raw(429, minute)))))
    assert r.value.retry_after == 7.0


def test_pacing_waits_between_requests():
    t, slept = [0.0], []
    g = GeminiLLM("m", FakeTransport(Raw(200, ok_body({"findings": []}))), min_interval_s=13.0, sleep=slept.append, clock=lambda: t[0])
    call(g)
    t[0] = 5.0
    call(g)
    assert slept == [8.0]


def test_unknown_token_count_is_estimated_and_flagged():
    body = json.dumps({"candidates": [{"content": {"parts": [{"text": "{}"}]}, "finishReason": "STOP"}]})
    g = GeminiLLM("m", FakeTransport(Raw(200, body)))
    assert call(g).tokens >= 1 and g.calls[0]["outcome"] == "ok_tokens_estimated"


def test_retrying_wrapper_backs_off_then_succeeds_and_does_not_retry_quota():
    slept = []
    flaky = FakeTransport(Raw(503, json.dumps({"error": {"message": "x"}})), Raw(200, ok_body({"findings": []})))
    r = RetryingLLM(GeminiLLM("m", flaky), max_retries=3, base=1, cap=5, sleep=slept.append)
    assert call(r).data == {"findings": []} and len(slept) == 1 and r.provider == "gemini"
    q = RetryingLLM(GeminiLLM("m", FakeTransport(Raw(429, json.dumps({"error": {"message": "per day quota"}})))), max_retries=3, base=1, cap=5, sleep=slept.append)
    with pytest.raises(LLMQuotaExhausted):
        call(q)
    assert len(slept) == 1                                                       # kvótánál nincs újrapróbálás


def test_quota_exhaustion_stops_run_keeps_finished_videos_and_never_switches_provider(tmp_path):
    e = make_engine(f"sqlite:///{tmp_path/'q.db'}")
    migrate(e)
    store, s = Store(e), Settings(limits=Limits())
    seg = "You need the AutoDroid app for this task."
    day = Raw(429, json.dumps({"error": {"message": "Quota exceeded per day", "details": [{"violations": [{"quotaId": "RequestsPerDay"}]}]}}))
    first = Raw(200, ok_body({"findings": [{"kind": "tool", "statement_hu": "Az AutoDroid alkalmazás kell hozzá.", "relevance": "direct", "concrete": True,
                                          "quotes": [{"segment_id": "x", "quote": seg}]}]}))
    t = FakeTransport(first, day)
    pipe = Pipeline(store, s, AdapterRegistry(production=False), GeminiLLM("m", t), semantic=False, sleep=lambda _x: None)
    jid, _ = import_job(store, s, question="Milyen eszközök kellenek?", transcript_text=seg, fmt="text", language="en", title="V", video_url=None)
    w = Worker(store, pipe, s, name="w")
    w.run_once()
    store.set_status(jid, JobStatus.queued, approved_plan=store.get_field(jid, "plan"))
    w.run_once()
    assert store.get_job(jid).status == JobStatus.completed and len(t.calls) == 1             # az első videó kész
    # második feladat: a napi kvóta már kimerült
    jid2, _ = import_job(store, s, question="Milyen eszközök kellenek?", transcript_text=seg + " Two.", fmt="text", language="en", title="V2", video_url=None)
    w.run_once()
    store.set_status(jid2, JobStatus.queued, approved_plan=store.get_field(jid2, "plan"))
    w.run_once()
    j2 = store.get_job(jid2)
    assert j2.status == JobStatus.failed and "kvótája kimerült" in (store.get_field(jid2, "error") or "") and len(t.calls) == 2
    assert store.get_job(jid).status == JobStatus.completed and store.get_field(jid, "report")             # a kész eredmény megmaradt


# ---- átiratimport ----
SRT = "1\n00:00:01,000 --> 00:00:04,500\nHello <i>there</i>.\n\n2\n00:00:05,000 --> 00:00:08,000\nSecond line\ncontinues.\n"
VTT = "WEBVTT\n\nNOTE komment\n\n00:01.000 --> 00:03.500 align:start\n<v Anna>First cue</v>\n\ncue2\n01:00:00.250 --> 01:00:02.000\nSecond cue\n"


def test_parse_srt_vtt_keep_real_timestamps_and_clean_markup():
    s = parse_transcript(SRT, "srt", 10_000)
    assert s == [("Hello there.", 1.0, 4.5), ("Second line continues.", 5.0, 8.0)]
    v = parse_transcript(VTT, "vtt", 10_000)
    assert v == [("First cue", 1.0, 3.5), ("Second cue", 3600.25, 3602.0)]


def test_plain_text_never_gets_timestamps_and_long_lines_are_split():
    segs = parse_transcript("Első sor.\n\nMásodik bekezdés.\n" + ("Hosszú mondat. " * 60), "text", 100_000)
    assert len(segs) > 3 and all(s is None and e is None for _, s, e in segs) and max(len(t) for t, _, _ in segs) <= 400


@pytest.mark.parametrize("text,fmt", [("", "text"), ("x", "docx"), ("nem webvtt", "vtt"), ("1\nrossz --> idő\nszöveg\n", "srt"), ("x" * 300, "text")])
def test_import_rejects_bad_input(text, fmt):
    with pytest.raises(ImportError_):
        parse_transcript(text, fmt, 200)


def store_for(tmp_path):
    e = make_engine(f"sqlite:///{tmp_path/'i.db'}")
    migrate(e)
    return Store(e), Settings(limits=Limits())


def test_import_stores_origin_null_timestamps_stable_ids_and_unverified_link(tmp_path):
    store, s = store_for(tmp_path)
    jid, created = import_job(store, s, question="Milyen eszközök kellenek?", transcript_text="Az AutoDroid kell.\nMásik sor.", fmt="text", language="hu", title="T",
                              video_url="https://www.youtube.com/watch?v=AAAAAAAAAAA")
    t = store.transcripts(jid)[0]
    v = store.videos(jid)[0]
    assert created and t.origin.value == "user_provided_transcript" and t.timestamps_available is False
    assert all(x.start_seconds is None and x.end_seconds is None for x in t.segments) and [x.id.rsplit(":", 1)[1] for x in t.segments] == ["s0", "s1"]
    assert v.transcript_link_status == "user_asserted_unverified" and v.provider == "user-import" and v.platform.value == "youtube"
    jid2, _ = import_job(store, s, question="Milyen eszközök kellenek?", transcript_text="x y z", fmt="text", language="hu", title=None, video_url=None)
    assert store.videos(jid2)[0].platform.value == "manual" and store.videos(jid2)[0].transcript_link_status == "not_applicable"


def test_import_bad_link_rejected_and_no_job_created(tmp_path):
    store, s = store_for(tmp_path)
    with pytest.raises(ImportError_):
        import_job(store, s, question="Kérdés van?", transcript_text="szöveg", fmt="text", language="hu", title=None, video_url="https://evil.example/x")


def test_imported_job_runs_end_to_end_without_platform_calls_and_report_states_the_limits(tmp_path):
    store, s = store_for(tmp_path)

    class M:
        provider, model, kind = "scripted-fake", "fake", "ai"

        def complete_json(self, *, system, user, schema_name, max_tokens):
            from video_research.llm import LLMResult
            if schema_name == "semantic":
                return LLMResult({"verdict": "consistent"}, 1)
            sid = user.split("<untrusted_transcript>")[1].strip().splitlines()[0][1:].split("]")[0]
            return LLMResult({"findings": [{"kind": "tool", "statement_hu": "Az AutoDroid alkalmazás szükséges.", "relevance": "direct", "concrete": True,
                                            "quotes": [{"segment_id": sid, "quote": "You need the AutoDroid app."}]}]}, 9)
    pipe = Pipeline(store, s, AdapterRegistry(production=False), M(), sleep=lambda _x: None)       # üres adaptertár: platformhívás nem lehetséges
    jid, _ = import_job(store, s, question="Milyen eszközök kellenek?", transcript_text=SRT.replace("Hello <i>there</i>.", "You need the AutoDroid app."), fmt="srt", language="en",
                        title="T", video_url="https://www.youtube.com/watch?v=AAAAAAAAAAA")
    w = Worker(store, pipe, s, name="w")
    w.run_once()
    plan = json.loads(store.get_field(jid, "plan"))
    assert plan["imported_sources"] == 1 and plan["search_queries"] == [] and plan["estimated_cost_usd"] == 0
    store.set_status(jid, JobStatus.queued, approved_plan=store.get_field(jid, "plan"))
    w.run_once()
    r = ResearchReport.model_validate_json(store.get_field(jid, "report"))
    assert store.get_job(jid).status == JobStatus.completed and r.findings[0].source_references[0].timestamp == 1.0
    assert any("nem ellenőrizte" in l and "nem bizonyít platformintegrációt" in l for l in r.coverage_limitations)
    assert r.source_list[0]["transcript_origin"] == "user_provided_transcript" and r.source_list[0]["transcript_link_status"] == "user_asserted_unverified"
    assert r.analysis_method == "ai_semantic" and r.analysis_model == {"provider": "scripted-fake", "model": "fake"}


def test_import_api_endpoint(tmp_path):
    store, s = store_for(tmp_path)
    s.api_token = SecretStr("t" * 20)
    c = TestClient(create_app(store, s, AdapterRegistry(production=False)))
    H = {"Authorization": "Bearer " + "t" * 20}
    body = {"question": "Milyen eszközök kellenek?", "transcript_text": SRT, "format": "srt", "language": "en"}
    assert c.post("/api/jobs/import", json=body).status_code == 401
    r = c.post("/api/jobs/import", json=body, headers={**H, "Idempotency-Key": "abcdef123456"})
    assert r.status_code == 202 and "nem ellenőrzi" in r.json()["note"]
    again = c.post("/api/jobs/import", json=body, headers={**H, "Idempotency-Key": "abcdef123456"})
    assert again.status_code == 200 and again.json()["job_id"] == r.json()["job_id"]
    assert c.post("/api/jobs/import", json={**body, "format": "docx"}, headers=H).status_code == 422
    assert c.post("/api/jobs/import", json={**body, "video_url": "http://127.0.0.1/x"}, headers=H).status_code == 422
