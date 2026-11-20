"""A kiértékelő: a csővezeték valódi kódján fut (felhasználói átiratimport -> terv -> jóváhagyás -> kinyerés -> idézetellenőrzés -> jelentés),
a modell helyén a forgatókönyves hamisítóval, majd összeveti a kimenetet a kézzel megadott elvárással."""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

from ..adapters.base import AdapterRegistry
from ..config import Settings
from ..db import Store, make_engine, migrate
from ..extractive import ExtractiveBaselineLLM
from ..extraction import _norm
from ..importer import import_job
from ..llm import LLMResult
from ..models import Disposition, JobStatus, Limits, ResearchReport
from ..pipeline import Pipeline
from ..report import evidence_markdown, filter_log_markdown, to_markdown
from ..worker import Worker
from .cases import CASES


class Scripted:
    """Forgatókönyves hamisító modell: a megadott szegmens-indexekhez a prompt szegmensszövegéből szó szerinti idézetet ad."""
    provider, model, kind = "scripted-fake", "scripted", "ai"

    def __init__(self, items):
        self.items, self.prompts = items, []

    def complete_json(self, *, system, user, schema_name, max_tokens):
        self.prompts.append((schema_name, user))
        if schema_name == "semantic":
            return LLMResult({"verdict": "consistent"}, 1)
        block = user.split("<untrusted_transcript>")[1].split("</untrusted_transcript>")[0].strip().splitlines()
        segs = {}
        for line in block:
            sid, text = line[1:].split("] ", 1)
            segs[int(sid.rsplit(":s", 1)[1])] = (sid, text)
        out = []
        for it in self.items:
            it = dict(it)
            sid, text = segs[it.pop("seg")]
            out.append({"quotes": [{"segment_id": sid, "quote": text}], **it})
        return LLMResult({"findings": out}, 50)


def to_srt(segs):
    def ts(x):
        return f"00:{int(x // 60):02d}:{int(x % 60):02d},000"
    return "\n\n".join(f"{i + 1}\n{ts(i * 6)} --> {ts(i * 6 + 5)}\n{t}" for i, t in enumerate(segs)) + "\n"


def run_case(case: dict, llm=None, tmp: Path | None = None) -> dict:
    tmp = tmp or Path(tempfile.mkdtemp())
    engine = make_engine(f"sqlite:///{tmp / (case['id'] + '.db')}")
    migrate(engine)
    store, settings = Store(engine), Settings(limits=Limits())
    llm = llm or Scripted(case["model"])
    pipe = Pipeline(store, settings, AdapterRegistry(production=False), llm, sleep=lambda _x: None, poll_interval=0, semantic=getattr(llm, "kind", "") == "ai")
    text = to_srt(case["segments"]) if case["fmt"] == "srt" else "\n".join(case["segments"])
    jid, _ = import_job(store, settings, question=case["question"], transcript_text=text, fmt=case["fmt"], language=case["lang"], title="Teszt átirat", video_url=None)
    w = Worker(store, pipe, settings, name="acc")
    w.run_once()
    store.set_status(jid, JobStatus.queued, approved_plan=store.get_field(jid, "plan"))
    w.run_once()
    job = store.get_job(jid)
    r = ResearchReport.model_validate_json(store.get_field(jid, "report"))
    return {"job": job, "report": r, "llm": llm, "store": store, "jid": jid}


def _seg(f) -> int:
    return int(f.source_references[0].transcript_segment_ids[0].rsplit(":s", 1)[1])


def evaluate(case: dict, res: dict) -> dict:
    g, r = case["gold"], res["report"]
    segs = case["segments"]
    out_items = [(_seg(f), f) for f in r.findings]
    expected = [(e, "keep") for e in g["keep"]] + [(e, "lead") for e in g["lead"]]
    missed, wrong_bucket, quote_bad, lost_limits, matched = [], [], [], [], []
    used = set()
    for e, bucket in expected:
        cand = [(i, f) for i, (s, f) in enumerate(out_items) if s == e["seg"] and f.category.value == e["kind"] and i not in used]
        if not cand:
            missed.append(f"szegmens {e['seg']} ({e['kind']})")
            continue
        i, f = cand[0]
        used.add(i)
        matched.append(f)
        if f.disposition.value != bucket:
            wrong_bucket.append(f"szegmens {e['seg']}: {f.disposition.value} helyett {bucket} lett volna az elvárás")
        if _norm(f.source_references[0].supporting_quote) != _norm(segs[e["seg"]]):
            quote_bad.append(f"szegmens {e['seg']}: az idézet nem a teljes elvárt szegmens")
        st = f.statement_hu.casefold()
        for group in e["must"]:
            if not any(w.casefold() in st for w in group):
                lost_limits.append(f"szegmens {e['seg']}: a magyar állításból hiányzik: {' / '.join(group)}")
    extra = [f"szegmens {s} ({f.category.value}, {f.disposition.value}): {f.statement_hu[:70]}" for i, (s, f) in enumerate(out_items)
             if i not in used and s not in g["optional"]]
    absent_present = [s for s, _ in out_items if s in g["absent"]]
    checks = {
        "missed": missed, "wrongly_included": extra + [f"kizárt szegmens {s} bekerült" for s in absent_present], "wrong_bucket": wrong_bucket,
        "quote_bad": quote_bad, "limitation_lost": lost_limits,
        "status": [] if res["job"].status.value == g["status"] else [f"státusz {res['job'].status.value} (elvárt: {g['status']})"],
        "no_result": [] if bool(r.no_result_note) == g["no_result"] else [f"no_result_note={bool(r.no_result_note)} (elvárt: {g['no_result']})"],
    }
    if g.get("timestamps_null"):
        checks["timestamp"] = [f"szegmens {s}: időbélyeg {f.source_references[0].timestamp}" for s, f in out_items if f.source_references[0].timestamp is not None]
    if g.get("contradictions") is not None:
        checks["contradictions"] = [] if len(r.contradictions) == g["contradictions"] else [f"{len(r.contradictions)} ellentmondás-jelzés (elvárt: {g['contradictions']})"]
    if g.get("injection_skipped"):
        checks["injection"] = [] if any(e.reason_code.value == "suspected_injection" for e in r.filter_log) else ["nincs suspected_injection naplóbejegyzés"]
        checks["no_model_override"] = [f"verification_status={f.verification_status}" for _, f in out_items if f.verification_status != "not_externally_verified"]
    if r.analysis_method == "ai_semantic":
        checks["verification"] = [f"{f.id}: verification_status={f.verification_status}" for f in r.findings if f.verification_status != "not_externally_verified"]
    return checks


def render(case: dict, res: dict, checks: dict) -> str:
    r, job = res["report"], res["job"]
    lines = [f"### {case['id']} — {case['title']}", "", f"**Kérdés:** {case['question']}", f"**Átirat ({case['lang']}, {case['fmt']}):**"]
    lines += [f"  {i}. {t}" for i, t in enumerate(case["segments"]) if len(case["segments"]) <= 10 or i in (0, 13, 14)] + (["  … (további töltelék szegmensek elhagyva a kijelzésből)"] if len(case["segments"]) > 10 else [])
    lines += ["", f"**Kimenet** (állapot: {job.status.value}, elemzés: {r.analysis_method}):"]
    if not r.findings:
        lines.append(f"  - (nincs megtartott tétel) {r.no_result_note or ''}")
    for f in r.findings:
        ref = f.source_references[0]
        lines.append(f"  - [{f.report_bucket}/{f.category.value}] {f.statement_hu}")
        lines.append(f"      idézet [{ref.quote_language}] „{ref.supporting_quote}” · időbélyeg: {ref.timestamp} · szegm.: {ref.transcript_segment_ids[0].rsplit(':', 1)[1]}")
        lines.append(f"      source_support_status={f.source_support_status} · verification_status={f.verification_status} · stance={f.stance.value} · indok: {f.classification_reason}")
    if r.filter_log:
        lines.append("  Szűrési napló: " + "; ".join(f"[{e.reason_code.value}] „{e.snippet[:50]}”" for e in r.filter_log))
    if r.contradictions:
        lines.append("  Ellentmondás-jelzés: " + "; ".join(c["note"] for c in r.contradictions))
    bad = {k: v for k, v in checks.items() if v}
    lines += ["", "**Kiértékelés (kézi elvárás ellen):** " + ("MINDEN ELVÁRÁS TELJESÜLT" if not bad else "ELTÉRÉS: " + "; ".join(f"{k}: {v}" for k, v in bad.items())), ""]
    return "\n".join(lines)


def run_all() -> list[tuple[dict, dict, dict]]:
    tmp = Path(tempfile.mkdtemp())
    results = []
    for case in CASES:
        res = run_case(case, tmp=tmp)
        results.append((case, res, evaluate(case, res)))
    return results


def baseline_cross_language() -> tuple[str, dict]:
    """A kulcsszavas baseline ugyanazon az A esetben (magyar kérdés, angol átirat), a kézi elvárás ellen kiértékelve. A számokat a futás adja, nem előre írt állítás."""
    case = next(c for c in CASES if c["id"] == "A_tools")
    res = run_case(case, llm=ExtractiveBaselineLLM())
    checks = evaluate(case, res)
    r = res["report"]
    found = "; ".join(f"szegm. {_seg(f)} [{f.report_bucket}] „{f.source_references[0].supporting_quote[:60]}”" for f in r.findings) or "nincs"
    txt = (f"Baseline (kulcsszavas, **NEM AI**; analysis_method={r.analysis_method}) az A esetre. Talált: {found}.\n"
           f"Kihagyott elvárt tételek: {checks['missed'] or 'nincs'}. Tévesen bekerült: {checks['wrongly_included'] or 'nincs'}. "
           "A baseline csak a közös szavakon (itt: „Android”) talál, a kérdés jelentését nem érti; a magyar kérdés–angol átirat szemantikai kezeléséhez modell kell.")
    return txt, checks


def main(argv: list[str]) -> int:
    if "--live" in argv:
        from .live import main_live
        return main_live(argv)
    out = ["# Elfogadási próbák (forgatókönyves hamisító modellel; NEM valódi modellminőség)", ""]
    for case, res, checks in run_all():
        out.append(render(case, res, checks))
    out += ["### Baseline összevetés", "", baseline_cross_language()[0], ""]
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
