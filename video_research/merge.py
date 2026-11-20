"""Összevonás: az ismétlés új FORRÁSA a meglévő megállapításhoz csatolódik (minden hivatkozás megmarad), de az eltérő feltétel, ellenpélda, verzió
vagy szám nem olvad bele az általános állításba: külön megállapítás marad, `related_ids`-kel összekötve.
Több ismétlés önmagában NEM igazolás; verified állapot nincs: külső ellenőrzést az 1. verzió nem végez."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .extraction import _norm
from .models import Disposition, EvidenceStatus, FilterEntry, Finding, SkipReason, VideoSource

_STOP = {"és", "a", "az", "hogy", "is", "egy", "van", "nem", "the", "and", "of", "to", "in", "is", "a", "for", "with"}
_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def _tokens(s: str) -> set[str]:
    return {t for t in _norm(s).split() if t not in _STOP and len(t) > 2}


def similar(a: str, b: str, threshold: float = 0.6) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    jac = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    return jac >= threshold or SequenceMatcher(None, _norm(a), _norm(b)).ratio() >= 0.8


def _key(v: str | None) -> str:
    return _norm(v or "")


def same_claim(a: Finding, b: Finding) -> bool:
    """Ugyanaz az állítás, ugyanazzal a feltétellel, állásponttal, verzióval és számokkal."""
    if a.category != b.category or not similar(a.statement_hu, b.statement_hu):
        return False
    if a.stance != b.stance or _key(a.condition) != _key(b.condition) or _key(a.version) != _key(b.version):
        return False
    na, nb = set(_NUM.findall(a.statement_hu)), set(_NUM.findall(b.statement_hu))
    return na == nb


def merge_findings(findings: list[Finding], videos: dict[str, VideoSource]) -> tuple[list[Finding], list[FilterEntry]]:
    clusters: list[Finding] = []
    log: list[FilterEntry] = []
    for f in findings:
        f = f.model_copy(deep=True)
        for c in clusters:
            if same_claim(c, f):
                seen = {(r.video_source_id, tuple(r.transcript_segment_ids), r.supporting_quote) for r in c.source_references}
                attached = False
                for r in f.source_references:
                    k = (r.video_source_id, tuple(r.transcript_segment_ids), r.supporting_quote)
                    if k not in seen:
                        c.source_references.append(r)
                        seen.add(k)
                        attached = True
                if f.statement_hu != c.statement_hu:
                    note = f"Összevont megfogalmazás: „{f.statement_hu}”"
                    if note not in c.limitations:
                        c.limitations.append(note)
                for l in f.limitations:
                    if l not in c.limitations:
                        c.limitations.append(l)
                if f.disposition == Disposition.lead:         # a kétség nem oldódik fel ismétléssel: a szigorúbb besorolás marad
                    c.disposition = Disposition.lead
                    c.lead_reasons += [x for x in f.lead_reasons if x not in c.lead_reasons]
                if attached:
                    log.append(FilterEntry(video_source_id=f.source_references[0].video_source_id, segment_ids=f.source_references[0].transcript_segment_ids,
                                           snippet=f.statement_hu[:160], reason_code=SkipReason.duplicate_source_attached,
                                           reason_hu="ismétlés: új forrás csatolva a meglévő megállapításhoz", finding_id=c.id))
                break
            if c.category == f.category and similar(c.statement_hu, f.statement_hu):
                # hasonló, de eltérő feltétel/ellenpélda/verzió/szám: külön marad, összekötve
                if f.id not in c.related_ids:
                    c.related_ids.append(f.id)
                if c.id not in f.related_ids:
                    f.related_ids.append(c.id)
        else:
            clusters.append(f)
            continue
    for c in clusters:
        vids = {r.video_source_id for r in c.source_references}
        if len(vids) >= 2:
            c.evidence_status = EvidenceStatus.repeated_across_sources
            creators = {(videos[v].creator or v) for v in vids if v in videos}
            c.limitations.append("Több videóban is szerepel, de ez nem független ellenőrzés: a videók ugyanazt az eredeti forrást is ismételhetik."
                                 + (" Mindegyik ugyanattól a készítőtől származik." if len(creators) == 1 else ""))
        else:
            c.evidence_status = EvidenceStatus.source_claim
        for rid in c.related_ids:
            other = next((x for x in clusters if x.id == rid), None)
            if other is not None and f"Eltérő feltétel/verzió/ellenpélda: lásd {rid}" not in c.limitations:
                c.limitations.append(f"Eltérő feltétel/verzió/ellenpélda: lásd {rid}")
    ids = {c.id for c in clusters}
    for c in clusters:
        c.related_ids = [r for r in c.related_ids if r in ids]
    return clusters, log
