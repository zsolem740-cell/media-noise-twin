"""Ismétlődések összevonása nyomtalan törlés nélkül: minden forráshivatkozás megmarad.
Több ismétlés önmagában NEM igazolás; verified állapot nincs: külső ellenőrzést az 1. verzió nem végez."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .extraction import _norm
from .models import EvidenceStatus, Finding, VideoSource

_STOP = {"és", "a", "az", "hogy", "is", "egy", "van", "nem", "the", "and", "of", "to", "in", "is", "a", "for", "with"}


def _tokens(s: str) -> set[str]:
    return {t for t in _norm(s).split() if t not in _STOP and len(t) > 2}


def similar(a: str, b: str, threshold: float = 0.6) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    jac = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    return jac >= threshold or SequenceMatcher(None, _norm(a), _norm(b)).ratio() >= 0.8


def merge_findings(findings: list[Finding], videos: dict[str, VideoSource]) -> list[Finding]:
    clusters: list[Finding] = []
    for f in findings:
        f = f.model_copy(deep=True)
        for c in clusters:
            if c.category == f.category and similar(c.statement_hu, f.statement_hu):
                seen = {(r.video_source_id, tuple(r.transcript_segment_ids), r.supporting_quote) for r in c.source_references}
                for r in f.source_references:
                    k = (r.video_source_id, tuple(r.transcript_segment_ids), r.supporting_quote)
                    if k not in seen:
                        c.source_references.append(r)
                        seen.add(k)
                if f.statement_hu != c.statement_hu:
                    note = f"Összevont megfogalmazás: „{f.statement_hu}”"
                    if note not in c.limitations:
                        c.limitations.append(note)
                for l in f.limitations:
                    if l not in c.limitations:
                        c.limitations.append(l)
                break
        else:
            clusters.append(f)
    for c in clusters:
        vids = {r.video_source_id for r in c.source_references}
        if len(vids) >= 2:
            c.evidence_status = EvidenceStatus.repeated_across_sources
            creators = {(videos[v].creator or v) for v in vids if v in videos}
            c.limitations.append("Több videóban is szerepel, de ez nem független ellenőrzés."
                                 + (" Mindegyik ugyanattól a készítőtől származik." if len(creators) == 1 else ""))
        else:
            c.evidence_status = EvidenceStatus.source_claim
    return clusters
