"""Magyar nyelvű jelentés és strukturált export. A jelentés csak tárolt, ellenőrzött adatból áll; semmi sem pótolódik modellből."""
from __future__ import annotations

import csv
import io
import json

from .models import AccessStatus, EvidenceStatus, Finding, ResearchJob, ResearchPlan, ResearchReport, Transcript, VideoSource

STATUS_HU = {
    EvidenceStatus.creator_claim: "a videó készítőjének állítása",
    EvidenceStatus.repeated_across_videos: "több videóban megismételt állítás (nem független ellenőrzés)",
    EvidenceStatus.independently_verified: "független forrással ellenőrzött",
}


def fmt_ts(t: float | None) -> str:
    if t is None:
        return "időbélyeg nem ismert"
    m, s = divmod(int(t), 60)
    return f"{m}:{s:02d}"


def build_report(job: ResearchJob, plan: ResearchPlan, videos: list[VideoSource], findings: list[Finding], transcripts: list[Transcript],
                 problems: list[str], stats, *, rejected: int, provider_runs: list[dict], stop_reason: str | None) -> ResearchReport:
    vmap = {v.id: v for v in videos}
    tmap = {t.video_source_id: t for t in transcripts}
    limits: list[str] = []
    if any(v.is_fixture for v in videos):
        limits.append("FIGYELEM: TESZT-FIXTURE adatok szerepelnek a jelentésben, nem valódi videók.")
    limits.append("A rendszer külső (független forrásos) ellenőrzést nem végzett: az állítások a videók tartalmát tükrözik, nem igazolt tények.")
    limits.append("Ellentmondás-észlelés ebben a verzióban nem történik; a `contradictions` mező üres, ez NEM jelenti, hogy nincs ellentmondás.")
    limits.append("Az idézetek programozottan ellenőrzöttek az átiratban; az állítás és az idézet jelentésbeli kapcsolatának ellenőrzése heurisztikus, nem tévedhetetlen.")
    if rejected:
        limits.append(f"{rejected} javasolt megállapítás kimaradt, mert az idézete nem volt ellenőrizhető az átiratban.")
    unknown = [r for r in provider_runs if not r["cost_known"]]
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
    repeated = [{"statement": f.statement, "video_count": len({r.video_source_id for r in f.source_references}), "finding_id": f.id}
                for f in findings if f.evidence_status == EvidenceStatus.repeated_across_videos]
    sources = [{"video_source_id": v.id, "platform": v.platform.value, "url": v.canonical_url, "title": v.title, "creator": v.creator,
                "provider": v.provider, "provider_run_id": v.provider_run_id, "access_status": v.access_status.value,
                "transcript_origin": tmap[v.id].origin.value if v.id in tmap else None, "fixture": v.is_fixture} for v in videos]
    summary = (f"{len(videos)} videó azonosítva, ebből {len(tmap)} átirattal; {len(findings)} megállapítás, ebből {len(repeated)} több videóban is szerepel. "
               f"Kutatási kérdés: {plan.question}")
    return ResearchReport(summary=summary, findings=findings, repeated_mentions=repeated, contradictions=[], missing_information=missing,
                          source_list=sources, coverage_limitations=limits)


def to_markdown(r: ResearchReport, job: ResearchJob) -> str:
    out = [f"# Kutatási jelentés", "", f"**Kérdés:** {job.request}", "", f"**Állapot:** {job.status.value} · Rögzített szolgáltatói költség: {job.recorded_cost:.4f} USD "
           f"(csak a ténylegesen ismert költség)", "", "## Összefoglaló", r.summary, ""]
    if r.coverage_limitations and any("FIXTURE" in l for l in r.coverage_limitations):
        out = out[:1] + ["", "> **⚠ TESZT-FIXTURE adatok, nem valódi videók.**"] + out[1:]
    cats: dict[str, list[Finding]] = {}
    for f in r.findings:
        cats.setdefault(f.category, []).append(f)
    out.append("## Megállapítások")
    for cat, fs in cats.items():
        out += ["", f"### {cat}"]
        for f in fs:
            out.append(f"- **{f.statement}** — _{STATUS_HU[f.evidence_status]}_")
            for ref in f.source_references:
                src = next((s for s in r.source_list if s["video_source_id"] == ref.video_source_id), {})
                out.append(f"  - „{ref.supporting_quote}” — {src.get('title') or src.get('url')} ({src.get('platform')}, {fmt_ts(ref.timestamp)}) {src.get('url', '')} [jelentés-ellenőrzés: {ref.semantic_check}]")
            for l in f.limitations:
                out.append(f"  - _Korlát:_ {l}")
    if not r.findings:
        out.append("\nNincs forrással alátámasztott megállapítás.")
    out += ["", "## Több videóban említett (nem független igazolás)"] + [f"- {m['statement']} ({m['video_count']} videó)" for m in r.repeated_mentions] if r.repeated_mentions else []
    out += ["", "## Hiányzó információ"] + [f"- {m}" for m in r.missing_information] if r.missing_information else []
    out += ["", "## Források"] + [f"- {s['title'] or s['url']} — {s['platform']} — {s['url']} (szolgáltató: {s['provider']}, átirat: {s['transcript_origin'] or 'nincs'})" for s in r.source_list]
    out += ["", "## Lefedettségi korlátok"] + [f"- {l}" for l in r.coverage_limitations]
    return "\n".join(out) + "\n"


def to_csv(r: ResearchReport) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["finding_id", "category", "statement", "evidence_status", "video_url", "timestamp_seconds", "quote", "semantic_check"])
    urls = {s["video_source_id"]: s["url"] for s in r.source_list}
    for f in r.findings:
        for ref in f.source_references:
            w.writerow([f.id, f.category, f.statement, f.evidence_status.value, urls.get(ref.video_source_id, ""), ref.timestamp if ref.timestamp is not None else "",
                        ref.supporting_quote, ref.semantic_check])
    return buf.getvalue()


def to_json(r: ResearchReport) -> str:
    return json.dumps(r.model_dump(mode="json"), ensure_ascii=False, indent=2)
