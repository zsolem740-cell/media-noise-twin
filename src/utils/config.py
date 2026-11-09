"""Beállítások: alapérték (config/sources.json, a projekttel jön) + saját felülírás (config/user.json a repóban).

A saját fájl csak azt tartalmazza, amit módosítani akarsz; hibás fájl esetén az alapbeállítás marad érvényben,
és a hibaüzenet az adatban (és az alkalmazás szerver-elemzés paneljén) is megjelenik.

Felülírási szabályok:
  - objektum: mezőnként összefésül;  lista: teljesen lecserél
  - "<kulcs>_add": elemek hozzáadása a listához,  "<kulcs>_remove": elemek törlése
  - "regions": {"HU-VA": {"weight": 0.9, "queries_add": ["Zalaegerszeg"]}} – régiónként, kóddal
      "enabled": false kikapcsolja a régiót; ismeretlen kód = új régió (teljes leírással)
  - "trust": új szint a hivatalos után kerül, így felülírja a beépített sajtószinteket
  - "clickbait_add": ["leleplezte"] – új kulcsszavak a szenzációszinthez
  - "exclude_domains_add": ["pelda.com"] – kizárt források (az EU-s látogatókat blokkoló, képaláírás-szemetet adó oldalak); "exclude_domains_remove" visszaveszi
"""
import copy
import json
from pathlib import Path

from src.utils import text_cleaner

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "config" / "sources.json"
USER = ROOT / "config" / "user.json"


def merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if k.endswith("_add") and isinstance(v, list):
            key = k[:-4]
            cur = out.get(key, [])
            out[key] = cur + [x for x in v if x not in cur]
        elif k.endswith("_remove") and isinstance(v, list):
            key = k[:-7]
            out[key] = [x for x in out.get(key, []) if x not in v]
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _apply_regions(base: list[dict], over) -> list[dict]:
    if isinstance(over, list):
        return copy.deepcopy(over)
    if not isinstance(over, dict):
        raise ValueError('a "regions" objektum vagy lista legyen')
    regions = copy.deepcopy(base)
    for code, patch in over.items():
        if not isinstance(patch, dict):
            raise ValueError(f'a "{code}" régió leírása objektum legyen')
        i = next((n for n, r in enumerate(regions) if r["code"] == code), None)
        if i is None:
            regions.append({"code": code, **copy.deepcopy(patch)})
        else:
            regions[i] = merge(regions[i], patch)
    return [r for r in regions if r.get("enabled", True)]


def _order_trust(trust: dict, base_keys: list[str]) -> dict:
    """official → a felhasználó új szintjei → a beépített szintek → default."""
    new = [k for k in trust if k not in base_keys and k != "default"]
    order = [k for k in ("official",) if k in trust] + new + [k for k in base_keys if k not in ("official", "default") and k in trust] + ["default"]
    return {k: trust[k] for k in order if k in trust}


def validate(cfg: dict) -> None:
    rs = cfg.get("research")
    if rs is not None:
        if not isinstance(rs, dict) or not isinstance(rs.get("companies", []), list):
            raise ValueError('a "research" objektum legyen, benne a "companies" lista')
        for co in rs.get("companies", []):
            if not (isinstance(co, dict) and isinstance(co.get("id"), str) and isinstance(co.get("symbol"), str) and isinstance(co.get("names", []), list)):
                raise ValueError('minden "research.companies" elemhez kell "id", "symbol" és "names" (lista)')
    al = cfg.get("domain_aliases", {})
    if not isinstance(al, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in al.items()):
        raise ValueError('a "domain_aliases" {"regi": "uj"} szótár legyen')
    ex = cfg.get("exclude_domains", [])
    if not isinstance(ex, list) or not all(isinstance(x, str) for x in ex):
        raise ValueError('az "exclude_domains" szövegek listája legyen')
    if not cfg["regions"]:
        raise ValueError("legalább egy régió kell")
    for r in cfg["regions"]:
        for key in ("code", "name", "weight", "lang", "queries", "geofence"):
            if key not in r:
                raise ValueError(f'a "{r.get("code", "?")}" régióból hiányzik: {key}')
        if not isinstance(r["weight"], (int, float)):
            raise ValueError(f'a "{r["code"]}" súlya szám legyen')
        for key in ("hl", "gl", "ceid"):
            if key not in r["lang"]:
                raise ValueError(f'a "{r["code"]}" lang részéből hiányzik: {key}')
        if not isinstance(r["queries"], list) or not isinstance(r["geofence"], list):
            raise ValueError(f'a "{r["code"]}" queries és geofence listája lista legyen')
    for name, t in cfg["trust"].items():
        if name == "default":
            if not isinstance(t, (int, float)):
                raise ValueError('a trust.default szám legyen')
            continue
        if not isinstance(t.get("value"), (int, float)) or not isinstance(t.get("domains"), list):
            raise ValueError(f'a "{name}" szintnek value (szám) és domains (lista) kell')
    for key in ("retention", "thresholds", "article", "notify"):
        if not isinstance(cfg.get(key), dict):
            raise ValueError(f'hiányzik vagy nem objektum: {key}')


def load_config(base_path: Path = BASE, user_path: Path = USER) -> tuple[dict, dict]:
    """(beállítás, állapot). Az állapot bekerül az adatba: {user, warning, applied}."""
    base = json.loads(base_path.read_text(encoding="utf-8"))
    status = {"user": False, "warning": None, "applied": []}
    cfg = base
    if user_path.exists():
        try:
            over = json.loads(user_path.read_text(encoding="utf-8"))
            if not isinstance(over, dict):
                raise ValueError("a fájl tartalma JSON objektum legyen")
            rest = {k: v for k, v in over.items() if k != "regions"}
            cand = merge(base, rest)
            if "regions" in over:
                cand["regions"] = _apply_regions(base["regions"], over["regions"])
            cand["trust"] = _order_trust(cand["trust"], list(base["trust"]))
            validate(cand)
            cfg = cand
            status = {"user": True, "warning": None, "applied": sorted(over.keys())}
        except Exception as exc:  # hibás saját fájl: az alapbeállítás marad
            status = {"user": False, "warning": f"{type(exc).__name__}: {exc}", "applied": []}
            cfg = base
    text_cleaner.set_extra_keywords(cfg.get("clickbait", []))
    return cfg, status
