"""Telepítés-ellenőr: egy szakasz zipjét ellenőrzi feltöltés előtt, a jegyzékhez és a kiválasztáshoz képest. Csak olvas, nem telepít, nincs hálózat.
Ellenőrzi: a zip SHA-256 egyezik a jegyzékkel; a fájlok egyenként egyeznek a jegyzék lenyomataival; biztonságos útvonalak; kötelező fájlok; a `_headers` tartalma;
a feed `pilot` mezője és a címek azonosítói pontosan a szakaszéi (sorrendre is); a sorok semleges mezői (nincs valódi forrás, link, pontszám); a szakaszok közt nincs közös cím; az alkalmazás verziója.
Parancssor: python -m validation.hu_pilot.deploycheck 1|2|4 [--zip UT.zip] [--results MAPPA]   (kilépési kód: 0 rendben, 1 hiba, 2 nem olvasható)"""
import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

from . import packaging
from .paths import load_config, results_dir

REQUIRED = ("index.html", "atm_history.json", "_headers", "robots.txt")
PILOT = {"1": "stage1-anchors", "2": "stage2-measured", "4": "stage4-foreign"}
NEUTRAL_NUMBERS = ("ATM", "G", "S", "S0", "V", "V0", "lat", "lng")


def expected_ids(stage, sel):
    return {"1": sel["anchor_ids"], "2": sel["measured_ids"], "4": sel.get("foreign_order") or []}[str(stage)]


def run_checks(zip_path, manifest, stage, sel, cfg):
    stage = str(stage)
    out = []

    def chk(name, ok, detail=""):
        out.append({"check": name, "ok": bool(ok), "detail": detail})

    zp = Path(zip_path)
    raw = zp.read_bytes()
    chk("zip_sha256_egyezik_a_jegyzekkel", hashlib.sha256(raw).hexdigest() == manifest.get("zip_sha256"), f"{hashlib.sha256(raw).hexdigest()[:12]}… / jegyzék: {str(manifest.get('zip_sha256'))[:12]}…")
    try:
        zf = zipfile.ZipFile(zp)
    except zipfile.BadZipFile:
        chk("zip_olvashato", False, "nem érvényes zip")
        return out
    names = [n for n in zf.namelist() if not n.endswith("/")]
    unsafe = [n for n in names if n.startswith("/") or ".." in n.split("/") or "\\" in n]
    chk("biztonsagos_utvonalak", not unsafe and len(names) == len(set(names)), f"{len(names)} fájl" + (f", gyanús: {unsafe[:3]}" if unsafe else ""))
    chk("kotelezo_fajlok", all(r in names for r in REQUIRED), f"hiányzik: {[r for r in REQUIRED if r not in names]}")
    files = manifest.get("files") or {}
    same_set = set(files) == set(names)
    bad_hash = [n for n in names if n in files and hashlib.sha256(zf.read(n)).hexdigest() != files[n]]
    chk("fajlok_egyeznek_a_jegyzek_lenyomataival", same_set and not bad_hash, f"eltérő: {bad_hash[:3]}; fájlkészlet {'egyezik' if same_set else 'ELTÉR'}")
    chk("headers_fajl_a_csomagolo_szerint", "_headers" in names and zf.read("_headers").decode("utf-8") == packaging.HEADERS, "")
    where = " ".join(zf.read(n).decode("utf-8", "replace") for n in ("index.html", "js/modules/diag.js") if n in names)
    want = cfg["deploy"]["app_version"]
    chk("alkalmazas_verzioja", manifest.get("app_version") == want and want in where, f"elvárt: {want}, jegyzék: {manifest.get('app_version')}")
    try:
        feed = json.loads(zf.read("atm_history.json").decode("utf-8"))
    except (KeyError, ValueError):
        chk("feed_olvashato", False, "atm_history.json hiányzik vagy nem JSON")
        return out
    chk("feed_pilot_mezo", feed.get("pilot") == PILOT[stage], f"{feed.get('pilot')} / elvárt: {PILOT[stage]}")
    items = feed.get("items") or []
    ids = [i.get("id") for i in items]
    exp = expected_ids(stage, sel)
    chk("cimek_pontosan_a_szakaszeiv_sorrendre_is", ids == exp, f"{len(ids)} cím / elvárt: {len(exp)}" + ("" if ids == exp else f"; hiányzik {len(set(exp) - set(ids))}, felesleges {len(set(ids) - set(exp))}"))
    bad = [i.get("id") for i in items if not (i.get("source") == "pilot" and i.get("source_domain") == "pilot.invalid" and i.get("link") == "" and i.get("summary") == ""
                                              and i.get("alert") is False and i.get("official") is False and all(i.get(k) == 0 for k in NEUTRAL_NUMBERS) and str(i.get("title") or "").strip())]
    chk("sorok_semlegesek_nincs_forras_link_pontszam", not bad, f"nem semleges sorok: {bad[:3]}")
    groups = {"1": set(sel["anchor_ids"]), "2": set(sel["measured_ids"]), "4": set(sel.get("foreign_order") or [])}
    others = set().union(*(v for k, v in groups.items() if k != stage))
    chk("nincs_kozos_cim_a_tobbi_szakasszal", not (set(ids) & others), f"közös: {len(set(ids) & others)}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stage", choices=sorted(PILOT))
    ap.add_argument("--zip")
    ap.add_argument("--results")
    a = ap.parse_args(argv)
    cfg = load_config()
    rdir = results_dir(cfg, a.results)
    try:
        sel = json.loads((rdir / cfg["files"]["selection"]).read_text(encoding="utf-8"))
        manifest = json.loads((rdir / cfg["deploy"]["dir"] / f"stage{a.stage}_manifest.json").read_text(encoding="utf-8"))
        zp = Path(a.zip) if a.zip else rdir / cfg["deploy"]["dir"] / f"mz_pilot_stage{a.stage}.zip"
        checks = run_checks(zp, manifest, a.stage, sel, cfg)
    except (FileNotFoundError, ValueError, KeyError) as e:
        print(f"NEM OLVASHATÓ: {e}", file=sys.stderr)
        return 2
    ok = all(c["ok"] for c in checks)
    print(f"=== TELEPÍTÉS-ELLENŐR: {a.stage}. szakasz ({zp.name}) ===")
    for c in checks:
        print(f"[{'OK' if c['ok'] else 'HIBA'}] {c['check']}: {c['detail']}")
    print("RENDBEN" if ok else "HIBA: ne töltsd fel")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
