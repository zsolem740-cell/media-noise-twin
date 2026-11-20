"""URL-normalizálás és platform-engedélylista. Saját letöltést az 1. verzió nem végez, ezért SSRF-felület sincs:
csak a normalizált, engedélyezett platform-azonosítók mennek az adaptereknek, a szolgáltató tölt le."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from .models import Platform

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_TT_ID = re.compile(r"^\d{8,25}$")
_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_TT_HOSTS = {"tiktok.com", "www.tiktok.com", "m.tiktok.com"}


class UrlRejected(ValueError):
    pass


@dataclass(frozen=True)
class VideoRef:
    platform: Platform
    video_id: str
    canonical_url: str


def normalize_video_url(raw: str, allowed: tuple[str, ...] = ("youtube", "tiktok")) -> VideoRef:
    raw = (raw or "").strip()
    if len(raw) > 2048:
        raise UrlRejected("túl hosszú URL")
    u = urlparse(raw)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise UrlRejected("csak http(s) videólink fogadható el")
    if u.username or u.password:
        raise UrlRejected("hitelesítő adat nem lehet az URL-ben")
    host = u.hostname.lower()
    if host in _YT_HOSTS or host == "youtu.be":
        vid = None
        if host == "youtu.be":
            vid = u.path.strip("/").split("/")[0]
        elif u.path == "/watch":
            vid = (parse_qs(u.query).get("v") or [None])[0]
        else:
            m = re.match(r"^/(shorts|embed|live)/([^/?#]+)", u.path)
            vid = m.group(2) if m else None
        if not vid or not _YT_ID.match(vid):
            raise UrlRejected("nem felismerhető YouTube-videóazonosító")
        ref = VideoRef(Platform.youtube, vid, f"https://www.youtube.com/watch?v={vid}")
    elif host in _TT_HOSTS:
        m = re.match(r"^/@([A-Za-z0-9_.-]{1,64})/video/(\d+)/?$", u.path)
        if not m or not _TT_ID.match(m.group(2)):
            raise UrlRejected("nem felismerhető TikTok-videólink (a rövid vm.tiktok.com linkek feloldása nincs támogatva)")
        ref = VideoRef(Platform.tiktok, m.group(2), f"https://www.tiktok.com/@{m.group(1)}/video/{m.group(2)}")
    else:
        raise UrlRejected(f"nem engedélyezett platform: {host}")
    if ref.platform.value not in allowed:
        raise UrlRejected(f"a platform nincs engedélyezve: {ref.platform.value}")
    return ref
