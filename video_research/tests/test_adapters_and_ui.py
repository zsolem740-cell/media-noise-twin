"""A közvetlen (ingyenes) adapterek, az extraktív alapút, a terv-hash, a törlés és a felület tesztjei. Hálózat nincs: minden külső hívás hamis."""
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient
from youtube_transcript_api import _errors as E

from video_research.adapters.base import AdapterRegistry, Capability, ProviderPermanentError
from video_research.adapters.http import get_json
from video_research.adapters.tiktok import TikTokAdapter
from video_research.adapters.youtube import YouTubeAdapter
from video_research.api import create_app
from video_research.config import SecretStr, Settings, load_settings
from video_research.db import Store, make_engine, migrate
from video_research.extractive import ExtractiveBaselineLLM
from video_research.models import JobStatus, Limits, Platform, ResearchReport
from video_research.pipeline import Pipeline
from video_research.util import RetryableError, now
from video_research.worker import Worker

YT = "https://www.youtube.com/watch?v=AAAAAAAAAAA"
TT = "https://www.tiktok.com/@fixture_user/video/1234567890123"


class FakeResp:
    def __init__(self, status=200, body=b"{}", chunks=None):
        self.status_code, self._body = status, body
    def iter_content(self, n): yield self._body
    def close(self): pass


class FakeSession:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp, exc, []
    def get(self, url, **kw):
        self.calls.append((url, kw))
        if self.exc: raise self.exc
        return self.resp


def snip(text, start, dur): return SimpleNamespace(text=text, start=start, duration=dur)


class FakeApi:
    def __init__(self, result=None, exc=None): self.result, self.exc, self.calls = result, exc, []
    def fetch(self, vid, languages):
        self.calls.append((vid, list(languages)))
        if self.exc: raise self.exc
        return self.result


def hu_transcript(auto=False):
    return SimpleNamespace(language_code="hu", is_generated=auto, snippets=[
        snip("Az AutoDroid eszköz root nélkül vezérli a telefont.", 1.0, 3.0), snip("Viszont gyakran elakad a felugró ablakoknál.", 4.0, 2.5)])


def yt(api=None, session=None):
    return YouTubeAdapter(session=session or FakeSession(FakeResp(200, json.dumps({"title": "T", "author_name": "A"}).encode())),
                          transcript_api_factory=lambda: api or FakeApi(hu_transcript()))


def test_capabilities_are_honest():
    assert yt().capabilities()["fetch_transcript"] and not yt().capabilities()["search_videos"] and not yt().capabilities()["visual"]
    tt = TikTokAdapter()
    assert tt.capabilities()["fetch_video_metadata"] and not tt.capabilities()["fetch_transcript"]
    assert not tt.supports(Capability.fetch_transcript, Platform.tiktok) and not yt().supports(Capability.search_videos, Platform.youtube)


def test_youtube_metadata_and_captions_keep_real_timestamps():
    a = yt()
    md = a.fetch_metadata(YT)
    assert md.title == "T" and md.creator == "A" and md.duration_seconds is None and md.published_at is None      # nem ismert: null
    tr = a.fetch_captions(YT, ["hu", "en"])
    assert tr.language == "hu" and tr.segments[0].start == 1.0 and tr.segments[0].end == 4.0 and tr.auto_generated is False


def test_youtube_no_captions_gives_empty_not_invented():
    for exc in (E.TranscriptsDisabled("x"), E.NoTranscriptFound("x", ["hu"], None)):
        assert yt(FakeApi(exc=exc)).fetch_captions(YT, ["hu"]).segments == []


def test_youtube_block_is_clear_error_and_not_bypassed():
    api = FakeApi(exc=E.IpBlocked("x"))
    with pytest.raises(ProviderPermanentError) as ei:
        yt(api).fetch_captions(YT, ["hu"])
    assert "nem kerüljük meg" in str(ei.value) and len(api.calls) == 1


def test_youtube_transient_network_is_retryable():
    with pytest.raises(RetryableError):
        yt(FakeApi(exc=requests.ConnectionError("x"))).fetch_captions(YT, ["hu"])


def test_youtube_unavailable_is_permanent():
    with pytest.raises(ProviderPermanentError):
        yt(FakeApi(exc=E.VideoUnavailable("x"))).fetch_captions(YT, ["hu"])


def test_adapter_rejects_foreign_urls_before_any_request():
    s = FakeSession(FakeResp())
    with pytest.raises(Exception):
        yt(session=s).fetch_metadata("https://evil.example/watch?v=AAAAAAAAAAA")
    with pytest.raises(Exception):
        TikTokAdapter(session=s).fetch_metadata(YT)
    assert s.calls == []


def test_http_limits_no_redirect_size_host_status():
    h = frozenset({"www.youtube.com"})
    with pytest.raises(ProviderPermanentError):
        get_json("https://evil.example/x", {}, h, FakeSession(FakeResp()))
    with pytest.raises(ProviderPermanentError):
        get_json("http://www.youtube.com/x", {}, h, FakeSession(FakeResp()))
    with pytest.raises(ProviderPermanentError):
        get_json("https://www.youtube.com/x", {}, h, FakeSession(FakeResp(302)))
    with pytest.raises(ProviderPermanentError):
        get_json("https://www.youtube.com/x", {}, h, FakeSession(FakeResp(403)))
    with pytest.raises(RetryableError):
        get_json("https://www.youtube.com/x", {}, h, FakeSession(FakeResp(429)))
    with pytest.raises(RetryableError):
        get_json("https://www.youtube.com/x", {}, h, FakeSession(exc=requests.Timeout()))
    with pytest.raises(ProviderPermanentError):
        get_json("https://www.youtube.com/x", {}, h, FakeSession(FakeResp(200, b"x" * (300 * 1024))))
    with pytest.raises(ProviderPermanentError):
        get_json("https://www.youtube.com/x", {}, h, FakeSession(FakeResp(200, b"nem json")))
    s = FakeSession(FakeResp(200, b'{"a":1}'))
    get_json("https://www.youtube.com/x", {}, h, s)
    assert s.calls[0][1]["allow_redirects"] is False and s.calls[0][1]["timeout"]


# ---- teljes folyamat valódi adapterosztályokkal (hamis hálózattal) + extraktív alapút ----
def make(tmp_path, api=None, tt_session=None):
    e = make_engine(f"sqlite:///{tmp_path/'n.db'}")
    migrate(e)
    store, s = Store(e), Settings(limits=Limits())
    reg = AdapterRegistry(production=False)
    reg.register(yt(api))
    reg.register(TikTokAdapter(session=tt_session or FakeSession(FakeResp(200, json.dumps({"title": "TT", "author_name": "tt_user"}).encode()))))
    pipe = Pipeline(store, s, reg, ExtractiveBaselineLLM(), semantic=False, sleep=lambda _x: None, poll_interval=0)
    return store, s, pipe


def run_links(store, s, pipe, text):
    job, _ = store.create_job(text, [], ["hu", "en"], s.limits)
    w = Worker(store, pipe, s, name="w")
    w.run_once()
    store.set_status(job.id, JobStatus.queued, approved_plan=store.get_field(job.id, "plan"))
    w.run_once()
    return job.id


def test_vertical_slice_links_to_sourced_hungarian_extract(tmp_path):
    store, s, pipe = make(tmp_path)
    jid = run_links(store, s, pipe, f"Hol akad el az ügynök az ablakoknál, és milyen eszközt említenek? {YT} {TT}")
    r = ResearchReport.model_validate_json(store.get_field(jid, "report"))
    assert store.get_job(jid).status == JobStatus.partially_completed             # a TikTok átirat nélküli
    f = next(x for x in r.findings if "elakad" in x.statement_hu)
    ref = f.source_references[0]
    assert f.category.value == "warning" and ref.timestamp == 4.0 and ref.transcript_segment_ids and "elakad" in ref.supporting_quote
    assert any("TikTok" in m or "tiktok" in m for m in r.missing_information)     # a TikTok hiány kimondva
    assert any("Vizuális elemzés ebben a verzióban nincs" in l for l in r.coverage_limitations)
    assert r.findings and all(x.evidence_status.value in ("source_claim", "repeated_across_sources") for x in r.findings)
    src = next(x for x in r.source_list if x["platform"] == "youtube")
    assert src["provider"] == "youtube-captions" and src["transcript_language"] == "hu" and src["auto_generated"] is False


def test_extractive_never_invents_and_marks_foreign_language():
    llm = ExtractiveBaselineLLM()
    user = ("Kutatási kérdés: Mi a phone battery problem lényege?\nÁtirat nyelve: en\n<untrusted_transcript>\n"
            "[s0] The phone battery drain is the main problem.\n[s1] Hello and welcome back.\n</untrusted_transcript>")
    out = llm.complete_json(system="", user=user, schema_name="findings", max_tokens=100).data["findings"]
    # korlát: a kulcsszó-egyezés nyelvfüggő, magyar kérdéssel angol átiratra nem talál (lásd docs)
    assert len(out) == 1 and out[0]["quotes"][0]["quote"] == "The phone battery drain is the main problem."
    assert out[0]["statement_hu"].startswith("[eredeti nyelv: en]") and any("Magyar fordítás nincs" in l for l in out[0]["limitations"])


def test_blocked_youtube_gives_failed_job_with_clear_error_no_fabrication(tmp_path):
    store, s, pipe = make(tmp_path, api=FakeApi(exc=E.IpBlocked("x")))
    jid = run_links(store, s, pipe, f"Android ügynök problémák {YT}")
    j = store.get_job(jid)
    assert j.status == JobStatus.failed and "nem kerüljük meg" in (store.get_field(jid, "error") or "")
    assert store.transcripts(jid) == [] and store.findings(jid) == []


def test_no_captions_marks_video_and_reports_gap(tmp_path):
    store, s, pipe = make(tmp_path, api=FakeApi(exc=E.TranscriptsDisabled("x")))
    jid = run_links(store, s, pipe, f"Android ügynök problémák {YT}")
    r = ResearchReport.model_validate_json(store.get_field(jid, "report"))
    assert any("Nincs hozzáférhető átirat" in m for m in r.missing_information) and r.findings == []


# ---- API: terv-hash, export, törlés, előnézet, felület ----
H = {"Authorization": "Bearer " + "t" * 20}


def client(tmp_path):
    store, s, pipe = make(tmp_path)
    s.api_token = SecretStr("t" * 20)
    reg = pipe.registry
    return TestClient(create_app(store, s, reg)), store, s, pipe


def test_plan_preview_is_free_and_stores_nothing(tmp_path):
    c, store, s, pipe = client(tmp_path)
    r = c.post("/api/jobs/plan", json={"request": f"Android ügynökök {YT}"}, headers=H).json()
    assert r["direct_urls"] == [YT] and len(r["plan_hash"]) == 64 and r["providers"]["youtube:fetch_transcript"] == "youtube-captions"
    assert r["platforms"] == ["youtube"] and r["estimated_cost_usd"] == 0 and any("megadott link" in o for o in r["operations"])
    with store.e.connect() as conn:
        from sqlalchemy import text
        assert conn.execute(text("SELECT count(*) FROM research_jobs")).scalar() == 0


def test_approval_bound_to_plan_hash_and_changed_plan_needs_new_approval(tmp_path):
    c, store, s, pipe = client(tmp_path)
    jid = c.post("/api/jobs", json={"request": f"Android ügynökök problémái {YT}"}, headers=H).json()["job_id"]
    Worker(store, pipe, s, name="w").run_once()
    plan = c.get(f"/api/jobs/{jid}", headers=H).json()["plan"]
    # a tárolt terv módosítása (pl. más link) a hash-t érvénytelenné teszi
    from sqlalchemy import text
    tampered = json.loads(store.get_field(jid, "plan")); tampered["direct_urls"].append(TT)
    with store.e.begin() as conn:
        conn.execute(text("UPDATE research_jobs SET plan=:p WHERE id=:i"), {"p": json.dumps(tampered), "i": jid})
    r = c.post(f"/api/jobs/{jid}/approve", json={"plan_hash": plan["plan_hash"]}, headers=H)
    assert r.status_code == 409 and "sértetlen" in r.text
    assert store.get_job(jid).status == JobStatus.awaiting_approval


def test_export_delete_and_ui(tmp_path):
    c, store, s, pipe = client(tmp_path)
    jid = c.post("/api/jobs", json={"request": f"Android ügynökök problémái {YT}"}, headers=H).json()["job_id"]
    Worker(store, pipe, s, name="w").run_once()
    ph = c.get(f"/api/jobs/{jid}", headers=H).json()["plan"]["plan_hash"]
    c.post(f"/api/jobs/{jid}/approve", json={"plan_hash": ph}, headers=H)
    Worker(store, pipe, s, name="w").run_once()
    assert c.get(f"/api/jobs/{jid}/export?format=csv", headers=H).text.startswith("finding_id,")
    assert "# Kutatási jelentés" in c.get(f"/api/jobs/{jid}/export?format=markdown", headers=H).text
    assert c.delete(f"/api/jobs/{jid}", headers=H).json() == {"deleted": jid}
    assert c.get(f"/api/jobs/{jid}", headers=H).status_code == 404 and store.videos(jid) == [] and store.transcripts(jid) == []
    page = c.get("/")
    assert page.status_code == 200 and "innerHTML" not in page.text and "API-kulcsos MVP" in page.text       # nem megbízható szöveg csak textContent-tel jelenik meg
    assert c.get("/health").json() == {"ok": True}


def test_delete_refused_while_leased_and_retention_purge(tmp_path):
    c, store, s, pipe = client(tmp_path)
    j1, _ = store.create_job("kérdés egy", [], ["hu"], Limits())
    store.claim_next("w", 60)
    assert not store.delete_job(j1.id) and store.get_job(j1.id)
    j2, _ = store.create_job("kérdés kettő", [], ["hu"], Limits())
    store.set_status(j2.id, JobStatus.completed)
    assert store.purge_expired(1) == 0
    assert store.purge_expired(1, when=now() + timedelta(days=3)) == 1 and store.get_job(j2.id) is None and store.get_job(j1.id)


def test_config_env_aliases_and_defaults():
    s = load_settings({"DATABASE_URL": "sqlite:///x.db", "APP_API_KEY": "k" * 20, "DEFAULT_MAX_VIDEOS": "5", "DATA_RETENTION_DAYS": "7", "VR_MODE": "production"})
    assert s.database_url == "sqlite:///x.db" and s.limits.max_videos == 5 and s.data_retention_days == 7 and s.allow_cloud_transcription is False
    assert "k" * 20 not in repr(s)                                   # a kulcs nem szivárog a repr-be


def test_exhausted_retries_fail_only_that_video_with_report(tmp_path):
    store, s, pipe = make(tmp_path, api=FakeApi(exc=requests.ConnectionError("proxy")))
    s.max_retries = 2
    jid = run_links(store, s, pipe, f"Android ügynök problémák {YT}")
    j = store.get_job(jid)
    assert j.status == JobStatus.failed and store.get_field(jid, "report")                 # jelentés van, nem csak hibaüzenet
    assert "hálózati hiba" in (store.get_field(jid, "error") or "")
