"""Közös alap a SZINKRON, ingyenes, közvetlen platformadaptereknek (nincs fizetős szolgáltatói futás).
Az adapter-szerződés: capabilities(), normalize_url(url), fetch_metadata(url), fetch_captions(url, languages). Az adapter nem végez MI-elemzést
és nem kezel hitelesítőt. Az `start/poll/results` csak az Executor kétfázisú felületéhez illeszt; a futásazonosító nem szolgáltatói futás."""
from __future__ import annotations

import uuid

from ..models import Platform
from ..urls import VideoRef, normalize_video_url
from .base import Capability, RunState, TranscriptResult, VideoMetadata


class DirectAdapter:
    name = "direct"
    is_fixture = False
    platform: Platform

    def __init__(self, allowed_platforms: tuple[str, ...] = ("youtube", "tiktok")):
        self.allowed = allowed_platforms
        self._cache: dict[str, object] = {}

    # --- az új szerződés ---
    def capabilities(self) -> dict[str, bool]:
        raise NotImplementedError

    def normalize_url(self, url: str) -> VideoRef:
        ref = normalize_video_url(url, self.allowed)
        if ref.platform != self.platform:
            raise ValueError("az adapter nem ehhez a platformhoz tartozik")
        return ref

    def fetch_metadata(self, url: str) -> VideoMetadata:
        raise NotImplementedError

    def fetch_captions(self, url: str, languages: list[str]) -> TranscriptResult:
        raise NotImplementedError

    # --- Executor-illesztés ---
    def supports(self, capability: Capability, platform: Platform) -> bool:
        return platform == self.platform and bool(self.capabilities().get(capability.value))

    def estimate_cost(self, capability, platform, units) -> float | None:
        return 0.0

    def max_run_cost(self, capability, platform) -> float:
        return 0.0

    def _run(self, capability: Capability, params: dict):
        if capability == Capability.fetch_video_metadata:
            return self.fetch_metadata(params["url"])
        if capability == Capability.fetch_transcript:
            return self.fetch_captions(params["url"], [params.get("language", "hu"), "en"] if params.get("language") != "en" else ["en", "hu"])
        raise ValueError(f"nem támogatott képesség: {capability.value}")

    def start(self, capability: Capability, platform: Platform, params: dict) -> str:
        result = self._run(capability, params)                         # hiba itt Retryable/Permanent
        run_id = f"{self.name}-{uuid.uuid4().hex[:12]}"
        self._cache[run_id] = result
        return run_id

    def poll(self, run_id: str) -> RunState:
        return RunState("succeeded", cost_usd=0.0)                     # ingyenes: a költség ismert, nulla

    def abort(self, run_id: str) -> bool:
        return True

    def results(self, capability: Capability, platform: Platform, run_id: str, params: dict):
        if run_id in self._cache:
            return self._cache.pop(run_id)
        return self._run(capability, params)                           # újraindítás után: ingyenes, ismételhető lekérés
