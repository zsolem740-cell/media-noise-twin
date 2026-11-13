"""A Webis-validáció parancssora (csak olvasó mód; teljes AI-futtatás nincs benne).

  python -m validation.webis_validation.run verify ARCHÍVUM.zip      MD5 és méret az ismert értékekkel
  python -m validation.webis_validation.run inspect                  mezők, annotátorszám, kizárások, eloszlás (a data/ mappából)
  python -m validation.webis_validation.run sample                   rétegzett minta → results/sample_meta.json, results/model_inputs.jsonl (csak id + cím)
  python -m validation.webis_validation.run evaluate SCORES.jsonl    kiértékelés → results/report.json
  python -m validation.webis_validation.run smoke                    szintetikus adatokon végigfuttatja a láncot próba-pontozóval (tmp mappában)"""
import json
import sys
import tempfile
from pathlib import Path

from . import evaluate as ev
from . import loader, sample, scoring, synthetic
from .isolation import MODULE_DIR, check_read, check_write, load_config


def _dirs(cfg):
    return MODULE_DIR / cfg["paths"]["data_dir"], MODULE_DIR / cfg["paths"]["results_dir"]


def _write_json(path, obj, results_dir):
    p = check_write(path, results_dir)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=list), encoding="utf-8")
    return p


def _load(cfg, data_dir):
    return loader.load(data_dir / cfg["files"]["instances"], data_dir / cfg["files"]["truth"], cfg, data_dir)


def do_sample(cfg, data_dir, results_dir):
    records, lrep = _load(cfg, data_dir)
    picked, srep = sample.stratified_sample(records, cfg)
    srep["corpus_distribution"] = sample.distribution(records, cfg["sample"]["strata"])
    _write_json(results_dir / "sample_meta.json", {"loader": lrep, "sample": srep}, results_dir)
    lines = "\n".join(json.dumps(scoring.build_model_input(r), ensure_ascii=False) for r in picked) + "\n"
    check_write(results_dir / "model_inputs.jsonl", results_dir).write_text(lines, encoding="utf-8")
    return lrep, srep


def do_evaluate(cfg, data_dir, results_dir, scores_path):
    records, _ = _load(cfg, data_dir)
    meta = json.loads(check_read(results_dir / "sample_meta.json", results_dir).read_text(encoding="utf-8"))
    ids = set(meta["sample"]["ids"])
    chosen = [r for r in records if r.id in ids]
    by_id = {r.id: r for r in chosen}
    scores, bad = [], []
    for line in check_read(scores_path, results_dir).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        s = json.loads(line)
        r = by_id.get(s.get("id"))
        errs = scoring.validate_score(s, r.text, cfg) if r else ["ismeretlen azonosító"]
        (bad if errs else scores).append({"id": s.get("id"), "errors": errs} if errs else s)
    rep = ev.evaluate(chosen, scores, cfg)
    rep["invalid_scores"] = bad
    _write_json(results_dir / "report.json", rep, results_dir)
    return rep


def do_smoke():
    cfg = load_config()
    cfg["sample"] = dict(cfg["sample"], size=60, strata=[dict(s, target=t) for s, t in zip(cfg["sample"]["strata"], (15, 15, 15, 15))])
    with tempfile.TemporaryDirectory() as tmp:
        data, results = Path(tmp) / "data", Path(tmp) / "results"
        results.mkdir()
        synthetic.write_corpus(data, n=300, seed=3)
        records, lrep = loader.load(data / "instances.jsonl", data / "truth.jsonl", cfg, data)
        picked, srep = sample.stratified_sample(records, cfg)
        scores = [synthetic.mock_score(r.id, r.text) for r in picked]
        bad = [(s["id"], scoring.validate_score(s, r.text, cfg)) for s, r in zip(scores, picked) if scoring.validate_score(s, r.text, cfg)]
        rep = ev.evaluate(picked, scores, cfg)
        _write_json(results / "smoke_report.json", rep, results)
        return {"MOCK": "szabályalapú próba-pontozó, nem AI és nem mérési eredmény", "loaded": lrep["n_kept"], "sampled": srep["size_actual"],
                "invalid_scores": len(bad), "spearman_vs_truthMean": rep["regression_vs_truthMean"]["spearman"], "kendall": rep["regression_vs_truthMean"]["kendall_tau_b"],
                "accuracy_vs_truthClass": rep["classification_vs_truthClass"]["accuracy"]}


def main(argv):
    cfg = load_config()
    data_dir, results_dir = _dirs(cfg)
    cmd = argv[0] if argv else ""
    if cmd == "verify" and len(argv) == 2:
        print(json.dumps(loader.verify_archive(check_read(argv[1], data_dir), cfg["known_archives"]), indent=1))
    elif cmd == "inspect":
        records, rep = _load(cfg, data_dir)
        rep["corpus_distribution"] = sample.distribution(records, cfg["sample"]["strata"])
        print(json.dumps(rep, ensure_ascii=False, indent=1, default=list))
    elif cmd == "sample":
        lrep, srep = do_sample(cfg, data_dir, results_dir)
        print(json.dumps({k: srep[k] for k in ("size_actual", "shortfall", "strata")}, ensure_ascii=False, indent=1))
    elif cmd == "evaluate" and len(argv) == 2:
        print(json.dumps(do_evaluate(cfg, data_dir, results_dir, argv[1]), ensure_ascii=False, indent=1, default=list)[:4000])
    elif cmd == "smoke":
        print(json.dumps(do_smoke(), ensure_ascii=False, indent=1))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
