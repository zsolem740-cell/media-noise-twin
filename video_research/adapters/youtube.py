"""YouTube: nyilvános metaadat (oEmbed) és a videóhoz tartozó elérhető felirat (`youtube-transcript-api`, MIT).

Hozzáférés: nincs API-kulcs, nincs cookie, nincs jelszó. Ha a YouTube blokkolja a kérést (IP-tiltás, CAPTCHA), az adapter ezt egyértelmű hibaként adja,
a blokkot NEM kerüljük meg (nincs proxy-forgatás, nincs CAPTCHA-megoldás). Felirat nélküli videónál üres átirat jön: beszédfelismerés ebben az adapterben nincs.
Keresés nincs (M4). A hosszt az oEmbed nem adja, ezért a duration_seconds null marad."""
from __future__ import annotations

from typing import Callable

import requests

from ..util import RetryableError
from .base import ProviderPermanentError, RawSegment, TranscriptResult, VideoMetadata
from .direct import DirectAdapter
from .http import get_json
from ..models import Platform, TranscriptOrigin

OEMBED = "https://www.youtube.com/oembed"
HOSTS = frozenset({"www.youtube.com"})


class YouTubeAdapter(DirectAdapter):
    name = "youtube-captions"
    platform = Platform.youtube

    def __init__(self, allowed_platforms=("youtube", "tiktok"), session: requests.Session | None = None,
                 transcript_api_factory: Callable[[], object] | None = None):
        super().__init__(allowed_platforms)
        self._session = session
        self._factory = transcript_api_factory

    def capabilities(self) -> dict[str, bool]:
        return {"search_videos": False, "fetch_video_metadata": True, "fetch_transcript": True, "speech_to_text": False, "visual": False}

    def fetch_metadata(self, url: str) -> VideoMetadata:
        ref = self.normalize_url(url)
        d = get_json(OEMBED, {"url": ref.canonical_url, "format": "json"}, HOSTS, self._session)
        return VideoMetadata(title=d.get("title") if isinstance(d.get("title"), str) else None,
                             creator=d.get("author_name") if isinstance(d.get("author_name"), str) else None,
                             published_at=None, duration_seconds=None, raw_ref=f"oembed:youtube:{ref.video_id}")

    def fetch_captions(self, url: str, languages: list[str]) -> TranscriptResult:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api import _errors as E        # a telepített 1.2.5-ös csomag kivételosztályai
        ref = self.normalize_url(url)
        api = self._factory() if self._factory else YouTubeTranscriptApi()
        try:
            t = api.fetch(ref.video_id, languages=languages)
        except (E.TranscriptsDisabled, E.NoTranscriptFound):
            return TranscriptResult(language=languages[0], origin=TranscriptOrigin.platform_caption, segments=[])     # nincs felirat: üres
        except (E.IpBlocked, E.RequestBlocked) as exc:
            raise ProviderPermanentError("A YouTube blokkolta a feliratkérést (IP-/botvédelem). A blokkot nem kerüljük meg; "
                                         "futtasd más hálózatról, vagy adj engedélyezett beszédfelismerő útvonalat.") from exc
        except (E.VideoUnavailable, E.VideoUnplayable, E.AgeRestricted, E.InvalidVideoId) as exc:
            raise ProviderPermanentError(f"A videó nem nyilvánosan elérhető ({type(exc).__name__}).") from exc
        except (E.YouTubeRequestFailed, E.HTTPError, requests.ConnectionError, requests.Timeout) as exc:
            raise RetryableError(f"átmeneti hálózati hiba a feliratkérésnél ({type(exc).__name__}); ha tartósan fennáll, a YouTube blokkolhatja a hálózatot vagy a hálózati szabály tiltja a címet") from exc
        except E.YouTubeTranscriptApiException as exc:
            raise ProviderPermanentError(f"A felirat nem kérhető le: {type(exc).__name__}") from exc
        segs = [RawSegment(text=s.text, start=float(s.start), end=float(s.start) + float(s.duration)) for s in t.snippets]
        return TranscriptResult(language=t.language_code, origin=TranscriptOrigin.platform_caption, segments=segs, auto_generated=bool(t.is_generated))
