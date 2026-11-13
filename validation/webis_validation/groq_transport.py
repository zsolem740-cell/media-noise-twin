"""A Groq-ág EGYETLEN hálózati fájlja. Csak ez olvashatja a GROQ_API_KEY környezeti változót, és csak a beállított api.groq.com címre küldhet.

A kulcs nem kerül naplóba, kimenetbe, hibaüzenetbe vagy fájlba. Egyetlen kulcsot használ (GROQ_API_KEY), nincs tartalék kulcs, és nincs automatikus szolgáltatóváltás."""
import os
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .groq_run import Raw, TransportTimeout


class MissingKey(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Az átirányítást nem követjük: a kulcsot hordozó fejléc így nem juthat el más géphez. A 3xx válasz hibaként jön vissza."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def make_transport(cfg):
    g = cfg["groq"]
    parts = urlsplit(g["base_url"])
    if parts.scheme != "https" or parts.hostname != "api.groq.com":
        raise ValueError("a Groq-átvitel csak https://api.groq.com címre küldhet")
    key = os.environ.get(g["env_var"], "")
    if not key.strip():
        raise MissingKey(f"a {g['env_var']} környezeti változó nincs beállítva")
    url = g["base_url"].rstrip("/") + g["path"]
    timeout = g["run"]["timeout_s"]
    opener = urllib.request.build_opener(NoRedirect)

    def send(body_bytes):
        req = urllib.request.Request(url, data=body_bytes, method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer " + key, "User-Agent": "webis-validation/1"})
        t0 = time.monotonic()
        try:
            with opener.open(req, timeout=timeout) as r:
                return Raw(r.status, r.read().decode("utf-8", "replace"), r.headers.get("retry-after"), time.monotonic() - t0)
        except urllib.error.HTTPError as e:
            return Raw(e.code, e.read().decode("utf-8", "replace"), e.headers.get("retry-after"), time.monotonic() - t0)
        except (socket.timeout, TimeoutError):
            raise TransportTimeout("időtúllépés") from None
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), (socket.timeout, TimeoutError)):
                raise TransportTimeout("időtúllépés") from None
            raise ConnectionError("hálózati hiba (részletek szándékosan nélkül)") from None
    return send
