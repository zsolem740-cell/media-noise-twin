"""Valódi HTTP-átvitel a Gemini és a Groq felé (csak stdlib). Aláírása megegyezik a modelrun által várt átvitelével: transport(model, body) -> Raw.
Biztonság: a kulcs csak fejlécben megy (soha URL-ben), átirányítást nem követ (a fejléc nem kerülhet más hosztra), a kivételek szövege nem tartalmaz kulcsot,
és az objektum szöveges alakja nem mutatja a kulcsot."""
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from ..modelrun import Raw, TransportTimeout

DEFAULT_BASE = {"gemini": "https://generativelanguage.googleapis.com", "groq": "https://api.groq.com"}
PATH = {"gemini": "/v1beta/models/{model}:generateContent", "groq": "/openai/v1/chat/completions"}
MAX_BYTES = 2_000_000


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None                                          # a 3xx válasz hibaként tér vissza, a kulcs nem megy tovább


class HttpTransport:
    def __init__(self, provider, api_key, timeout_s, base_url=None):
        if provider not in PATH:
            raise ValueError(f"ismeretlen szolgáltató: {provider}")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("hiányzik a kulcs")
        self.provider, self._key, self.timeout_s = provider, api_key.strip(), float(timeout_s)
        self.base = (base_url or DEFAULT_BASE[provider]).rstrip("/")
        if not base_url and not self.base.startswith("https://"):
            raise ValueError("az éles cím csak https lehet")
        self._opener = urllib.request.build_opener(_NoRedirect)

    def __repr__(self):
        return f"HttpTransport(provider={self.provider!r}, base={self.base!r}, key=<elrejtve>)"

    def _headers(self):
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.provider == "gemini":
            h["x-goog-api-key"] = self._key
        else:
            h["Authorization"] = "Bearer " + self._key
        return h

    def _url(self, model):
        path = PATH[self.provider]
        return self.base + (path.format(model=urllib.parse.quote(str(model), safe="")) if "{model}" in path else path)

    def __call__(self, model, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self._url(model), data=data, headers=self._headers(), method="POST")
        t0 = time.monotonic()
        try:
            with self._opener.open(req, timeout=self.timeout_s) as r:
                text, status, ra = r.read(MAX_BYTES).decode("utf-8", "replace"), r.status, r.headers.get("Retry-After")
        except urllib.error.HTTPError as e:
            try:
                text = e.read(MAX_BYTES).decode("utf-8", "replace")
            except Exception:
                text = ""
            status, ra = e.code, e.headers.get("Retry-After") if e.headers else None
        except (socket.timeout, TimeoutError):
            raise TransportTimeout("időtúllépés") from None
        except urllib.error.URLError as e:
            if isinstance(e.reason, (socket.timeout, TimeoutError)):
                raise TransportTimeout("időtúllépés") from None
            raise ConnectionError("hálózati hiba") from None
        except OSError:
            raise ConnectionError("hálózati hiba") from None
        return Raw(status, text, ra, int((time.monotonic() - t0) * 1000))
