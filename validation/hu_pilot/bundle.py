"""Futtatási csomag: az 50 cím (azonosító + szöveg) és a lezárás aggregált adata, KÜLÖN fájlban, hogy a modell-futtatás olyan gépen is indulhasson (GitHub Actions),
ahol az emberi szavazatok és a referencia nincs meg. A csomag NEM tartalmaz szavazatot, szavazónkénti címkét vagy címenkénti emberi értéket; csak a lezárás után készíthető.
Hálózat és környezet nincs itt; a csomag saját hash-ét a futtató ellenőrzi."""
import hashlib
import json
from pathlib import Path

from . import modelrun, prompt as P, providers as V
from .freeze import check_manifest, require_freeze

SCHEMA = "hu-pilot-run-bundle-1"
DEFAULT_PATH = Path(__file__).resolve().parent / "run_bundle.json"
FORBIDDEN_KEYS = {"votes", "human_mean", "majority", "ordinal", "voter_profile", "reference", "mids", "skipped"}


class BundleError(Exception):
    pass


def _canon(o):
    return json.dumps(o, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(b):
    return hashlib.sha256(_canon({k: v for k, v in b.items() if k != "sha256"}).encode("utf-8")).hexdigest()


def _walk_keys(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(o, list):
        for x in o:
            yield from _walk_keys(x)


def build_bundle(rdir, cfg):
    man = require_freeze(rdir, cfg)                           # csak érvényes, fájlokkal egyező lezárás után
    titles = modelrun.load_titles(rdir, cfg)
    g = man["gate"]
    freeze = {"created_utc": man["created_utc"], "voters": man["voters"], "anchor_ids": man["anchor_ids"], "measured_ids": man["measured_ids"],
              "gate": {k: g.get(k) for k in ("decision", "basis", "voters", "n_titles", "alpha", "alpha_min", "min_voters", "min_voters_note")},
              "reference_sha256": man["reference_csv"]["sha256"], "exports": [{"sha256": e["sha256"]} for e in man["exports"]]}
    m = cfg["model"]
    b = {"schema": SCHEMA, "titles": titles, "freeze": freeze, "prompt_sha256": V.sha256_text(P.SYSTEM_INSTRUCTION),
         "schema_sha256": V.sha256_text(P.canonical_json(P.gemini_schema(m["max_points_per_signal"]))), "model_config_sha256": V.sha256_text(_canon(m))}
    b["sha256"] = _hash(b)
    return b


def write_bundle(b, path=None):
    p = Path(path) if path else DEFAULT_PATH
    if p.exists():
        raise FileExistsError(f"{p.name} már létezik: nem íródik felül")
    p.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def load_bundle(path, cfg=None):
    try:
        b = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BundleError(f"a futtatási csomag nem olvasható: {e}") from None
    return verify_bundle(b, cfg)


def verify_bundle(b, cfg=None):
    if not isinstance(b, dict) or b.get("schema") != SCHEMA:
        raise BundleError("nem futtatási csomag")
    if b.get("sha256") != _hash(b):
        raise BundleError("a futtatási csomag hash-e nem egyezik (módosították)")
    bad = set(_walk_keys(b)) & FORBIDDEN_KEYS
    if bad:
        raise BundleError(f"a csomag tiltott mezőt tartalmaz: {sorted(bad)}")
    try:
        check_manifest(b["freeze"])
        ids = [t["id"] for t in b["titles"]]
        if sorted(ids) != sorted(b["freeze"]["anchor_ids"] + b["freeze"]["measured_ids"]):
            raise BundleError("a címek azonosítói nem egyeznek a lezárt jegyzékkel")
        for t in b["titles"]:
            V.check_text(t["title"])
    except (KeyError, TypeError):
        raise BundleError("hiányos futtatási csomag") from None
    except V.RequestError as e:
        raise BundleError(f"hibás cím a csomagban: {e}") from None
    if V.sha256_text(P.SYSTEM_INSTRUCTION) != b["prompt_sha256"]:
        raise BundleError("a prompt eltér a csomag készítésekor használttól")
    if cfg is not None and V.sha256_text(_canon(cfg["model"])) != b["model_config_sha256"]:
        raise BundleError("a modell-konfiguráció eltér a csomag készítésekor használttól")
    return b
