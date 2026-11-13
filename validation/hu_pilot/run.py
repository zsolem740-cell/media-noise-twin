"""A magyar pilot parancssora. Modellt és hálózatot nem használ.

  python -m validation.hu_pilot.run select                  kiválasztás + pilot-feed fájlok + horgony-előnézet (results/)
  python -m validation.hu_pilot.run analyze EXPORT...       kappa, egyezés, kapu, harmadik szavazat listája (results/analysis.json, human_reference.csv)
  python -m validation.hu_pilot.run adjudication EXPORT...  a harmadik szavazathoz kell feed (csak azok a mérési címek, ahol az elsődleges páros eltér)
  python -m validation.hu_pilot.run freeze EXPORT...        a címkézés lezárása (csak ha a kapu átment vagy eldönthetetlen); a modellfuttatás ezt várja"""
import json
import sys
from pathlib import Path

from . import analysis, feeds, freeze, selection
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
    feeds.write_json(f["stage1"], feeds.build_feed(s["anchors"], "stage1-anchors"), rdir)
    feeds.write_json(f["stage2"], feeds.build_feed(s["measured"], "stage2-measured"), rdir)
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
    _, items = selection.load_feed(feed_path or REPO_ROOT / cfg["feed"])
    by = {i["id"]: i for i in items}
    feeds.write_json(f["stage3"], feeds.build_feed([by[i] for i in ids], "stage3-adjudication"), rdir)
    return {"adjudication_titles": len(ids)}


def do_freeze(cfg, exports, base=None):
    rdir, f, sel, votes, rep = _load(cfg, exports, base)
    res = analysis.analyze(votes, rep, sel, cfg)
    ref = analysis.write_reference_csv(votes, set(sel["measured_ids"]), f["reference"], rdir)
    return freeze.freeze(rdir, cfg, exports, sel, res, ref)


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
    else:
        print(__doc__)
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=1, default=list))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
