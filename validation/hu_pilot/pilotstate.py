"""Pilot-állapot: egy oldalon megmondja, hol tart a pilot, és mi a következő lépés. Csak olvas (a results/ mappát, a megadott exportokat), nincs hálózat, nem módosít semmit.
Mutatja: kiválasztás, csomagok (a zip lenyomata a jegyzékkel), szavazatok betűnként a horgony- / mérési / külföldi körben, a kapu, a lezárás, a modellfuttatások. Szavazóról csak a betű szerepel.
A Cloudflare-on lévő verziót innen nem látja: azt a felhasználónak kell megnéznie (HÍREK száma, v47.12).
Parancssor: python -m validation.hu_pilot.pilotstate [--exports EXPORT...] [--results MAPPA] [--json]"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from . import analysis
from .paths import load_config, results_dir

STAGES = {"1": "horgonykör (20 magyar cím)", "2": "mérési kör (30 magyar cím)", "4": "külföldi kör (en, de, sl)"}


def _json(p):
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def collect(rdir, cfg, export_paths):
    f = cfg["files"]
    info = {"selection": _json(rdir / f["selection"]), "analysis": _json(rdir / f["analysis"]), "frozen": (rdir / f["freeze"]).exists(), "stages": {}, "runs": [], "votes": None}
    for s in STAGES:
        zp, mp = rdir / cfg["deploy"]["dir"] / f"mz_pilot_stage{s}.zip", rdir / cfg["deploy"]["dir"] / f"stage{s}_manifest.json"
        man = _json(mp)
        info["stages"][s] = {"zip": zp.exists(), "manifest": man is not None,
                             "sha_ok": bool(zp.exists() and man and hashlib.sha256(zp.read_bytes()).hexdigest() == man.get("zip_sha256"))}
    rd = rdir / f["model_runs_dir"]
    if rd.is_dir():
        for d in sorted(rd.iterdir()):
            st = _json(d / "state.json")
            if st:
                info["runs"].append({"name": d.name, "provider": st.get("provider"), "status": st.get("status"), "titles": len(st.get("ids", []))})
    if export_paths and info["selection"]:
        votes, rep = analysis.parse_exports(export_paths, cfg)
        sel = info["selection"]
        groups = {"anchors": set(sel["anchor_ids"]), "measured": set(sel["measured_ids"]), **{f"foreign_{l}": set(v) for l, v in (sel.get("foreign_ids") or {}).items()}}
        counts = {}
        for v in votes:
            for g, ids in groups.items():
                if v["id"] in ids:
                    counts.setdefault(v["voter"], {}).setdefault(g, set()).add(v["id"])
        info["votes"] = {"sizes": {g: len(ids) for g, ids in groups.items()}, "by_voter": {x: {g: len(s) for g, s in gs.items()} for x, gs in sorted(counts.items())}}
    return info


def assess(info, cfg):
    sel, an = info["selection"], info["analysis"]
    need = cfg["gate"]["min_voters"]
    out = {"selection": None, "stages": info["stages"], "votes": info["votes"], "gate": None, "frozen": info["frozen"], "runs": info["runs"], "complete": {}, "next": [], "notes": []}
    nxt = out["next"]
    if not sel:
        nxt.append("Nincs kiválasztás: `python -m validation.hu_pilot.run select` (vagy a már leszavazott horgonyokkal `select --anchors-from EXPORT...`).")
        return out
    out["selection"] = {"anchors": len(sel["anchor_ids"]), "measured": len(sel["measured_ids"]), "foreign": {l: len(v) for l, v in (sel.get("foreign_ids") or {}).items()}, "reselection": "reselection" in sel}
    missing = [f"{s}. szakasz" for s, st in info["stages"].items() if not (st["zip"] and st["manifest"])]
    bad = [f"{s}. szakasz" for s, st in info["stages"].items() if st["zip"] and st["manifest"] and not st["sha_ok"]]
    if missing:
        nxt.append(f"Hiányzó csomag: {', '.join(missing)}: `python -m validation.hu_pilot.run package --app-dir PUBLIC_MAPPA --stage N`.")
    if bad:
        nxt.append(f"A zip lenyomata nem egyezik a jegyzékkel: {', '.join(bad)}: ne töltsd fel; csomagold újra.")
    out["notes"].append("A Cloudflare-on lévő verziót innen nem látom: nézd meg a telefonon (HÍREK száma, v47.12), vagy futtasd a Telepítés-ellenőrt a zipre.")
    v = info["votes"]
    if v is None:
        nxt.append("Add meg a szavazói exportokat (`--exports ...`), hogy lássam a szavazás állását.")
    else:
        for g in ("anchors", "measured"):
            full = [x for x, gs in v["by_voter"].items() if gs.get(g, 0) >= v["sizes"][g] > 0]
            out["complete"][g] = full
        a_full, m_full = out["complete"]["anchors"], out["complete"]["measured"]
        if len(a_full) < need:
            nxt.append(f"A horgonykör szavazása még nem teljes: kész {len(a_full)} / {need} szavazó ({', '.join(a_full) or '–'}).")
        elif len(m_full) < need:
            todo = [x for x in v["by_voter"] if x not in m_full] or ["senki"]
            nxt.append(f"A mérési kör szavazása folyamatban: kész {len(m_full)} / {need} szavazó ({', '.join(m_full) or '–'}); hiányzik: {', '.join(todo)}. Mindenki a saját betűjével, egyedül szavaz.")
        elif an is None:
            nxt.append(f"A kapuhoz szükséges {need} szavazó kész a mérési körrel ({', '.join(m_full)}): `python -m validation.hu_pilot.run analyze EXPORT...` (a kapu a mérési kör szavazóinak közös alfáján dönt).")
    if an:
        g = an["gate"]
        out["gate"] = {"decision": g.get("decision"), "alpha": g.get("alpha"), "alpha_min": g.get("alpha_min"), "voters": g.get("voters"), "warnings": g.get("warnings")}
        d = g.get("decision")
        if d in ("atment", "eldonthetetlen") and not info["frozen"]:
            nxt.append("A kapu " + ("átment" if d == "atment" else "eldönthetetlen") + ": a lezárás a felhasználó döntése (`python -m validation.hu_pilot.run freeze EXPORT...`).")
        elif d == "elbukott":
            nxt.append("A kapu elbukott: közös szabály, újraszavazás vagy harmadik szavazat; a felhasználó dönt. A lezárás nem lehetséges.")
        elif d == "nem_szamolhato":
            nxt.append("A kapu nem számolható (kevés szavazó vagy adat): hiányzik valakinek a szavazata.")
    if info["frozen"] and not info["runs"]:
        nxt.append("Lezárva. Következő: `python -m validation.hu_pilot.run export-bundle`, majd az éles futás: azt csak a felhasználó indíthatja (kézi munkafolyamat, jóváhagyással).")
    for r in info["runs"]:
        if r["status"] == "stopped_quota":
            nxt.append(f"A(z) {r['name']} futás kvótamegállt: nézd meg a Kvótafigyelővel, mikor folytatható.")
    if not nxt:
        nxt.append("Nincs függő lépés.")
    return out


def render(out):
    L = ["=== PILOT-ÁLLAPOT ==="]
    s = out["selection"]
    L.append("Kiválasztás: " + ("nincs" if not s else f"{s['anchors']} horgony, {s['measured']} mérési, külföldi {s['foreign']}" + (" (újrakiválasztott)" if s["reselection"] else "")))
    for k, st in out["stages"].items():
        L.append(f"  {k}. szakasz ({STAGES[k]}): zip {'van' if st['zip'] else 'nincs'}, jegyzék {'van' if st['manifest'] else 'nincs'}, lenyomat {'rendben' if st['sha_ok'] else 'nem ellenőrizhető/eltér'}")
    if out["votes"]:
        L.append("Szavazatok (csak betűk):")
        for x, gs in out["votes"]["by_voter"].items():
            L.append(f"  {x}: " + ", ".join(f"{g} {gs[g]}/{size}" for g, size in out["votes"]["sizes"].items() if g in gs))
    if out["gate"]:
        g = out["gate"]
        L.append(f"Kapu: {g['decision']} (alfa {g['alpha']}, küszöb {g['alpha_min']})")
    L.append("Lezárva: " + ("igen" if out["frozen"] else "nem"))
    for r in out["runs"]:
        L.append(f"Futás: {r['name']} ({r['provider']}): {r['status']}")
    L.append("Következő lépés:")
    L += [f"  - {x}" for x in out["next"]]
    L += [f"Megjegyzés: {x}" for x in out["notes"]]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exports", nargs="*", default=[])
    ap.add_argument("--results")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_config()
    try:
        out = assess(collect(results_dir(cfg, a.results), cfg, a.exports), cfg)
    except (FileNotFoundError, ValueError, KeyError) as e:
        print(f"NEM OLVASHATÓ: {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=1) if a.json else render(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
