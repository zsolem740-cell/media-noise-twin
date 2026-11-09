"""Címek földrajzi elhelyezése (város/ország-szótár, nincs külső szolgáltatás)."""
import hashlib
import re

# (lat, lng, [angol nevek – szóhatáros], [magyar tövek – ragozott alakot is elfogad])
TOWNS = {
    "HU-VA": [
        (47.23, 16.62, [], ["szombathely"]), (47.01, 16.60, [], ["körmend"]), (47.05, 16.80, [], ["vasvár"]),
        (47.39, 16.54, [], ["kőszeg"]), (47.25, 16.94, [], ["sárvár"]), (46.95, 16.28, [], ["szentgotthárd"]),
        (46.85, 16.43, [], ["őriszentpéter", "őrség"]), (47.25, 17.15, [], ["celldömölk"]), (47.42, 17.02, [], ["répcelak"]),
    ],
    "AT-1": [
        (47.29, 16.20, ["oberwart"], []), (47.06, 16.32, ["güssing"], []), (46.95, 16.15, ["jennersdorf"], []),
        (47.85, 16.52, ["eisenstadt"], []), (47.95, 16.84, ["neusiedl"], []), (47.74, 16.40, ["mattersburg"], []),
        (47.51, 16.50, ["oberpullendorf"], []),
    ],
    "SI-1": [
        (46.66, 16.17, ["murska sobota"], []), (46.56, 16.45, ["lendava"], []), (46.52, 16.19, ["ljutomer"], []),
        (46.67, 15.99, ["gornja radgona"], []), (46.61, 16.24, ["beltinci"], []),
    ],
    "HU-NAT": [
        (47.50, 19.04, [], ["budapest"]), (47.53, 21.63, [], ["debrecen"]), (46.25, 20.15, [], ["szeged"]),
        (48.10, 20.78, [], ["miskolc"]), (46.07, 18.23, [], ["pécs"]), (47.69, 17.63, [], ["győr"]),
        (47.95, 21.72, [], ["nyíregyháza"]), (46.90, 19.69, [], ["kecskemét"]), (47.19, 18.41, [], ["székesfehérvár"]),
        (47.18, 20.20, [], ["szolnok"]), (47.57, 18.40, [], ["tatabánya"]), (47.90, 20.38, [], ["eger"]),
        (47.09, 17.91, [], ["veszprém"]), (46.84, 16.84, [], ["zalaegerszeg"]), (46.68, 21.09, [], ["békéscsaba"]),
        (46.83, 17.74, [], ["balaton"]), (47.23, 16.62, [], ["szombathely"]),
    ],
}

COUNTRIES = [
    (39.8, -98.6, ["united states", "u.s.", "usa", "america", "white house", "pentagon"], ["egyesült államok", "amerikai egyesült", "fehér ház"]),
    (38.9, -77.0, ["washington"], []), (40.7, -74.0, ["new york", "manhattan"], []),
    (36.8, -119.4, ["california", "los angeles"], ["kalifornia"]), (31.0, -100.0, ["texas"], []), (27.8, -81.7, ["florida"], []),
    (49.0, 32.0, ["ukraine", "kyiv", "kiev"], ["ukrajna", "kijev"]),
    (61.5, 105.3, ["russia", "moscow", "kremlin"], ["oroszország", "moszkva", "kreml"]),
    (35.9, 104.2, ["china", "beijing"], ["kína", "peking"]),
    (31.0, 34.8, ["israel", "tel aviv", "jerusalem"], ["izrael", "jeruzsálem"]),
    (31.4, 34.4, ["gaza"], ["gáza"]), (32.4, 53.7, ["iran", "tehran"], ["irán", "teherán"]),
    (34.8, 38.9, ["syria"], ["szíria"]), (39.0, 35.2, ["turkey", "ankara", "istanbul"], ["törökország", "isztambul"]),
    (20.6, 78.9, ["india", "new delhi"], []), (36.2, 138.3, ["japan", "tokyo"], ["japán", "tokió"]),
    (36.5, 127.9, ["south korea", "seoul"], ["dél-korea", "szöul"]), (40.3, 127.5, ["north korea"], ["észak-korea"]),
    (23.7, 121.0, ["taiwan"], ["tajvan"]), (-25.3, 133.8, ["australia"], ["ausztrália"]),
    (56.1, -106.3, ["canada"], ["kanada"]), (23.6, -102.6, ["mexico"], ["mexikó"]),
    (-14.2, -51.9, ["brazil"], ["brazília"]), (-38.4, -63.6, ["argentina"], ["argentína"]),
    (6.4, -66.6, ["venezuela"], []), (21.5, -77.8, ["cuba"], ["kuba"]),
    (54.0, -2.0, ["united kingdom", "britain", "england", "london"], ["egyesült királyság", "nagy-britannia", "anglia", "london"]),
    (46.2, 2.2, ["france", "paris"], ["franciaország", "párizs"]),
    (51.2, 10.5, ["germany", "berlin"], ["németország", "berlin"]),
    (41.9, 12.6, ["italy", "rome"], ["olaszország", "róma"]), (40.5, -3.7, ["spain", "madrid"], ["spanyolország"]),
    (51.9, 19.1, ["poland", "warsaw"], ["lengyelország", "varsó"]), (47.5, 14.5, ["austria", "vienna"], ["ausztria", "bécs"]),
    (46.1, 14.9, ["slovenia", "ljubljana"], ["szlovénia"]), (48.7, 19.7, ["slovakia"], ["szlovákia", "pozsony"]),
    (45.9, 25.0, ["romania", "bucharest"], ["románia", "bukarest"]), (44.0, 21.0, ["serbia", "belgrade"], ["szerbia", "belgrád"]),
    (45.1, 15.2, ["croatia", "zagreb"], ["horvátország"]), (49.8, 15.5, ["czech", "prague"], ["csehország", "prága"]),
    (50.85, 4.35, ["brussels", "european union"], ["brüsszel", "európai unió"]),
    (39.1, 21.8, ["greece", "athens"], ["görögország", "athén"]),
    (26.8, 30.8, ["egypt", "cairo"], ["egyiptom", "kairó"]), (-30.6, 22.9, ["south africa"], ["dél-afrika"]),
    (9.1, 8.7, ["nigeria"], ["nigéria"]), (23.9, 45.1, ["saudi arabia", "saudi"], ["szaúd"]),
    (30.4, 69.3, ["pakistan"], ["pakisztán"]), (33.9, 67.7, ["afghanistan"], ["afganisztán"]),
    (33.2, 43.7, ["iraq", "baghdad"], ["irak", "bagdad"]), (33.9, 35.9, ["lebanon", "beirut"], ["libanon", "bejrút"]),
    (15.6, 48.5, ["yemen"], ["jemen"]), (12.9, 30.2, ["sudan"], ["szudán"]), (9.1, 40.5, ["ethiopia"], ["etiópia"]),
    (-0.8, 113.9, ["indonesia"], ["indonézia"]), (15.9, 101.0, ["thailand"], ["thaiföld"]),
    (12.9, 121.8, ["philippines"], ["fülöp-szigetek"]), (14.1, 108.3, ["vietnam"], ["vietnam"]),
    (47.2, 19.5, ["hungary", "budapest"], ["magyarország"]),
]


def _compile(entries):
    pats, coords = [], []
    flat = []
    for lat, lng, en, hu in entries:
        for n in en:
            flat.append((n, lat, lng, False))
        for n in hu:
            flat.append((n, lat, lng, True))
    flat.sort(key=lambda x: -len(x[0]))
    for name, lat, lng, suffix in flat:
        tail = r"\w{0,8}(?!\w)" if suffix else r"(?!\w)"
        body = re.escape(name)
        if suffix and name[-1] in "ae":  # Ukrajna → Ukrajnában (a→á), Görögország nem érintett
            body = re.escape(name[:-1]) + ("[aá]" if name[-1] == "a" else "[eé]")
        pats.append("(" + body + tail + ")")
        coords.append((lat, lng))
    if not pats:
        return None, coords
    return re.compile(r"(?<!\w)(?:" + "|".join(pats) + ")"), coords


_TOWN_RX = {k: _compile(v) for k, v in TOWNS.items()}
_COUNTRY_RX = _compile(COUNTRIES)


def _search(compiled, text):
    rx, coords = compiled
    if rx is None:
        return None
    m = rx.search(text)
    return coords[m.lastindex - 1] if m else None


def _jitter(item_id: str, spread: float):
    h = int(hashlib.md5(item_id.encode()).hexdigest()[:8], 16)
    return ((h & 0xFFFF) / 65535 - 0.5) * spread, (((h >> 16) & 0xFFFF) / 65535 - 0.5) * spread * 1.3


def locate(item: dict, centers: dict, fallback_regions: set):
    """(lat, lng) vagy None. Város → (HU-NAT/INT esetén) ország → régióközpont."""
    text = item.get("title", "").lower()
    code = item["region"]
    spread = 0.3
    hit = _search(_TOWN_RX.get(code, (None, [])), text) if code in _TOWN_RX else None
    if hit is None and code in ("HU-NAT", "INT"):
        hit = _search(_COUNTRY_RX, text)
        spread = 4.0
    if hit is None and code in fallback_regions and code in centers:
        hit = tuple(centers[code])
        spread = 0.5
    if hit is None:
        return None
    dlat, dlng = _jitter(item["id"], spread)
    return round(hit[0] + dlat, 3), round(hit[1] + dlng, 3)


def attach(item: dict, centers: dict, fallback_regions: set) -> dict:
    pos = locate(item, centers, fallback_regions)
    if pos:
        item["lat"], item["lng"] = pos
    else:
        item.pop("lat", None)
        item.pop("lng", None)
    return item
