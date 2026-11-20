"""Korlátozott kimenő HTTP: csak https, csak engedélyezett hoszt, nincs átirányítás-követés, időkorlát és méretkorlát.
Az URL-t az adapter a normalizált azonosítóból építi; a felhasználó vagy a modell nyers URL-jét nem hívjuk."""
from __future__ import annotations

import json
from urllib.parse import urlparse

import requests

from ..util import RetryableError
from .base import ProviderPermanentError

MAX_BYTES = 256 * 1024
TIMEOUT = (5, 15)


def get_json(url: str, params: dict, allowed_hosts: frozenset[str], session: requests.Session | None = None) -> dict:
    u = urlparse(url)
    if u.scheme != "https" or u.hostname not in allowed_hosts:
        raise ProviderPermanentError(f"nem engedélyezett kimenő cím: {u.hostname}")
    s = session or requests.Session()
    try:
        r = s.get(url, params=params, timeout=TIMEOUT, allow_redirects=False, stream=True,
                  headers={"User-Agent": "video-research/1.0 (nyilvános oEmbed)", "Accept": "application/json"})
        try:
            if 300 <= r.status_code < 400:
                raise ProviderPermanentError("átirányítás: nem követjük")
            if r.status_code in (404, 400, 401, 403):
                raise ProviderPermanentError(f"a videó metaadata nem érhető el (HTTP {r.status_code}): privát, törölt vagy nem nyilvános lehet")
            if r.status_code == 429 or r.status_code >= 500:
                raise RetryableError(f"átmeneti szolgáltatói hiba (HTTP {r.status_code})")
            body = b""
            for chunk in r.iter_content(8192):
                body += chunk
                if len(body) > MAX_BYTES:
                    raise ProviderPermanentError("a válasz túl nagy")
        finally:
            r.close()
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise RetryableError(f"hálózati hiba: {type(exc).__name__}") from exc
    try:
        data = json.loads(body.decode("utf-8"))
    except ValueError as exc:
        raise ProviderPermanentError("a válasz nem érvényes JSON") from exc
    if not isinstance(data, dict):
        raise ProviderPermanentError("váratlan válaszszerkezet")
    return data
