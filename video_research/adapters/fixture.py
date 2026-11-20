"""EGYÉRTELMŰEN JELÖLT TESZT-FIXTURE fejlesztéshez. Nem valódi videók: minden VideoSource `is_fixture=True`,
a szolgáltató neve "fixture", a jelentés pedig figyelmeztetést kap. Éles módban a regisztráció tiltott."""
from __future__ import annotations

import json
from pathlib import Path

from ..models import Platform, TranscriptOrigin
from .base import (Capability, ProviderPermanentError, RawSegment, RunState, TranscriptResult, VideoCandidate, VideoMetadata)


class FixtureAdapter:
    name = "fixture"
    is_fixture = True

    def __init__(self, data: dict):
        self.data = data          # {"videos": [{"platform","url","title","creator","duration_seconds","language","origin","segments":[{"text","start","end"}]}]}

    @classmethod
    def from_file(cls, path: str | Path) -> "FixtureAdapter":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def supports(self, capability: Capability, platform: Platform) -> bool:
        return any(v["platform"] == platform.value for v in self.data.get("videos", []))

    def estimate_cost(self, capability, platform, units) -> float | None:
        return 0.0

    def max_run_cost(self, capability, platform) -> float:
        return 0.0

    def start(self, capability: Capability, platform: Platform, params: dict) -> str:
        return f"fixture-{capability.value}-{abs(hash(json.dumps(params, sort_keys=True))) % 10**8}"

    def poll(self, run_id: str) -> RunState:
        return RunState("succeeded", cost_usd=0.0)

    def abort(self, run_id: str) -> bool:
        return True

    def _find(self, url: str) -> dict:
        for v in self.data["videos"]:
            if v["url"] == url:
                return v
        raise ProviderPermanentError(f"a fixture nem ismeri ezt az URL-t: {url}")

    def results(self, capability: Capability, platform: Platform, run_id: str, params: dict):
        if capability == Capability.search_videos:
            q = params["query"].lower()
            words = [w for w in q.split() if len(w) > 2]
            out = [VideoCandidate(v["url"], v.get("title")) for v in self.data["videos"]
                   if v["platform"] == platform.value and (not words or any(w in (v.get("title", "") + " " + v.get("tags", "")).lower() for w in words))]
            return out[: params.get("max_results", 10)]
        v = self._find(params["url"])
        if capability == Capability.fetch_video_metadata:
            return VideoMetadata(v.get("title"), v.get("creator"), v.get("published_at"), v.get("duration_seconds"), raw_ref=f"fixture:{v['url']}")
        segs = [RawSegment(s["text"], s.get("start"), s.get("end")) for s in v.get("segments", [])]
        return TranscriptResult(v.get("language", "hu"), TranscriptOrigin(v.get("origin", "platform_caption")), segs)
