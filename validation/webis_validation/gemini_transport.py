"""A Gemini-ellenőrzés EGYETLEN hálózati fájlja: models.list (csak olvasás) és generateContent. Csak a beállított generativelanguage.googleapis.com címre küld.

A kulcsot a hálózati titok adja a proxyn át; a helyi változó (config: gemini.check.env_var) csak a fejléc kitöltéséhez kell, és nem kerül naplóba, kimenetbe, hibaüzenetbe.
Nem követ átirányítást. Egyetlen kulcs, nincs tartalék kulcs, nincs automatikus fizetős váltás."""
import json
import os
import socket
import time
import urllib.error
import urllib.request

from .gemini_smoke import Raw, TransportTimeout


ALLOWED_HOST = "generativelanguage.googleapis.com"


class MissingKey(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _opener_and_key(cfg):
    c = cfg["gemini"]["check"]
    if c["host"] != ALLOWED_HOST:
        raise ValueError("a Gemini-átvitel csak a generativelanguage.googleapis.com címre küldhet")
    key = os.environ.get(c["env_var"], "")
    if not key.strip():
        raise MissingKey(f"a {c['env_var']} környezeti változó nincs beállítva")
    return urllib.request.build_opener(NoRedirect), key, c["host"], cfg["gemini"]["smoke"]["timeout_s"]


def _call(opener, req, timeout):
    t0 = time.monotonic()
    try:
        with opener.open(req, timeout=timeout) as r:
            return Raw(r.status, r.read().decode("utf-8", "replace"), int((time.monotonic() - t0) * 1000))
    except urllib.error.HTTPError as e:
        return Raw(e.code, e.read().decode("utf-8", "replace"), int((time.monotonic() - t0) * 1000))
    except (socket.timeout, TimeoutError):
        raise TransportTimeout("időtúllépés") from None
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), (socket.timeout, TimeoutError)):
            raise TransportTimeout("időtúllépés") from None
        raise ConnectionError("hálózati hiba (részletek szándékosan nélkül)") from None


def list_models(cfg):
    """Csak olvasó: a modelllista (név és támogatott módszerek), generálás nélkül."""
    opener, key, host, timeout = _opener_and_key(cfg)
    models, token = [], None
    for _ in range(10):
        url = f"https://{host}/v1beta/models?pageSize=200" + (f"&pageToken={token}" if token else "")
        raw = _call(opener, urllib.request.Request(url, method="GET", headers={"x-goog-api-key": key}), timeout)
        if raw.status != 200:
            raise ConnectionError(f"modelllista: HTTP {raw.status}")
        d = json.loads(raw.text)
        models += d.get("models", [])
        token = d.get("nextPageToken")
        if not token:
            break
    return {"models": [{"name": m.get("name"), "supportedGenerationMethods": m.get("supportedGenerationMethods")} for m in models]}


def make_transport(cfg):
    opener, key, host, timeout = _opener_and_key(cfg)

    def send(model, body):
        url = f"https://{host}/v1beta/models/{model}:generateContent"
        req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
        return _call(opener, req, timeout)
    return send
