"""TikTok: csak nyilvános metaadat az oEmbed végponton. FELIRAT/ÁTIRAT NINCS: a TikTok nem ad nyilvános, hitelesítés nélküli felirat-API-t,
és a hangból átiratot készítő útvonal (letöltés + engedélyezett beszédfelismerő) ebben a kiadásban nincs megvalósítva.
A képesség-lista ezt kimondja, ezért a pipeline a TikTok-videót átirat nélkülinek jelöli, kitalált szöveg nélkül."""
from __future__ import annotations

import requests

from ..models import Platform
from .base import ProviderPermanentError, TranscriptResult, VideoMetadata
from .direct import DirectAdapter
from .http import get_json

OEMBED = "https://www.tiktok.com/oembed"
HOSTS = frozenset({"www.tiktok.com"})


class TikTokAdapter(DirectAdapter):
    name = "tiktok-oembed"
    platform = Platform.tiktok

    def __init__(self, allowed_platforms=("youtube", "tiktok"), session: requests.Session | None = None):
        super().__init__(allowed_platforms)
        self._session = session

    def capabilities(self) -> dict[str, bool]:
        return {"search_videos": False, "fetch_video_metadata": True, "fetch_transcript": False, "speech_to_text": False, "visual": False}

    def fetch_metadata(self, url: str) -> VideoMetadata:
        ref = self.normalize_url(url)
        d = get_json(OEMBED, {"url": ref.canonical_url}, HOSTS, self._session)
        # A valódi oEmbed-válasz (2026-11-20 próba) cím és szerző nélkül is érkezhet; ilyenkor null marad, a készítő a link @kezelője (a linkből, nem kitalálva).
        handle = ref.canonical_url.split("/@", 1)[1].split("/", 1)[0]
        return VideoMetadata(title=d.get("title") if isinstance(d.get("title"), str) else None,
                             creator=d.get("author_name") if isinstance(d.get("author_name"), str) else f"@{handle}",
                             raw_ref=f"oembed:tiktok:{ref.video_id}")

    def fetch_captions(self, url: str, languages: list[str]) -> TranscriptResult:
        raise ProviderPermanentError("TikTok-felirat nem támogatott ebben a kiadásban")
