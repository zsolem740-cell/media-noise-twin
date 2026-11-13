"""Végigfutó (smoke) teszt szintetikus adatokon, AI nélkül: betöltés → minta → séma → kiértékelés. A próba-pontozó nem AI."""
import copy
import json

from validation.webis_validation import run, scoring, synthetic


def small(cfg, size):
    c = copy.deepcopy(cfg)
    c["sample"].update(size=size, strata=[dict(s, target=size // 4) for s in cfg["sample"]["strata"]])
    return c


def test_builtin_smoke_run():
    out = run.do_smoke()
    assert "nem AI" in out["MOCK"] and out["loaded"] == 300 and out["sampled"] == 60 and out["invalid_scores"] == 0
    assert out["spearman_vs_mean"] > 0.5 and out["kendall"] > 0.4


def test_twelve_item_chain_through_the_files(tmp_path, cfg):
    c = small(cfg, 12)
    data, results = tmp_path / "data", tmp_path / "results"
    results.mkdir()
    synthetic.write_corpus(data, n=300, seed=6)
    lrep, srep = run.do_sample(c, data, results)
    assert srep["size_actual"] == 12 and srep["shortfall"] == 0 and [s["allocated"] for s in srep["strata"]] == [3, 3, 3, 3]
    lines = [json.loads(x) for x in (results / "model_inputs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 12 and all(set(x) == {"id", "text"} for x in lines)                  # a modell csak az id-t és a címet kapja
    scores = [synthetic.mock_score(x["id"], x["text"]) for x in lines]
    (results / "scores.jsonl").write_text("\n".join(json.dumps(s) for s in scores) + "\n", encoding="utf-8")
    rep = run.do_evaluate(c, data, results, results / "scores.jsonl")
    assert rep["coverage"] == {"records": 12, "scored": 12, "missing_scores": 0, "unknown_scores": 0} and rep["invalid_scores"] == []
    assert (results / "report.json").exists()
    assert json.loads((results / "report.json").read_text(encoding="utf-8"))["coverage"]["scored"] == 12


def test_invalid_scores_are_reported_not_evaluated(tmp_path, cfg):
    c = small(cfg, 12)
    data, results = tmp_path / "data", tmp_path / "results"
    results.mkdir()
    synthetic.write_corpus(data, n=300, seed=6)
    run.do_sample(c, data, results)
    lines = [json.loads(x) for x in (results / "model_inputs.jsonl").read_text(encoding="utf-8").splitlines()]
    scores = [synthetic.mock_score(x["id"], x["text"]) for x in lines]
    scores[0]["signals"]["exaggeration"].update(score=2, span="idézet, ami nincs a címben")
    scores.append({"id": "ismeretlen", "source": "webis-clickbait-17"})
    (results / "scores.jsonl").write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in scores) + "\n", encoding="utf-8")
    rep = run.do_evaluate(c, data, results, results / "scores.jsonl")
    assert len(rep["invalid_scores"]) == 2 and rep["coverage"]["scored"] == 11 and rep["coverage"]["missing_scores"] == 1


def test_smoke_leaves_no_files_in_the_module_folders():
    from validation.webis_validation.isolation import MODULE_DIR
    before = sorted(p.name for p in (MODULE_DIR / "results").iterdir()) + sorted(p.name for p in (MODULE_DIR / "data").iterdir())
    run.do_smoke()
    assert before == sorted(p.name for p in (MODULE_DIR / "results").iterdir()) + sorted(p.name for p in (MODULE_DIR / "data").iterdir())
