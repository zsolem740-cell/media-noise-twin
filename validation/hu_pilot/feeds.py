"""A pilot-feed fájlok: semleges mezőkkel (nincs szabály- vagy AI-pontszám, nincs valódi forrás vagy helyadat), hogy vak módban sem a fájlból, sem a felületről nem szivároghat semmi.
Az azonosító a valós hírmentésé (a későbbi kizáráshoz), a cím változatlan."""
import hashlib
import json

from .paths import check_write

NEUTRAL_KEYS = ("ATM", "G", "S", "S0", "V", "V0", "lat", "lng")
ROW_KEYS = {"ATM", "G", "S", "S0", "V", "V0", "alert", "id", "lat", "link", "lng", "official", "published", "region", "source", "source_domain", "summary", "title"}


def neutral_row(item):
    r = {k: 0 for k in NEUTRAL_KEYS}
    r.update({"alert": False, "official": False, "id": item["id"], "link": "", "published": "2000-01-01T00:00:00Z", "region": "HU",
              "source": "pilot", "source_domain": "pilot.hu", "summary": "", "title": item["title"]})
    return r


def zeroed(v):
    """Ugyanolyan szerkezet, semleges értékekkel: a szótárak kulcsai megmaradnak, a listák üresek, a számok 0, a szövegek üresek."""
    if isinstance(v, dict):
        return {k: zeroed(x) for k, x in v.items()}
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return 0
    if isinstance(v, str):
        return ""
    return [] if isinstance(v, list) else None


def build_feed(items, stage, template):
    """Pilot-feed. A template az eredeti hírmentés: belőle csak az alkalmazás működéséhez kell a `model` (szabály- és súlykonfiguráció, nincs benne hír vagy pontszám) szó szerint,
    a többi felső szintű mező (summary, insights, notified, config, research) szerkezethű, de nullázott. Profilok, pontszámok, források nincsenek."""
    if not isinstance(template, dict) or not isinstance(template.get("model"), dict):
        raise ValueError("a template nem hírmentés (hiányzik a model)")
    out = {"schema": template.get("schema", 1), "generated_at": "2000-01-01T00:00:00Z", "pilot": stage, "model": json.loads(json.dumps(template["model"])),
           "profiles": {}, "items": [neutral_row(i) for i in items], "health": []}
    for k in ("summary", "insights", "notified", "config", "research"):
        out[k] = zeroed(template.get(k, {}))
    return out


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path, obj, rdir):
    p = check_write(path, rdir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    return p
