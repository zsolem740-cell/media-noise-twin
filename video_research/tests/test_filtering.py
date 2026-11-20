"""A zajszűrő termékcél tesztjei: nincs kötelező találat, részletszintű szűrés, hasznosság ≠ alátámasztottság, három kimeneti csoport,
rögzített arány nélkül, ismétlés/eltérő feltétel kezelése, rövid fő jelentés + külön bizonyíték és napló, visszajelzés."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from video_research.adapters.base import AdapterRegistry
from video_research.adapters.fixture import FixtureAdapter
from video_research.api import create_app
from video_research.config import SecretStr, Settings
from video_research.db import Store, make_engine, migrate
from video_research.extractive import ExtractiveBaselineLLM
from video_research.llm import LLMResult
from video_research.models import Disposition, JobStatus, Limits, ResearchReport, SkipReason
from video_research.pipeline import Pipeline
from video_research.report import NO_RESULT
from video_research.worker import Worker

H = {"Authorization": "Bearer " + "t" * 20}
U1, U2 = "https://www.youtube.com/watch?v=AAAAAAAAAAA", "https://www.youtube.com/watch?v=BBBBBBBBBBB"


def vid(url, title, texts, lang="hu"):
    return {"platform": "youtube", "url": url, "title": title, "creator": "c" + url[-2:], "duration_seconds": 60, "language": lang, "origin": "platform_caption",
            "segments": [{"text": t, "start": i * 5.0, "end": i * 5.0 + 4} for i, t in enumerate(texts)]}


class Cand:
    """Forgatókönyves modell: a jelölteket a videó átiratának szegmens-indexe alapján adja (az idézet mindig szó szerinti)."""
    def __init__(self, plan_by_url):
        self.plan, self.calls = plan_by_url, 0

    def complete_json(self, *, system, user, schema_name, max_tokens):
        self.calls += 1
        if schema_name == "semantic":
            return LLMResult({"verdict": "doubtful" if "KÉTES" in user else "consistent"}, 1)
        url = re.search(r"Videó: \w+, (\S+)", user).group(1)
        segs = {}
        for line in user.split("<untrusted_transcript>")[1].split("</untrusted_transcript>")[0].strip().splitlines():
            sid, text = line[1:].split("] ", 1)
            segs[int(sid.rsplit(":s", 1)[1])] = (sid, text)
        out = []
        for idx, extra in self.plan[url]:
            sid, text = segs[idx]
            out.append({"category": "claim", "statement_hu": extra.pop("statement_hu", text), "quotes": [{"segment_id": sid, "quote": text}], **extra})
        return LLMResult({"findings": out}, 10)


def build(tmp_path, videos, llm, semantic=True):
    e = make_engine(f"sqlite:///{tmp_path/'f.db'}")
    migrate(e)
    store, s = Store(e), Settings(limits=Limits())
    reg = AdapterRegistry(production=False)
    reg.register(FixtureAdapter({"videos": videos}))
    pipe = Pipeline(store, s, reg, llm, sleep=lambda _x: None, poll_interval=0, semantic=semantic)
    return store, s, pipe


def run(store, s, pipe, urls, known=None, q="Milyen eszközök kezelik az ablakokat az Android ügynököknél?"):
    job, _ = store.create_job("\n".join([q, *urls]), [], ["hu"], s.limits, known_information=known)
    w = Worker(store, pipe, s, name="w")
    w.run_once()
    store.set_status(job.id, JobStatus.queued, approved_plan=store.get_field(job.id, "plan"))
    w.run_once()
    return job.id, ResearchReport.model_validate_json(store.get_field(job.id, "report"))


D = {"relevance": "direct", "concrete": True}
T1 = ["Sziasztok, üdv a csatornán!", "Az AutoDroid eszköz root nélkül kezeli a felugró ablakokat.", "Iratkozzatok fel és nyomjatok egy lájkot!", "A rendezés 2024-ben volt Budapesten."]


def test_no_result_is_a_valid_outcome_and_report_is_not_padded(tmp_path):
    llm = Cand({U1: [(0, {"relevance": "none"}), (2, {"relevance": "none"})]})
    store, s, pipe = build(tmp_path, [vid(U1, "V1", T1)], llm)
    jid, r = run(store, s, pipe, [U1])
    assert store.get_job(jid).status == JobStatus.completed             # nem hiba és nem részleges: a „nincs találat” érvényes eredmény
    assert r.findings == [] and r.no_result_note == NO_RESULT
    assert {e.reason_code for e in r.filter_log} == {SkipReason.irrelevant}
    c = TestClient(create_app(store, s, pipe.registry)); s.api_token = SecretStr("t" * 20)
    md = c.get(f"/api/jobs/{jid}/report?format=markdown", headers=H).text
    assert NO_RESULT in md and "## Megtartandó információk" not in md and "Ellenőrizendő nyomok" not in md


def test_detail_level_filtering_weak_video_keeps_one_good_video_drops_noise(tmp_path):
    weak = ["Ma főzök valamit.", "Sok mindent kipróbáltam, de nem volt jó.", "A ClickBot eszköz képes a rejtett menük megnyitására.", "Köszönöm a figyelmet."]
    llm = Cand({U1: [(1, {**D}), (0, {"relevance": "none"}), (2, {"relevance": "none"}), (3, {"relevance": "none"})],
                U2: [(2, {**D})]})
    store, s, pipe = build(tmp_path, [vid(U1, "Jó videó", T1), vid(U2, "Gyenge videó", weak)], llm)
    jid, r = run(store, s, pipe, [U1, U2])
    kept = [f.statement_hu for f in r.findings if f.disposition == Disposition.keep]
    assert len(kept) == 2 and any("AutoDroid" in k for k in kept) and any("ClickBot" in k for k in kept)     # a gyenge videó egyetlen részlete is megmarad
    assert not any("lájkot" in f.statement_hu or "Sziasztok" in f.statement_hu for f in r.findings)          # a jó videó irreleváns részei nem
    assert r.filter_stats["skipped_by_reason"]["irrelevant"] == 3


def test_usefulness_and_support_are_separate_axes(tmp_path):
    # pontos, ellenőrzött idézet, de a modell szerint csak részben releváns / ellenőrzendő: nyom, nem megtartandó; az alátámasztottság nem nő
    llm = Cand({U1: [(1, {"relevance": "partial"}), (3, {**D, "needs_check": "szokatlan, egyetlen forrásból származó állítás"})]})
    store, s, pipe = build(tmp_path, [vid(U1, "V", T1)], llm)
    jid, r = run(store, s, pipe, [U1])
    assert [f.disposition for f in r.findings] == [Disposition.lead, Disposition.lead]
    assert all(f.evidence_status.value == "source_claim" for f in r.findings)
    assert any("csak részben releváns" in x for x in r.findings[0].lead_reasons) and "szokatlan" in r.findings[1].lead_reasons[0]
    assert all(ref.supporting_quote for f in r.findings for ref in f.source_references)


def test_doubtful_semantic_check_demotes_to_lead(tmp_path):
    t = ["Az AutoDroid root nélkül kezeli az ablakokat. KÉTES"]
    llm = Cand({U1: [(0, {**D})]})
    store, s, pipe = build(tmp_path, [vid(U1, "V", t)], llm)
    jid, r = run(store, s, pipe, [U1])
    f = r.findings[0]
    assert f.disposition == Disposition.lead and any("kétes" in x for x in f.lead_reasons)


def test_fabricated_quote_is_skipped_log_and_never_a_finding(tmp_path):
    class Fab:
        def complete_json(self, **k):
            return LLMResult({"findings": [{"category": "claim", "statement_hu": "Kitalált, de meggyőző állítás az ablakokról", "relevance": "direct", "concrete": True,
                                            "quotes": [{"segment_id": "x", "quote": "ez a mondat sosem hangzott el sehol"}]}]}, 5)
    store, s, pipe = build(tmp_path, [vid(U1, "V", T1)], Fab())
    jid, r = run(store, s, pipe, [U1])
    assert r.findings == [] and r.no_result_note == NO_RESULT
    assert [e.reason_code for e in r.filter_log] == [SkipReason.unverified_quote] and r.unsupported


def test_no_fixed_selection_ratio_many_relevant_all_kept_none_padded(tmp_path):
    many = [f"A Tool{i} eszköz kezeli az ablakokat és a felugró menüket." for i in range(30)]
    store, s, pipe = build(tmp_path, [vid(U1, "Sok", many)], ExtractiveBaselineLLM(), semantic=False)
    jid, r = run(store, s, pipe, [U1])
    assert len([f for f in r.findings if f.disposition == Disposition.keep]) == 30               # nincs felső korlát (nem 1–2%)


def test_empty_when_nothing_matches_extractive(tmp_path):
    store, s, pipe = build(tmp_path, [vid(U2, "Semmi", ["Szia mindenkinek", "Viszlát jövő héten", "Ez egy teljesen más téma a főzésről."])], ExtractiveBaselineLLM(), semantic=False)
    jid, r = run(store, s, pipe, [U2])
    assert r.findings == [] and r.no_result_note == NO_RESULT and store.get_job(jid).status == JobStatus.completed


def test_repeat_attaches_new_source_but_variants_stay_separate(tmp_path):
    a = ["Az AutoDroid root nélkül kezeli az ablakokat.", "Az AutoDroid csak Android 12-n működik jól.", "A ClickBot gyors, de csak Android 14-n megy."]
    b = ["Az AutoDroid root nélkül kezeli az ablakokat is.", "Az AutoDroid Android 14-n már nem működik jól.", "Az AutoDroid root nélkül kezeli az ablakokat, de csak ha a kisegítő mód be van kapcsolva."]
    llm = Cand({U1: [(0, {**D}), (1, {**D, "version": "Android 12"}), (2, {**D})],
                U2: [(0, {**D}), (1, {**D, "version": "Android 14", "stance": "counterexample"}), (2, {**D, "condition": "kisegítő mód bekapcsolva"})]})
    store, s, pipe = build(tmp_path, [vid(U1, "A", a), vid(U2, "B", b)], llm)
    jid, r = run(store, s, pipe, [U1, U2])
    root = [f for f in r.findings if f.statement_hu.startswith("Az AutoDroid root nélkül") and f.condition is None]
    assert len(root) == 1 and len({x.video_source_id for x in root[0].source_references}) == 2          # új forrás a meglévőhöz csatolva
    assert root[0].evidence_status.value == "repeated_across_sources"
    assert any(e.reason_code == SkipReason.duplicate_source_attached and e.finding_id == root[0].id for e in r.filter_log)
    by_ver = {f.version: f for f in r.findings if f.version}
    assert set(by_ver) == {"Android 12", "Android 14"} and by_ver["Android 14"].stance.value == "counterexample"   # verzió/ellenpélda külön
    assert by_ver["Android 14"].id in by_ver["Android 12"].related_ids or by_ver["Android 12"].id in by_ver["Android 14"].related_ids
    cond = [f for f in r.findings if f.condition]
    assert len(cond) == 1  and cond[0].id != root[0].id                  # feltétel nem olvad be


def test_known_information_is_not_repeated_but_logged(tmp_path):
    llm = Cand({U1: [(1, {**D}), (3, {**D})]})
    store, s, pipe = build(tmp_path, [vid(U1, "V", T1)], llm)
    jid, r = run(store, s, pipe, [U1], known=["Az AutoDroid eszköz root nélkül kezeli a felugró ablakokat."])
    assert all("AutoDroid" not in f.statement_hu for f in r.findings)
    assert any(e.reason_code == SkipReason.already_known for e in r.filter_log)
    assert json.loads(store.get_field(jid, "plan"))["known_information"]


def test_short_report_vs_evidence_and_filter_log_views(tmp_path):
    llm = Cand({U1: [(1, {**D}), (0, {"relevance": "none"}), (3, {"relevance": "partial"})]})
    store, s, pipe = build(tmp_path, [vid(U1, "V", T1)], llm)
    s.api_token = SecretStr("t" * 20)
    c = TestClient(create_app(store, s, pipe.registry))
    jid, r = run(store, s, pipe, [U1])
    short = c.get(f"/api/jobs/{jid}/report?format=markdown", headers=H).text
    for h in ("## Megtartandó információk", "## Ellenőrizendő nyomok", "## Kihagyott részletek"):
        assert h in short                                                         # a három csoport
    assert "„" not in short                                                       # idézetek csak a bizonyítéknézetben
    ev = c.get(f"/api/jobs/{jid}/evidence?format=markdown", headers=H).text
    assert "„Az AutoDroid eszköz root nélkül" in ev and "nem bizonyítja az állítás igazságát" in ev
    fl = c.get(f"/api/jobs/{jid}/filter-log", headers=H).json()
    assert fl["stats"]["skipped_by_reason"] == {"irrelevant": 1} and fl["entries"][0]["reason_hu"]
    sj = c.get(f"/api/jobs/{jid}/report", headers=H).json()
    assert len(sj["keep"]) == 1 and len(sj["leads"]) == 1 and "quote" not in json.dumps(sj)
    assert len(short) < len(ev) + len(c.get(f"/api/jobs/{jid}/filter-log?format=markdown", headers=H).text)


def test_feedback_stored_shown_not_destructive_and_no_learning(tmp_path):
    llm = Cand({U1: [(1, {**D}), (3, {"relevance": "partial"})]})
    store, s, pipe = build(tmp_path, [vid(U1, "V", T1)], llm)
    s.api_token = SecretStr("t" * 20)
    c = TestClient(create_app(store, s, pipe.registry))
    jid, r = run(store, s, pipe, [U1])
    fid = r.findings[0].id
    assert c.post(f"/api/jobs/{jid}/findings/{fid}/feedback", json={"label": "igaz"}, headers=H).status_code == 422
    assert c.post(f"/api/jobs/{jid}/findings/nincs/feedback", json={"label": "useful"}, headers=H).status_code == 404
    for lab in ("useful", "already_known"):
        assert c.post(f"/api/jobs/{jid}/findings/{fid}/feedback", json={"label": lab, "note": "megjegyzés"}, headers=H).status_code == 201
    fbs = c.get(f"/api/jobs/{jid}/feedback", headers=H).json()
    assert [x["label"] for x in fbs] == ["useful", "already_known"]                # a történet megmarad
    md = c.get(f"/api/jobs/{jid}/report?format=markdown", headers=H).text
    assert "visszajelzés: már ismert" in md and r.findings[0].statement_hu in md   # a „már ismert” nem rejti el, és nem hamis/értéktelen
    after = ResearchReport.model_validate_json(store.get_field(jid, "report"))
    assert [f.model_dump() for f in after.findings] == [f.model_dump() for f in r.findings]       # a visszajelzés nem írja át a megállapításokat
    # új feladat ugyanazzal a bemenettel: a korábbi visszajelzés nem változtat a kinyerésen (nincs önfejlesztés)
    store2, s2, pipe2 = build(tmp_path, [vid(U1, "V", T1)], Cand({U1: [(1, {**D}), (3, {"relevance": "partial"})]}))
    jid2, r2 = run(store2, s2, pipe2, [U1])
    assert [f.statement_hu for f in r2.findings] == [f.statement_hu for f in r.findings]
