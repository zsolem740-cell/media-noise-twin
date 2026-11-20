"""Adapterszerződés. Három képesség: search_videos, fetch_video_metadata, fetch_transcript.
Az adapter jelzi, melyiket támogatja; a keresés és az átirat különböző szolgáltatótól is jöhet.

Egy művelet kétfázisú (start -> poll -> results), hogy a szolgáltatói futásazonosító menthető legyen,
és újraindítás után a futás állapota lekérdezhető legyen vak újraindítás helyett.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from ..models import Platform, TranscriptOrigin


class Capability(str, Enum):
    search_videos = "search_videos"
    fetch_video_metadata = "fetch_video_metadata"
    fetch_transcript = "fetch_transcript"


class ProviderPermanentError(Exception):
    """Nem javítható hiba (hibás beállítás, hozzáférés, nem létező Actor): újrapróbálás nincs."""


class ProviderNotConfigured(ProviderPermanentError):
    """Éles módban nincs beállított szolgáltató ehhez a képességhez. Soha nem helyettesítjük kitalált adattal."""


@dataclass
class RunState:
    status: str                 # running | succeeded | failed | aborted
    cost_usd: float | None = None   # None = nem ismert költség (nem becslés!)
    message: str = ""


@dataclass
class VideoCandidate:
    url: str
    title: str | None = None


@dataclass
class VideoMetadata:
    title: str | None = None
    creator: str | None = None
    published_at: str | None = None        # ISO-szöveg, ha ismert
    duration_seconds: float | None = None
    raw_ref: str | None = None


@dataclass
class RawSegment:
    text: str
    start: float | None = None
    end: float | None = None


@dataclass
class TranscriptResult:
    language: str
    origin: TranscriptOrigin
    segments: list[RawSegment] = field(default_factory=list)   # üres: nincs hozzáférhető átirat
    auto_generated: bool | None = None


@runtime_checkable
class VideoAdapter(Protocol):
    name: str
    is_fixture: bool

    def supports(self, capability: Capability, platform: Platform) -> bool: ...
    def estimate_cost(self, capability: Capability, platform: Platform, units: int) -> float | None: ...
    def max_run_cost(self, capability: Capability, platform: Platform) -> float: ...
    def start(self, capability: Capability, platform: Platform, params: dict) -> str: ...
    def poll(self, run_id: str) -> RunState: ...
    def abort(self, run_id: str) -> bool: ...
    def results(self, capability: Capability, platform: Platform, run_id: str, params: dict): ...


class AdapterRegistry:
    """Csak a regisztrált, engedélyezett adapterek hívhatók. Fixture éles módban nem regisztrálható."""

    def __init__(self, production: bool):
        self.production = production
        self._adapters: list[VideoAdapter] = []

    def register(self, adapter: VideoAdapter) -> None:
        if self.production and adapter.is_fixture:
            raise ProviderPermanentError("fixture adapter éles módban tiltott")
        self._adapters.append(adapter)

    def get(self, capability: Capability, platform: Platform) -> VideoAdapter:
        for a in self._adapters:
            if a.supports(capability, platform):
                return a
        raise ProviderNotConfigured(
            f"Nincs beállított szolgáltató ehhez: {platform.value}:{capability.value}. "
            "Állíts be ellenőrzött Actort (VR_ACTORS_FILE), lásd video_research/docs/ACTORS.md.")
