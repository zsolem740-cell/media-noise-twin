"""A magyar pilot parancssora. Modellt és hálózatot nem használ.

  python -m validation.hu_pilot.run select                  kiválasztás + pilot-feed fájlok + horgony-előnézet (results/)
  python -m validation.hu_pilot.run analyze EXPORT...       kappa, egyezés, kapu, harmadik szavazat listája (results/analysis.json, human_reference.csv)
  python -m validation.hu_pilot.run adjudication EXPORT...  a harmadik szavazathoz kell feed (csak azok a mérési címek, ahol az elsődleges páros eltér)
  python -m validation.hu_pilot.run package --app-dir PUBLIC_MAPPA --stage 1|2|3 [--app-commit SHA]   telepíthető csomag (Cloudflare Pages): app + szakasz-feed, ellenőrzéssel és ZIP-pel; nem telepít
  python -m validation.hu_pilot.run model-dryrun gemini|groq  a 50 modellkérés előállítása és ellenőrzése, hálózat és kulcs nélkül (modellfuttatás NINCS a parancssorban)
  python -m validation.hu_pilot.run freeze EXPORT...        a címkézés lezárása (csak ha a kapu átment vagy eldönthetetlen); a modellfuttatás ezt várja"""
import json
import sys
from pathlib import Path

from . import analysis, feeds, freeze, modelrun, packaging, selection
from .paths import REPO_ROOT, check_write, load_config, results_dir


def _paths(cfg, base=None):
    rdir = results_dir(cfg, base)
    return rdir, {k: rdir / v for k, v in cfg["files"].items()}


def do_select(cfg, feed_path=None, base=None):
    rdir, f = _paths(cfg, base)
    feed, items = selection.load_feed(feed_path or REPO_ROOT / cfg["feed"])
    override = None
    op = rdir / "anchors_override.json"
    if op.exists():
        override = json.loads(op.read_text(encoding="utf-8"))
    for k in ("selection", "stage1", "stage2"):
        if f[k].exists():
            raise FileExistsError(f"{f[k].name} már létezik: a kiválasztás nem íródik felül")
    s = selection.select(items, cfg, override)
    sel = {"seed": cfg["seed"], "feed_generated_at": feed.get("generated_at"), "pool": s["pool"], "enriched_pool": s["enriched_pool"], "excluded": s["excluded"],
           "anchor_ids": [i["id"] for i in s["anchors"]], "measured_ids": [i["id"] for i in s["measured"]],
           "measured_random_ids": s["measured_random_ids"], "measured_enriched_ids": s["measured_enriched_ids"], "source_counts": s["source_counts"]}
    feeds.write_json(f["selection"], sel, rdir)
    feeds.write_json(f["stage1"], feeds.build_feed(s["anchors"], "stage1-anchors", feed), rdir)
    feeds.write_json(f["stage2"], feeds.build_feed(s["measured"], "stage2-measured", feed), rdir)
    prev = check_write(f["anchor_preview"], rdir)
    prev.write_text("\n".join(f"{n:2d}. [{i['id']}] {i['title']}" for n, i in enumerate(s["anchors"], 1)) + "\n", encoding="utf-8")
    return {k: sel[k] for k in ("pool", "enriched_pool", "excluded")} | {"anchors": len(sel["anchor_ids"]), "measured": len(sel["measured_ids"])}


def _load(cfg, exports, base=None):
    rdir, f = _paths(cfg, base)
    sel = json.loads(f["selection"].read_text(encoding="utf-8"))
    votes, rep = analysis.parse_exports(exports, cfg)
    return rdir, f, sel, votes, rep


def do_analyze(cfg, exports, base=None):
    rdir, f, sel, votes, rep = _load(cfg, exports, base)
    res = analysis.analyze(votes, rep, sel, cfg)
    feeds.write_json(f["analysis"], res, rdir)
    analysis.write_reference_csv(votes, set(sel["measured_ids"]), f["reference"], rdir)
    return res


def do_adjudication(cfg, exports, feed_path=None, base=None):
    rdir, f, sel, votes, rep = _load(cfg, exports, base)
    ids = analysis.adjudication_ids(analysis.ratings(votes, set(sel["measured_ids"])), cfg["voters"]["primary"])
    feed, items = selection.load_feed(feed_path or REPO_ROOT / cfg["feed"])
    by = {i["id"]: i for i in items}
    feeds.write_json(f["stage3"], feeds.build_feed([by[i] for i in ids], "stage3-adjudication", feed), rdir)
    return {"adjudication_titles": len(ids)}


def do_freeze(cfg, exports, base=None):
    rdir, f, sel, votes, rep = _load(cfg, exports, base)
    res = analysis.analyze(votes, rep, sel, cfg)
    ref = analysis.write_reference_csv(votes, set(sel["measured_ids"]), f["reference"], rdir)
    return freeze.freeze(rdir, cfg, exports, sel, res, ref)


def do_model_dryrun(cfg, provider, base=None):
    """A modellkérések előállítása és ellenőrzése HÁLÓZAT ÉS KULCS NÉLKÜL (a 50 pilotcím, egy cím egy kérésben). Modellfuttatást nem indít."""
    rdir = results_dir(cfg, base)
    titles = modelrun.load_titles(rdir, cfg)
    rows = modelrun.build_requests(titles, provider, cfg)
    p = check_write(rdir / cfg["files"]["model_dryrun"].format(provider=provider), rdir)
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    rows2 = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    errs = modelrun.verify_requests(rows2, titles, provider, cfg)
    return {"provider": provider, "n_requests": len(rows2), "no_network": True, "api_key_used": False, "mode": "egy cím egy kérésben", "errors": errs,
            "prompt_sha256": modelrun.V.sha256_text(modelrun.P.SYSTEM_INSTRUCTION), "status": "OK" if not errs else "HIBA"}


def do_package(cfg, app_dir, stage, app_commit=None, base=None):
    """A telepíthető csomag egy szakaszra (1 horgony, 2 mérési, 3 harmadik szavazat): a v47.10 public/ mappa + a szakasz pilot-feedje, ellenőrzéssel és ZIP-pel. Nem telepít."""
    rdir, f = _paths(cfg, base)
    key = {"1": "stage1", "2": "stage2", "3": "stage3"}[str(stage)]
    feed = json.loads(f[key].read_text(encoding="utf-8"))
    mine = [i["title"] for i in feed["items"]]
    others = []
    for k in ("stage1", "stage2", "stage3"):
        if k != key and f[k].exists():
            others += [i["title"] for i in json.loads(f[k].read_text(encoding="utf-8"))["items"]]
    if str(stage) == "3":
        others = [t for t in others if t not in set(mine)]
    out = rdir / cfg["deploy"]["dir"] / f"stage{stage}"
    packaging.build_site(app_dir, feed, out, rdir, cfg)
    errs = packaging.verify_site(out, mine, others, cfg)
    zp = packaging.make_zip(out, rdir / cfg["deploy"]["dir"] / f"mz_pilot_stage{stage}.zip", rdir)
    man = packaging.manifest(out, zp, stage, cfg, app_commit)
    feeds.write_json(rdir / cfg["deploy"]["dir"] / f"stage{stage}_manifest.json", man, rdir)
    return {"stage": stage, "titles": len(mine), "files": len(man["files"]), "zip": str(zp.name), "zip_sha256": man["zip_sha256"], "app_version": man["app_version"],
            "errors": errs, "status": "OK" if not errs else "HIBA"}


def main(argv):
    cfg = load_config()
    cmd, rest = (argv[0] if argv else ""), argv[1:]
    if cmd == "select" and not rest:
        out = do_select(cfg)
    elif cmd == "analyze" and rest:
        r = do_analyze(cfg, rest)
        out = {"gate": r["gate"], "voters": r["voters"], "coverage": r["coverage"], "adjudication_titles": len(r["adjudication_ids"])}
    elif cmd == "adjudication" and rest:
        out = do_adjudication(cfg, rest)
    elif cmd == "freeze" and rest:
        out = do_freeze(cfg, rest)
    elif cmd == "package" and len(rest) in (4, 6) and rest[0] == "--app-dir" and rest[2] == "--stage" and rest[3] in ("1", "2", "3"):
        commit = rest[5] if len(rest) == 6 and rest[4] == "--app-commit" else None
        out = do_package(cfg, rest[1], rest[3], commit)
    elif cmd == "model-dryrun" and len(rest) == 1 and rest[0] in cfg["model"]["providers"]:
        out = do_model_dryrun(cfg, rest[0])
    else:
        print(__doc__)
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=1, default=list))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
