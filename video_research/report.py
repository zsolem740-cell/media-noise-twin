"""Magyar nyelvű jelentés és strukturált export. A jelentés csak tárolt, ellenőrzött adatból áll; semmi sem pótolódik modellből."""
from __future__ import annotations

import csv
import io
import json

from .models import (AccessStatus, Disposition, EvidenceStatus, FilterEntry, Finding, ResearchJob, ResearchPlan, ResearchReport, SkipReason,
                     Transcript, VideoSource)

STATUS_HU = {
    EvidenceStatus.source_claim: "a videó készítőjének állítása (nem ellenőrzött)",
    EvidenceStatus.repeated_across_sources: "több videóban megismételt állítás (nem független ellenőrzés)",
    EvidenceStatus.unsupported: "nem alátámasztott",
}


def fmt_ts(t: float | None) -> str:
    if t is None:
        return "időbélyeg nem ismert"
    m, s = divmod(int(t), 60)
    return f"{m}:{s:02d}"


NO_RESULT = "Nem találtam a feltételeknek megfelelő információt."
REASON_HU = {"irrelevant": "nem releváns", "not_concrete": "nem elég konkrét", "unverified_quote": "nem ellenőrizhető idézet (nem alátámasztott)",
             "already_known": "már rögzített információ", "duplicate_source_attached": "ismétlés, új forrás csatolva", "malformed": "hibás javaslat"}
FB_HU = {"useful": "hasznos", "not_relevant": "nem releváns", "already_known": "már ismert", "extracted_wrong": "hibásan kinyert", "needs_check": "további ellenőrzést igényel"}


def build_report(job: ResearchJob, plan: ResearchPlan, videos: list[VideoSource], findings: list[Finding], transcripts: list[Transcript],
                 problems: list[str], stats, *, provider_runs: list[dict], stop_reason: str | None, filter_log: list[FilterEntry],
                 segments_total: int, videos_processed: int) -> ResearchReport:
    tmap = {t.video_source_id: t for t in transcripts}
    limits: list[str] = []
    if any(v.is_fixture for v in videos):
        limits.append("FIGYELEM: TESZT-FIXTURE adatok szerepelnek a jelentésben, nem valódi videók.")
    limits.append("A rendszer külső (független forrásos) ellenőrzést nem végzett: az állítások a videók tartalmát tükrözik, nem igazolt tények.")
    limits.append("Ellentmondás-észlelés ebben a verzióban nem történik; a `contradictions` mező üres, ez NEM jelenti, hogy nincs ellentmondás.")
    limits.append("Vizuális elemzés ebben a verzióban nincs: a csak képen látható információkat (felirat a képen, kijelzők, ábrák) a rendszer nem vizsgálja.")
    limits.append("Az idézetek programozottan ellenőrzöttek az átiratban; ez nem bizonyítja az állítás igazságát. Az állítás és az idézet jelentésbeli kapcsolatának ellenőrzése heurisztikus, nem tévedhetetlen.")
    unsup = [e for e in filter_log if e.reason_code == SkipReason.unverified_quote]
    if unsup:
        limits.append(f"{len(unsup)} javasolt megállapítás kimaradt (unsupported), mert az idézete nem volt ellenőrizhető az átiratban.")
    if any(t.auto_generated for t in transcripts):
        limits.append("Egyes átiratok a platform automatikus (gépi) feliratai, elírásokat tartalmazhatnak.")
    if any(v.duration_seconds is None for v in videos):
        limits.append("Egyes videók hossza ismeretlen, ezért a videóperc-keret rájuk nem érvényesíthető.")
    unknown = [r for r in provider_runs if not r["cost_known"] and r["status"] in ("succeeded", "running", "abort_requested", "aborted")]
    if unknown:
        limits.append(f"{len(unknown)} szolgáltatói futás költsége nem ismert; a rögzített költség alsó becslés.")
    if stop_reason:
        limits.append({"cancelled": "A feladatot megszakították; a részeredmények megmaradtak.", "runtime_limit": "A futásidő-keret lejárt; részeredmény.",
                       "cost_budget": "A szolgáltatói költségkeret kimerült; részeredmény.", "unavailable": "Szolgáltatás nem volt elérhető; részeredmény."}.get(stop_reason, stop_reason))
    limits += problems
    missing = []
    for v in videos:
        if v.access_status == AccessStatus.no_transcript:
            missing.append(f"Nincs hozzáférhető átirat: {v.canonical_url}")
        elif v.access_status != AccessStatus.ok:
            missing.append(f"Nem feldolgozható ({v.access_status.value}): {v.canonical_url}")
        elif v.id not in tmap:
            missing.append(f"Átirat nem készült el: {v.canonical_url}")
    keep = [f for f in findings if f.disposition == Disposition.keep]
    leads = [f for f in findings if f.disposition == Disposition.lead]
    repeated = [{"statement": f.statement_hu, "video_count": len({r.video_source_id for r in f.source_references}), "finding_id": f.id}
                for f in findings if f.evidence_status == EvidenceStatus.repeated_across_sources]
    sources = [{"video_source_id": v.id, "platform": v.platform.value, "url": v.canonical_url, "title": v.title, "creator": v.creator,
                "provider": v.provider, "provider_run_id": v.provider_run_id, "access_status": v.access_status.value,
                "transcript_origin": tmap[v.id].origin.value if v.id in tmap else None, "transcript_language": tmap[v.id].language if v.id in tmap else None,
                "auto_generated": tmap[v.id].auto_generated if v.id in tmap else None, "fixture": v.is_fixture} for v in videos]
    by_reason: dict[str, int] = {}
    for e in filter_log:
        by_reason[e.reason_code.value] = by_reason.get(e.reason_code.value, 0) + 1
    # nincs rögzített kiválasztási arány: a számok csak leírják, mi történt
    stats_d = {"videos_total": len(videos), "videos_processed": videos_processed, "segments_total": segments_total,
               "kept": len(keep), "leads": len(leads), "skipped_by_reason": by_reason}
    no_result = NO_RESULT if videos_processed > 0 and not findings else None
    summary = (f"{videos_processed} videó feldolgozva ({len(videos)} azonosított): {len(keep)} megtartandó információ, {len(leads)} ellenőrizendő nyom, "
               f"{sum(by_reason.values())} kihagyott/ismétlésként csatolt részlet. Kérdés: {plan.question.splitlines()[0]}")
    return ResearchReport(summary=summary, findings=findings, repeated_mentions=repeated, contradictions=[], missing_information=missing,
                          source_list=sources, coverage_limitations=limits, no_result_note=no_result, filter_log=filter_log, filter_stats=stats_d,
                          unsupported=[{"statement_hu": e.snippet, "reason": e.reason_hu} for e in unsup])


def _src(r: ResearchReport, vid: str) -> dict:
    return next((s for s in r.source_list if s["video_source_id"] == vid), {})


def _ref_line(r: ResearchReport, ref) -> str:
    src = _src(r, ref.video_source_id)
    return f"{src.get('title') or src.get('url')} ({src.get('platform')}, {fmt_ts(ref.timestamp)}) {src.get('url', '')}"


def latest_feedback(feedback: list[dict] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in feedback or []:
        out[f["finding_id"]] = f["label"]            # időrendben: az utolsó jelölés érvényes, a korábbiak megmaradnak az adatbázisban
    return out


def _fb(fb: dict[str, str], fid: str) -> str:
    return f" · visszajelzés: {FB_HU[fb[fid]]}" if fid in fb else ""


def to_markdown(r: ResearchReport, job: ResearchJob, feedback: list[dict] | None = None) -> str:
    """RÖVID fő jelentés. A teljes bizonyíték és a szűrési napló külön nézet (evidence, filter-log)."""
    fb = latest_feedback(feedback)
    out = ["# Kutatási jelentés", ""]
    if any("FIXTURE" in l for l in r.coverage_limitations):
        out += ["> **⚠ TESZT-FIXTURE adatok, nem valódi videók.**", ""]
    out += [f"**Kérdés:** {job.request.splitlines()[0]}", "", f"**Állapot:** {job.status.value} · {r.summary.split(' Kérdés:')[0]}", ""]
    if r.no_result_note:
        out += [f"**{r.no_result_note}**", ""]
    keep = [f for f in r.findings if f.disposition == Disposition.keep]
    leads = [f for f in r.findings if f.disposition == Disposition.lead]
    if keep:
        out.append("## Megtartandó információk")
        for f in keep:
            ref = f.source_references[0]
            extra = " · ".join(x for x in [f"feltétel: {f.condition}" if f.condition else "", f"verzió: {f.version}" if f.version else "",
                                           "ellenpélda" if f.stance.value == "counterexample" else ""] if x)
            out.append(f"- **{f.statement_hu}** [{f.category.value}] — _{STATUS_HU[f.evidence_status]}_{(' · ' + extra) if extra else ''}{_fb(fb, f.id)}")
            out.append(f"  - forrás: {_ref_line(r, ref)}" + (f" (+{len(f.source_references) - 1} további forrás)" if len(f.source_references) > 1 else "") + f" · azonosító: {f.id}")
        out.append("")
    if leads:
        out.append("## Ellenőrizendő nyomok")
        for f in leads:
            out.append(f"- **{f.statement_hu}** [{f.category.value}] — ok: {'; '.join(f.lead_reasons) or 'ellenőrzés javasolt'}{_fb(fb, f.id)}")
            out.append(f"  - forrás: {_ref_line(r, f.source_references[0])} · azonosító: {f.id}")
        out.append("")
    sk = r.filter_stats.get("skipped_by_reason", {})
    out.append("## Kihagyott részletek")
    out.append("Nincs kihagyott jelölt." if not sk else "; ".join(f"{REASON_HU.get(k, k)}: {v}" for k, v in sk.items()) +
               f". Szegmensek az átiratokban: {r.filter_stats.get('segments_total', 0)} (a javaslatba sem került szegmenseket nem naplózzuk egyenként). Részletek: a szűrési napló.")
    out.append("")
    if r.missing_information:
        out += ["## Hiányok"] + [f"- {m}" for m in r.missing_information] + [""]
    key = [l for l in r.coverage_limitations if l.startswith(("FIGYELEM", "A rendszer külső", "Vizuális", "A feladatot", "A futásidő", "A szolgáltatói költségkeret", "Szolgáltatás nem"))]
    out += ["## Fő korlátok"] + [f"- {l}" for l in key] + ["- Teljes bizonyíték (idézetek, szegmensek, időbélyegek) és szűrési napló: külön nézet.", ""]
    return "\n".join(out)


def evidence_markdown(r: ResearchReport, job: ResearchJob, feedback: list[dict] | None = None) -> str:
    fb = latest_feedback(feedback)
    out = ["# Részletes bizonyítékok", ""]
    for f in r.findings:
        out.append(f"## {f.statement_hu}")
        out.append(f"- azonosító: {f.id} · kategória: {f.category.value} · besorolás: {f.disposition.value} · relevancia: {f.relevance.value} · konkrét: {f.concrete}"
                   f" · alátámasztottság: {f.evidence_status.value}{_fb(fb, f.id)}")
        if f.condition or f.version or f.stance.value != "supports":
            out.append(f"- feltétel: {f.condition or '–'} · verzió: {f.version or '–'} · álláspont: {f.stance.value}")
        if f.lead_reasons:
            out.append(f"- ellenőrzendő, mert: {'; '.join(f.lead_reasons)}")
        for ref in f.source_references:
            out.append(f"- „{ref.supporting_quote}” — {_ref_line(r, ref)}; szegmensek: {', '.join(ref.transcript_segment_ids)}; jelentés-ellenőrzés: {ref.semantic_check} (az idézet megléte nem bizonyítja az állítás igazságát)")
        out += [f"- korlát: {l}" for l in f.limitations]
        if f.related_ids:
            out.append(f"- kapcsolódó (eltérő feltétel/verzió/ellenpélda): {', '.join(f.related_ids)}")
        out.append("")
    if not r.findings:
        out.append(r.no_result_note or "Nincs megtartott megállapítás.")
    out += ["## Teljes korlátlista"] + [f"- {l}" for l in r.coverage_limitations]
    return "\n".join(out) + "\n"


def filter_log_markdown(r: ResearchReport) -> str:
    out = ["# Szűrési napló", "", f"Videók: {r.filter_stats.get('videos_processed', 0)}/{r.filter_stats.get('videos_total', 0)} feldolgozva · szegmensek: {r.filter_stats.get('segments_total', 0)} · "
           "nincs rögzített kiválasztási arány vagy kvóta; csak a javaslatba került jelöltek kapnak sort.", ""]
    for e in r.filter_log:
        src = _src(r, e.video_source_id)
        out.append(f"- [{REASON_HU.get(e.reason_code.value, e.reason_code.value)}] „{e.snippet}” — {e.reason_hu} ({src.get('url', '')}{'; szegm.: ' + ', '.join(e.segment_ids) if e.segment_ids else ''})"
                   + (f" → megállapítás: {e.finding_id}" if e.finding_id else ""))
    if not r.filter_log:
        out.append("Nincs bejegyzés.")
    return "\n".join(out) + "\n"


def short_json(r: ResearchReport, feedback: list[dict] | None = None) -> dict:
    fb = latest_feedback(feedback)

    def item(f: Finding) -> dict:
        return {"id": f.id, "category": f.category.value, "statement_hu": f.statement_hu, "evidence_status": f.evidence_status.value,
                "condition": f.condition, "version": f.version, "stance": f.stance.value, "lead_reasons": f.lead_reasons, "feedback": fb.get(f.id),
                "sources": [{"url": _src(r, x.video_source_id).get("url"), "title": _src(r, x.video_source_id).get("title"), "timestamp": x.timestamp} for x in f.source_references]}
    return {"summary": r.summary, "no_result_note": r.no_result_note,
            "keep": [item(f) for f in r.findings if f.disposition == Disposition.keep],
            "leads": [item(f) for f in r.findings if f.disposition == Disposition.lead],
            "skipped_by_reason": r.filter_stats.get("skipped_by_reason", {}), "missing_information": r.missing_information}


def to_csv(r: ResearchReport) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["finding_id", "category", "statement", "disposition", "relevance", "evidence_status", "video_url", "timestamp_seconds", "quote", "semantic_check"])
    urls = {s["video_source_id"]: s["url"] for s in r.source_list}
    for f in r.findings:
        for ref in f.source_references:
            w.writerow([f.id, f.category.value, f.statement_hu, f.disposition.value, f.relevance.value, f.evidence_status.value, urls.get(ref.video_source_id, ""), ref.timestamp if ref.timestamp is not None else "",
                        ref.supporting_quote, ref.semantic_check])
    return buf.getvalue()


def to_json(r: ResearchReport) -> str:
    return json.dumps(r.model_dump(mode="json"), ensure_ascii=False, indent=2)
