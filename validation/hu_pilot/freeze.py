"""A címkézés lezárása: az exportok, a cím-azonosítók és a referencia hash-e. A modellfuttatás csak érvényes lezárási jegyzékkel indulhat."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .paths import check_write


class NotFrozen(Exception):
    pass


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def freeze(rdir, cfg, export_paths, sel, analysis, reference_csv, now=None):
    if analysis["gate"]["decision"] not in ("atment", "eldonthetetlen"):
        raise NotFrozen(f"a kapu állapota: {analysis['gate']['decision']}; a lezárás nem lehetséges")
    man = {"created_utc": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"), "gate": analysis["gate"], "voters": analysis["voters"],
           "exports": [{"name": Path(p).name, "sha256": sha256_file(p)} for p in export_paths],
           "anchor_ids": sorted(sel["anchor_ids"]), "measured_ids": sorted(sel["measured_ids"]),
           "reference_csv": {"name": Path(reference_csv).name, "sha256": sha256_file(reference_csv)}}
    p = check_write(Path(rdir) / cfg["files"]["freeze"], rdir)
    if p.exists():
        raise FileExistsError("a lezárási jegyzék már létezik: nem írjuk felül")
    p.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    return man


def require_freeze(rdir, cfg, export_paths=()):
    """A modellfuttatás kapuja: lezárási jegyzék nélkül, vagy ha a fájlok azóta változtak, kivételt dob."""
    p = Path(rdir) / cfg["files"]["freeze"]
    if not p.exists():
        raise NotFrozen("nincs lezárási jegyzék: a címkézés nincs lezárva, modell nem indítható")
    man = json.loads(p.read_text(encoding="utf-8"))
    ref = Path(rdir) / man["reference_csv"]["name"]
    if not ref.exists() or sha256_file(ref) != man["reference_csv"]["sha256"]:
        raise NotFrozen("a referencia-fájl hiányzik vagy megváltozott a lezárás óta")
    known = {e["name"]: e["sha256"] for e in man["exports"]}
    for q in export_paths:
        if known.get(Path(q).name) != sha256_file(q):
            raise NotFrozen(f"az export nem egyezik a lezárt változattal: {Path(q).name}")
    return man
