"""Explicit felhasználói átiratimport: egyszerű szöveg, SRT vagy VTT. Eredet: `user_provided_transcript`.

Az időbélyeg csak akkor van, ha az SRT/VTT fájl ténylegesen tartalmazza; egyszerű szövegnél MINDIG null. Stabil szegmensazonosítót generálunk (`<video>:s<N>`),
időbélyeget soha. A megadott videólink NEM jelent igazolt átirat–videó egyezést (`transcript_link_status = user_asserted_unverified`).
Az import tesztelést segít: nem bizonyít platformintegrációt."""
from __future__ import annotations

import hashlib
import re

from .config import Settings
from .db import Store
from .models import (AccessStatus, JobStatus, Limits, Platform, StepStatus, Transcript, TranscriptOrigin, TranscriptSegment, VideoSource)
from .urls import UrlRejected, normalize_video_url
from .util import new_id, now

FORMATS = ("text", "srt", "vtt")
_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
_ARROW = re.compile(r"^\s*([\d:.,]+)\s*-->\s*([\d:.,]+)")
_TAG = re.compile(r"<[^>]+>")
CHUNK = 400


class ImportError_(ValueError):
    pass


def _sec(s: str) -> float | None:
    m = _TS.fullmatch(s.strip())
    if not m:
        return None
    h, mi, sec, ms = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(sec) + int(ms.ljust(3, "0")) / 1000


def _clean(t: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub("", t)).strip()


def parse_plain(text: str) -> list[tuple[str, None, None]]:
    """Bekezdések/sorok szerint; túl hosszú sor mondathatáron darabolva. Időbélyeg nincs (null)."""
    out: list[tuple[str, None, None]] = []
    for para in re.split(r"\n\s*\n|\r\n\s*\r\n", text):
        for line in (l for l in para.splitlines() if l.strip()):
            line = _clean(line)
            while len(line) > CHUNK:
                cut = max(line.rfind(". ", 0, CHUNK), line.rfind("? ", 0, CHUNK), line.rfind("! ", 0, CHUNK))
                cut = cut + 1 if cut > 40 else line.rfind(" ", 0, CHUNK)
                cut = cut if cut > 0 else CHUNK
                out.append((line[:cut].strip(), None, None))
                line = line[cut:].strip()
            if line:
                out.append((line, None, None))
    return out


def parse_cues(text: str, fmt: str) -> list[tuple[str, float | None, float | None]]:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    if fmt == "vtt":
        if not text.startswith("WEBVTT"):
            raise ImportError_("A VTT fájl nem „WEBVTT” fejléccel kezdődik.")
        text = text.split("\n", 1)[1] if "\n" in text else ""
    out: list[tuple[str, float | None, float | None]] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [l for l in block.split("\n")]
        if not any(l.strip() for l in lines):
            continue
        if fmt == "vtt" and lines[0].startswith(("NOTE", "STYLE", "REGION")):
            continue
        idx = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if idx is None:
            continue
        m = _ARROW.match(lines[idx])
        start, end = (_sec(m.group(1)), _sec(m.group(2))) if m else (None, None)
        if start is None:
            raise ImportError_(f"Értelmezhetetlen időbélyeg: {lines[idx][:60]!r}")
        if end is not None and end < start:
            end = None                                         # hibás vég: null, nem találgatjuk
        body = _clean(" ".join(lines[idx + 1:]))
        if body:
            out.append((body, start, end))
    return out


def parse_transcript(text: str, fmt: str, max_chars: int) -> list[tuple[str, float | None, float | None]]:
    if fmt not in FORMATS:
        raise ImportError_(f"A formátum text, srt vagy vtt lehet (kapott: {fmt!r}).")
    if not text or not text.strip():
        raise ImportError_("Az átirat üres.")
    if len(text) > max_chars:
        raise ImportError_(f"Az átirat túl hosszú ({len(text)} > {max_chars} karakter).")
    segs = parse_plain(text) if fmt == "text" else parse_cues(text, fmt)
    if not segs:
        raise ImportError_("Az átiratból nem nyerhető ki szöveges szegmens.")
    return segs


def import_job(store: Store, settings: Settings, *, question: str, transcript_text: str, fmt: str, language: str, title: str | None,
               video_url: str | None, known_information: list[str] | None = None, limits: Limits | None = None,
               idempotency_key: str | None = None) -> tuple[str, bool]:
    """Feladat létrehozása importált átirattal. Visszaad: (job_id, created)."""
    if language not in ("hu", "en"):
        raise ImportError_("Az átirat nyelve hu vagy en lehet.")
    segs = parse_transcript(transcript_text, fmt, settings.max_transcript_chars)
    ref = None
    if video_url:
        try:
            ref = normalize_video_url(video_url, tuple(settings.allowed_platforms))
        except UrlRejected as exc:
            raise ImportError_(f"A megadott videólink nem fogadható el: {exc}") from exc
    body = "\n".join(t for t, _, _ in segs)
    chash = hashlib.sha256(body.encode()).hexdigest()
    job, created = store.create_job(question, [], [language], limits or settings.limits, (idempotency_key and f"imp-{idempotency_key}") or None, known_information)
    if not created:
        return job.id, False
    vid = VideoSource(id=new_id("vid"), platform=ref.platform if ref else Platform.manual, platform_video_id=ref.video_id if ref else f"import-{chash[:16]}",
                      canonical_url=ref.canonical_url if ref else f"user-import:{chash[:16]}", title=(title or "").strip()[:200] or None, creator=None,
                      retrieved_at=now(), provider="user-import", access_status=AccessStatus.ok, raw_metadata_reference="user_import",
                      transcript_link_status="user_asserted_unverified" if ref else "not_applicable")
    store.add_video(job.id, vid)
    ts_ok = any(s is not None for _, s, _ in segs)
    store.save_transcript(job.id, Transcript(
        id=new_id("trn"), video_source_id=vid.id, language=language, origin=TranscriptOrigin.user_provided_transcript,
        segments=[TranscriptSegment(id=f"{vid.id}:s{i}", start_seconds=s, end_seconds=e, text=t) for i, (t, s, e) in enumerate(segs)],
        timestamps_available=ts_ok, content_hash=chash, provider="user-import", auto_generated=None, fetched_at=now()))
    for step in (f"meta:{vid.id}", f"tr:{vid.id}"):
        store.set_step(job.id, step, StepStatus.done, {"source": "user_import"})
    store.set_step(job.id, "collect", StepStatus.done, {"videos": 1, "source": "user_import"})
    return job.id, True
