"""Az élő-ellenőr lekérője és parancssori belépője: egyetlen GET egy feltöltött pilot-címre. A hálózati kód a live csomagban van; az ellenőrzések logikája hálózatmentes (livecheck).
  python -m validation.hu_pilot.live.pagecheck URL [--stage 1|2|4] [--results MAPPA]
Csak olvas: nem telepít, kulcsot nem használ, nem ír a tárolóba. Fejlécben csak általános kliensnevet küld."""
import sys
import urllib.error
import urllib.request

from .. import livecheck

TIMEOUT = 20
MAX_BYTES = 5_000_000
USER_AGENT = "hu-pilot-livecheck"


def default_fetch(url):
    """Egyetlen GET. Átirányítást követ, de a végső címet visszaadja, hogy az ellenőr lássa, ha másik gépre vitték."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return {"status": r.status, "headers": {k.lower(): v for k, v in r.headers.items()}, "body": r.read(MAX_BYTES), "url": r.geturl()}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "headers": {k.lower(): v for k, v in e.headers.items()}, "body": e.read(MAX_BYTES), "url": url}


if __name__ == "__main__":
    sys.exit(livecheck.main(sys.argv[1:], default_fetch))
