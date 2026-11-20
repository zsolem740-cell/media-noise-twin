import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from video_research.adapters.apify import ApifyAdapter, render_input
from video_research.adapters.base import (AdapterRegistry, Capability, ProviderNotConfigured, ProviderPermanentError)
from video_research.adapters.fixture import FixtureAdapter
from video_research.api import create_app
from video_research.config import ActorConfig, SecretStr, Settings
from video_research.db import Store, make_engine, migrate
from video_research.executor import CostBudgetExhausted, Executor, JobStopped, UncertainRun
from video_research.llm import NullLLM
from video_research.models import AccessStatus, EvidenceStatus, JobStatus, Limits, Platform
from video_research.pipeline import Pipeline
from video_research.util import RetryableError, UncertainOutcome
from video_research.worker import Worker

from .helpers import CountingAdapter, ScriptedLLM

FIX = Path(__file__).parent / "fixtures" / "videos.json"
Q = "Keress YouTube-on és TikTokon Androidos AI-ügynökökről. Gyűjtsd ki az eszközöket és a problémákat."


def make(tmp_path, *, llm=None, adapter=None, limits=None, mode="dev", semantic=True):
    e = make_engine(f"sqlite:///{tmp_path/'f.db'}")
    migrate(e)
    store = Store(e)
    s = Settings(mode=mode, limits=limits or Limits(), lease_seconds=60)
    reg = AdapterRegistry(production=False)
    inner = FixtureAdapter.from_file(FIX)
    ad = adapter or CountingAdapter(inner)
    reg.register(ad)
    llm = llm or ScriptedLLM()
    pipe = Pipeline(store, s, reg, llm, sleep=lambda _x: None, poll_interval=0, semantic=semantic)
    return store, s, pipe, ad, llm


def run_to_end(store, pipe, s, q=Q, approve=True):
    job, _ = store.create_job(q, [], ["hu", "en"], s.limits)
    w = Worker(store, pipe, s, name="w1")
    assert w.run_once() == job.id                                    # tervezés
    assert store.get_job(job.id).status == JobStatus.awaiting_approval
    if approve:
        store.set_status(job.id, JobStatus.queued, approved_plan=store.get_field(job.id, "plan"))
        assert w.run_once() == job.id
    return job.id


def test_end_to_end_sourced_report(tmp_path):
    store, s, pipe, ad, llm = make(tmp_path)
    jid = run_to_end(store, pipe, s)
    job = store.get_job(jid)
    assert job.status == JobStatus.partially_completed                  # a TikTok-fixture átirat nélküli
    from video_research.models import ResearchReport
    r = ResearchReport.model_validate_json(store.get_field(jid, "report"))
    assert r.findings and all(f.source_references for f in r.findings)  # minden megállapításnak van forrása
    assert not any(f.statement_hu == "Kitalált állítás" for f in r.findings)  # kitalált idézet: kiszűrve
    assert any("unsupported" in l for l in r.coverage_limitations)
    auto = [f for f in r.findings if "AutoDroid" in f.statement_hu]
    assert len(auto) == 1 and auto[0].evidence_status == EvidenceStatus.repeated_across_sources
    assert len({x.video_source_id for x in auto[0].source_references}) == 2        # mindkét videó forrása megmaradt
    assert {e.value for e in EvidenceStatus} == {"source_claim", "repeated_across_sources", "unsupported"}                 # nincs verified érték
    assert all(f.evidence_status != EvidenceStatus.unsupported for f in r.findings)
    assert any("Nincs hozzáférhető átirat" in m for m in r.missing_information)
    assert any("FIXTURE" in l for l in r.coverage_limitations)
    assert all(ref.timestamp is not None for f in r.findings for ref in f.source_references)
    assert job.recorded_cost > 0 and store.get_field(jid, "llm_tokens_used") > 0


def test_plan_requires_approval_and_nothing_paid_before(tmp_path):
    store, s, pipe, ad, _ = make(tmp_path)
    jid = run_to_end(store, pipe, s, approve=False)
    assert ad.starts == [] and store.get_job(jid).status == JobStatus.awaiting_approval
    plan = json.loads(store.get_field(jid, "plan"))
    assert plan["limits"]["max_videos"] <= 10 and set(plan["platforms"]) == {"youtube", "tiktok"}
    assert all(not q.startswith("http") for q in plan["search_queries"])          # az LLM nem csempészhet be URL-t


def test_resume_after_crash_does_not_repeat_paid_steps(tmp_path):
    store, s, pipe, ad, llm = make(tmp_path, llm=ScriptedLLM(fail_after=4))
    jid, _ = store.create_job(Q, [], ["hu", "en"], s.limits)
    w = Worker(store, pipe, s, name="w1")
    w.run_once()
    store.set_status(jid.id, JobStatus.queued, approved_plan=store.get_field(jid.id, "plan"))
    w.run_once()
    assert store.get_job(jid.id).status in (JobStatus.failed,)                     # LLM-összeomlás: a worker hibaként rögzíti
    done_before = len(ad.starts)
    # újraindítás: új, működő LLM; a feladat visszaállítása futhatóra (mint egy lejárt lease-es feladat)
    with store.e.begin() as c:
        from sqlalchemy import text
        c.execute(text("UPDATE research_jobs SET status='running' WHERE id=:i"), {"i": jid.id})
    pipe2 = Pipeline(store, s, pipe.registry, ScriptedLLM(), sleep=lambda _x: None, poll_interval=0)
    Worker(store, pipe2, s, name="w2").run_once()
    assert len(ad.starts) == done_before                                           # a szolgáltatói lépések nem ismétlődtek
    assert store.get_job(jid.id).status in (JobStatus.partially_completed, JobStatus.completed)


def test_cancel_between_steps_keeps_partial_results(tmp_path):
    store, s, pipe, ad, _ = make(tmp_path)
    job, _ = store.create_job(Q, [], ["hu"], s.limits)
    w = Worker(store, pipe, s, name="w1")
    w.run_once()
    store.set_status(job.id, JobStatus.queued, approved_plan=store.get_field(job.id, "plan"))
    orig = ad.start
    n = {"c": 0}
    def start_then_cancel(c, p, params):
        n["c"] += 1
        if n["c"] == 6:
            store.request_cancel(job.id)
        return orig(c, p, params)
    ad.start = start_then_cancel
    w.run_once()
    assert store.get_job(job.id).status == JobStatus.cancelled
    assert store.get_field(job.id, "report")                                       # a részeredmény/jelentés megmaradt
    assert len(store.videos(job.id)) > 0


def test_runtime_limit_stops_job(tmp_path):
    store, s, pipe, ad, _ = make(tmp_path, limits=Limits(max_runtime_seconds=30))
    ticks = iter(range(0, 10_000, 100))
    pipe.clock = lambda: next(ticks)
    jid = run_to_end(store, pipe, s)
    assert store.get_job(jid).status in (JobStatus.failed, JobStatus.partially_completed)
    assert "futásidő" in store.get_field(jid, "report") or "runtime" in store.get_field(jid, "report")


def test_video_cap_and_dedupe(tmp_path):
    store, s, pipe, ad, _ = make(tmp_path, limits=Limits(max_videos=1))
    jid = run_to_end(store, pipe, s, q="https://www.youtube.com/watch?v=AAAAAAAAAAA https://youtu.be/AAAAAAAAAAA https://www.youtube.com/watch?v=BBBBBBBBBBB")
    assert len(store.videos(jid)) == 1


def test_token_budget_stops_new_llm_calls(tmp_path):
    store, s, pipe, ad, llm = make(tmp_path, llm=ScriptedLLM(tokens=60_000), limits=Limits(llm_token_budget=100_000))
    jid = run_to_end(store, pipe, s, q="https://www.youtube.com/watch?v=AAAAAAAAAAA https://www.youtube.com/watch?v=BBBBBBBBBBB", approve=True)
    assert store.get_field(jid, "llm_tokens_used") <= 100_000 + 60_000 * 8          # nincs új hívás a keret kimerülése után
    assert any("tokenkeret" in e for e in [store.get_field(jid, "error") or ""])


def test_prompt_injection_in_transcript_cannot_leak_or_change_task(tmp_path):
    llm = ScriptedLLM()
    store, s, pipe, ad, _ = make(tmp_path, llm=llm)
    s.apify_token = SecretStr("super-secret-token-value")
    run_to_end(store, pipe, s, q="https://www.youtube.com/watch?v=BBBBBBBBBBB")
    joined = "\n".join(a + b for a, b in llm.prompts)
    assert "super-secret-token-value" not in joined
    sys_prompt, user = next(x for x in llm.prompts if "<untrusted_transcript>" in x[1])
    assert "NEM MEGBÍZHATÓ" in sys_prompt and "Ignore all previous instructions" in user.split("<untrusted_transcript>")[1]


def test_production_refuses_fixture_and_unconfigured_gives_clear_error(tmp_path):
    reg = AdapterRegistry(production=True)
    with pytest.raises(ProviderPermanentError):
        reg.register(FixtureAdapter.from_file(FIX))
    e = make_engine(f"sqlite:///{tmp_path/'p.db'}")
    migrate(e)
    store, s = Store(e), Settings(mode="production", api_token=SecretStr("t" * 20))
    pipe = Pipeline(store, s, reg, NullLLM(), sleep=lambda _x: None)
    job, _ = store.create_job("https://www.youtube.com/watch?v=AAAAAAAAAAA", [], ["hu"], s.limits)
    Worker(store, pipe, s, name="w").run_once()
    store.set_status(job.id, JobStatus.queued, approved_plan=store.get_field(job.id, "plan"))
    Worker(store, pipe, s, name="w").run_once()
    j = store.get_job(job.id)
    assert j.status == JobStatus.failed and "Nincs beállított szolgáltató" in (store.get_field(job.id, "error") or "")
    assert store.findings(job.id) == [] and store.transcripts(job.id) == []          # semmi nem lett kitalálva


# ---- executor ----
def _ex(tmp_path, ad, cancel=lambda: None):
    store, s, pipe, _, _ = make(tmp_path, adapter=ad)
    job, _ = store.create_job("kérdés egy", [], ["hu"], Limits())
    return store, job.id, Executor(store, s, cancel, lambda _x: None, 0)


def test_uncertain_start_is_never_blindly_repeated(tmp_path):
    ad = CountingAdapter(FixtureAdapter.from_file(FIX), start_error=UncertainOutcome("időtúllépés"))
    store, jid, ex = _ex(tmp_path, ad)
    params = {"url": "https://www.youtube.com/watch?v=AAAAAAAAAAA"}
    with pytest.raises(UncertainRun):
        ex.run(jid, "meta", ad, Capability.fetch_video_metadata, Platform.youtube, params, 1.0)
    ad.start_error = None
    with pytest.raises(UncertainRun):                                    # újrapróbálás: állapot nem ellenőrizhető -> nem indít újat
        ex.run(jid, "meta", ad, Capability.fetch_video_metadata, Platform.youtube, params, 1.0)
    assert ad.starts == []


def test_saved_run_id_is_polled_not_restarted(tmp_path):
    ad = CountingAdapter(FixtureAdapter.from_file(FIX))
    store, jid, ex = _ex(tmp_path, ad)
    params = {"url": "https://www.youtube.com/watch?v=AAAAAAAAAAA"}
    from video_research.executor import request_key
    key = request_key(Capability.fetch_video_metadata, Platform.youtube, params)
    store.save_provider_run(jid, "meta", "fixture", "fetch_video_metadata", key, "running", provider_run_id="run-123")
    run_id, md, _ = ex.run(jid, "meta", ad, Capability.fetch_video_metadata, Platform.youtube, params, 1.0)
    assert run_id == "run-123" and ad.starts == []


def test_cost_budget_blocks_new_paid_run(tmp_path):
    ad = CountingAdapter(FixtureAdapter.from_file(FIX), cost=0.4)
    store, jid, ex = _ex(tmp_path, ad)
    p = {"url": "https://www.youtube.com/watch?v=AAAAAAAAAAA"}
    ex.run(jid, "m1", ad, Capability.fetch_video_metadata, Platform.youtube, p, 0.5)
    with pytest.raises(CostBudgetExhausted):
        ex.run(jid, "m2", ad, Capability.fetch_video_metadata, Platform.youtube, {"url": "https://www.youtube.com/watch?v=BBBBBBBBBBB"}, 0.5)
    assert len(ad.starts) == 1


def test_retryable_start_backs_off_then_succeeds(tmp_path):
    ad = CountingAdapter(FixtureAdapter.from_file(FIX))
    store, jid, ex = _ex(tmp_path, ad)
    seq = [RetryableError("429"), RetryableError("503")]
    inner_start = ad.start
    def flaky(c, p, params):
        if seq:
            raise seq.pop(0)
        return inner_start(c, p, params)
    ad.start = flaky
    ex.run(jid, "m", ad, Capability.fetch_video_metadata, Platform.youtube, {"url": "https://www.youtube.com/watch?v=AAAAAAAAAAA"}, 1.0)
    assert len(ad.starts) == 1


def test_cancel_during_run_aborts_best_effort_and_warns(tmp_path):
    ad = CountingAdapter(FixtureAdapter.from_file(FIX), hang=True)
    flag = {"n": 0}
    def cancel():
        flag["n"] += 1
        if flag["n"] > 3:
            raise JobStopped("cancelled")
    store, jid, ex = _ex(tmp_path, ad, cancel)
    with pytest.raises(JobStopped):
        ex.run(jid, "m", ad, Capability.fetch_video_metadata, Platform.youtube, {"url": "https://www.youtube.com/watch?v=AAAAAAAAAAA"}, 1.0)
    assert ad.aborts and any("nem garantált" in n for n in ex.notes)


def test_unknown_cost_is_not_invented(tmp_path):
    ad = CountingAdapter(FixtureAdapter.from_file(FIX), cost_known=False)
    store, jid, ex = _ex(tmp_path, ad)
    ex.run(jid, "m", ad, Capability.fetch_video_metadata, Platform.youtube, {"url": "https://www.youtube.com/watch?v=AAAAAAAAAAA"}, 1.0)
    run = store.provider_runs(jid)[0]
    assert run["cost_usd"] is None and run["cost_known"] == 0


# ---- Apify adapter (hamis klienssel) ----
class FakeRun:
    def __init__(self, id="r1", status="SUCCEEDED", ds="d1", cost=0.02):
        self.id, self.status, self.default_dataset_id, self.usage_total_usd = id, status, ds, cost


class FakeClient:
    def __init__(self, items=None, err=None):
        self.items, self.err, self.started = items or [], err, []
    def actor(self, aid):
        outer = self
        class A:
            def start(self, **kw):
                if outer.err:
                    raise outer.err
                outer.started.append((aid, kw))
                return FakeRun()
        return A()
    def run(self, rid):
        class R:
            def get(_s): return FakeRun()
            def abort(_s, gracefully=None): return None
        return R()
    def dataset(self, did):
        outer = self
        class D:
            def iterate_items(_s, limit=None): return iter(outer.items)
        return D()


ACT = {"youtube:fetch_transcript": ActorConfig(actor_id="owner/some-actor", capability="fetch_transcript", input_template={"videoUrl": "{url}"},
                                                output_map={"segments": "0.captions", "segment_text": "t", "segment_start": "s", "segment_end": "e", "language": "0.lang"},
                                                verified_on="2026-11-20")}


def test_apify_requires_verified_configured_actor_and_no_login():
    ad = ApifyAdapter(SecretStr("tok-dummy-value"), {}, lambda t: FakeClient())
    assert not ad.supports(Capability.fetch_transcript, Platform.youtube)
    with pytest.raises(ProviderNotConfigured):
        ad.start(Capability.fetch_transcript, Platform.youtube, {"url": "u"})
    unverified = {"youtube:fetch_transcript": ActorConfig(actor_id="o/a", capability="fetch_transcript")}
    with pytest.raises(ProviderNotConfigured):
        ApifyAdapter(SecretStr("tok-dummy-value"), unverified, lambda t: FakeClient()).start(Capability.fetch_transcript, Platform.youtube, {"url": "u"})
    login = {"youtube:fetch_transcript": ActorConfig(actor_id="o/a", capability="fetch_transcript", verified_on="2026-11-20", requires_cookies_or_login=True)}
    with pytest.raises(ProviderNotConfigured):
        ApifyAdapter(SecretStr("tok-dummy-value"), login, lambda t: FakeClient()).start(Capability.fetch_transcript, Platform.youtube, {"url": "u"})


def test_apify_start_passes_cost_cap_and_maps_transcript():
    fc = FakeClient(items=[{"lang": "hu", "captions": [{"t": "Szia világ", "s": 0, "e": 2}, {"t": "  ", "s": 2}, {"t": "Második sor", "s": 2.5}]}])
    ad = ApifyAdapter(SecretStr("tok-dummy-value"), ACT, lambda t: fc)
    rid = ad.start(Capability.fetch_transcript, Platform.youtube, {"url": "https://www.youtube.com/watch?v=AAAAAAAAAAA"})
    aid, kw = fc.started[0]
    assert rid == "r1" and aid == "owner/some-actor" and kw["run_input"] == {"videoUrl": "https://www.youtube.com/watch?v=AAAAAAAAAAA"}
    assert float(kw["max_total_charge_usd"]) == 0.5
    assert ad.poll(rid).cost_usd == 0.02
    tr = ad.results(Capability.fetch_transcript, Platform.youtube, rid, {})
    assert [s.text for s in tr.segments] == ["Szia világ", "Második sor"] and tr.segments[0].end == 2


def test_apify_error_classification():
    class E(Exception):
        def __init__(self, code): self.status_code = code
    with pytest.raises(ProviderPermanentError):
        ApifyAdapter(SecretStr("tok-dummy-value"), ACT, lambda t: FakeClient(err=E(403))).start(Capability.fetch_transcript, Platform.youtube, {"url": "u"})
    for err in (E(500), E(429), TimeoutError()):
        with pytest.raises(UncertainOutcome):
            ApifyAdapter(SecretStr("tok-dummy-value"), ACT, lambda t: FakeClient(err=err)).start(Capability.fetch_transcript, Platform.youtube, {"url": "u"})


def test_render_input_types():
    assert render_input({"n": "{max_items}", "q": "x {query}"}, {"max_items": 5, "query": "ai"}) == {"n": 5, "q": "x ai"}


# ---- API ----
def api_client(tmp_path, token="t" * 20):
    store, s, pipe, ad, llm = make(tmp_path)
    s.api_token = SecretStr(token) if token else None
    return TestClient(create_app(store, s)), store, s, pipe


H = {"Authorization": "Bearer " + "t" * 20}


def test_api_auth_and_async_job_id(tmp_path):
    c, store, s, pipe = api_client(tmp_path)
    assert c.post("/api/jobs", json={"request": "android ai"}).status_code == 401
    assert c.post("/api/jobs", json={"request": "android ai"}, headers={"Authorization": "Bearer rossz"}).status_code == 401
    r = c.post("/api/jobs", json={"request": Q}, headers={**H, "Idempotency-Key": "abcdef123456"})
    assert r.status_code == 202 and r.json()["status"] == "queued" and r.json()["created"]
    again = c.post("/api/jobs", json={"request": Q}, headers={**H, "Idempotency-Key": "abcdef123456"})
    assert again.status_code == 200 and again.json()["job_id"] == r.json()["job_id"]
    clash = c.post("/api/jobs", json={"request": "másik kérés"}, headers={**H, "Idempotency-Key": "abcdef123456"})
    assert clash.status_code == 409


def test_api_validation_and_limits_cannot_be_raised(tmp_path):
    c, store, s, pipe = api_client(tmp_path)
    assert c.post("/api/jobs", json={"request": Q, "platforms": ["instagram"]}, headers=H).status_code == 422
    r = c.post("/api/jobs", json={"request": Q, "limits": {"max_videos": 500}}, headers=H).json()
    assert store.get_job(r["job_id"]).limits.max_videos == 10


def test_api_full_flow_approve_report_formats(tmp_path):
    c, store, s, pipe = api_client(tmp_path)
    jid = c.post("/api/jobs", json={"request": Q}, headers=H).json()["job_id"]
    assert c.post(f"/api/jobs/{jid}/approve", json={"plan_hash": "0" * 64}, headers=H).status_code == 409   # tervezés előtt nem hagyható jóvá
    Worker(store, pipe, s, name="w").run_once()
    v = c.get(f"/api/jobs/{jid}", headers=H).json()
    assert v["status"] == "awaiting_approval" and v["plan"]["platforms"] and "cost_note" in v
    assert c.get(f"/api/jobs/{jid}/report", headers=H).status_code == 409
    bad = c.post(f"/api/jobs/{jid}/approve", json={"plan_hash": "f" * 64}, headers=H)
    assert bad.status_code == 409 and "nem egyezik" in bad.text                    # rossz hash: nincs jóváhagyás
    assert c.post(f"/api/jobs/{jid}/approve", json={"plan_hash": v["plan"]["plan_hash"]}, headers=H).json()["status"] == "queued"
    Worker(store, pipe, s, name="w").run_once()
    md = c.get(f"/api/jobs/{jid}/report?format=markdown", headers=H)
    assert "TESZT-FIXTURE" in md.text and "AutoDroid" in md.text and "nem független ellenőrzés" in md.text and "youtube.com/watch?v=AAAAAAAAAAA" in md.text
    assert c.get(f"/api/jobs/{jid}/report?format=csv", headers=H).text.startswith("finding_id,")
    assert c.get(f"/api/jobs/{jid}/report", headers=H).json()["source_list"]


def test_api_cancel_queued_job_and_best_effort_note(tmp_path):
    c, store, s, pipe = api_client(tmp_path)
    jid = c.post("/api/jobs", json={"request": Q}, headers=H).json()["job_id"]
    r = c.post(f"/api/jobs/{jid}/cancel", headers=H).json()
    assert r["status"] == "cancelled" and "best effort" in r["cancel_note"].lower()
    assert c.post(f"/api/jobs/{jid}/approve", json={"plan_hash": "0" * 64}, headers=H).status_code == 409


def test_prod_api_without_token_is_closed(tmp_path):
    store, s, pipe, ad, llm = make(tmp_path)
    s.mode, s.api_token = "production", None
    assert TestClient(create_app(store, s)).get("/api/jobs/x").status_code == 503
