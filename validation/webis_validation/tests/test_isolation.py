"""Elkülönítés: a modul nem érinti a fő mérési állapotot, nem importál a fő kódból, és csak a saját mappáiba olvas és ír."""
import ast
import json
from pathlib import Path

import pytest

from validation.webis_validation import isolation, run, synthetic
from validation.webis_validation.isolation import REPO_ROOT, IsolationError

MODULE = Path(isolation.__file__).resolve().parent


def test_config_must_be_benchmark_readonly(tmp_path):
    cfg = json.loads((MODULE / "config.json").read_text(encoding="utf-8"))
    for bad in ({"mode": "read_write"}, {"mode": None}, {"source": "other"}, {"language": "hu"}):
        p = tmp_path / "c.json"
        p.write_text(json.dumps({**cfg, **bad}), encoding="utf-8")
        with pytest.raises(IsolationError):
            isolation.load_config(p)
    p.write_text(json.dumps(cfg), encoding="utf-8")
    assert isolation.load_config(p)["mode"] == "benchmark_readonly"


def test_default_config_is_valid():
    cfg = isolation.load_config()
    assert cfg["language"] == "en" and cfg["license"] == "CC BY 4.0" and cfg["paths"] == {"data_dir": "data", "results_dir": "results"}


@pytest.mark.parametrize("rel", ["data/metrics/atm_history.json", "data/metrics/gemini_labels.json", "public/index.html", "config/sources.json", "src/core/atm_engine.py", "inbox/LOG.md"])
def test_main_state_is_never_read(rel):
    with pytest.raises(IsolationError, match="fő adattárból"):
        isolation.check_read(REPO_ROOT / rel, REPO_ROOT / "data")                   # még hibás beállítású data_dir mellett sem


def test_read_only_inside_the_data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "a.jsonl").write_text("{}", encoding="utf-8")
    assert isolation.check_read(d / "a.jsonl", d) == (d / "a.jsonl").resolve()
    with pytest.raises(IsolationError, match="adatmappájából"):
        isolation.check_read(tmp_path / "x.jsonl", d)
    with pytest.raises(IsolationError):
        isolation.check_read(d / ".." / "x.jsonl", d)                               # útvonal-bejárás


def test_write_only_inside_the_results_dir(tmp_path):
    r = tmp_path / "results"
    r.mkdir()
    assert isolation.check_write(r / "report.json", r)
    for bad in (tmp_path / "x.json", r / ".." / "x.json", REPO_ROOT / "public" / "x.js", REPO_ROOT / "data" / "metrics" / "x.json"):
        with pytest.raises(IsolationError, match="eredménytárba"):
            isolation.check_write(bad, r)


def test_hungarian_only_characters():
    assert isolation.has_hungarian_chars("szőlő") and isolation.has_hungarian_chars("Űr")
    assert not isolation.has_hungarian_chars("An English headline with café and naïve")


def imports_of(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            out.append(("." * n.level) + (n.module or ""))
    return out


def test_module_imports_nothing_from_the_main_code():
    banned = ("src", "tests", "scripts", "public", "preview")
    for f in MODULE.rglob("*.py"):
        for imp in imports_of(f):
            top = imp.lstrip(".").split(".")[0]
            assert top not in banned, f"{f.name} importál: {imp}"
            if imp.startswith("validation") and not imp.startswith("validation.webis_validation"):
                pytest.fail(f"{f.name} idegen validációs modult importál: {imp}")


def test_main_data_paths_are_named_only_in_the_isolation_module():
    for f in MODULE.glob("*.py"):
        if f.name == "isolation.py":
            continue
        text = f.read_text(encoding="utf-8")
        assert "atm_history" not in text and "data/metrics" not in text and "gemini_labels" not in text and "gemini_budget" not in text, f.name
        assert "GEMINI_API_KEY" not in text, f.name              # a fő Gemini-folyamat titka sem szerepelhet


def test_module_has_no_network_or_ai_client():
    for f in MODULE.rglob("*.py"):
        if f.name in ("groq_transport.py", "gemini_transport.py"):
            continue                                   # a Groq-ág egyetlen, külön tesztelt hálózati fájlja (test_groq.py: csak az érinthet hálózatot és környezetet, csak api.groq.com-ot)
        tops = {i.lstrip(".").split(".")[0] for i in imports_of(f)}
        assert not tops & {"requests", "urllib", "http", "socket", "anthropic", "openai", "google", "httpx"}, f.name


def test_sampling_writes_only_into_the_results_dir(tmp_path, cfg):
    data, results = tmp_path / "data", tmp_path / "results"
    results.mkdir()
    synthetic.write_corpus(data, n=400, seed=4)
    small = json.loads(json.dumps(cfg))
    small["sample"].update(size=40, strata=[dict(s, target=10) for s in cfg["sample"]["strata"]])
    before = {p for p in tmp_path.rglob("*")}
    run.do_sample(small, data, results)
    new = {p for p in tmp_path.rglob("*")} - before
    assert new and all(results in p.parents for p in new), new
    assert {p.name for p in new} == {"sample_meta.json", "model_inputs.jsonl"}


def test_evaluate_refuses_scores_outside_the_results_dir(tmp_path, cfg):
    data, results = tmp_path / "data", tmp_path / "results"
    results.mkdir()
    synthetic.write_corpus(data, n=100, seed=4)
    (results / "sample_meta.json").write_text(json.dumps({"sample": {"ids": []}}), encoding="utf-8")
    outside = tmp_path / "scores.jsonl"
    outside.write_text("", encoding="utf-8")
    with pytest.raises(IsolationError):
        run.do_evaluate(cfg, data, results, outside)


def test_gitignore_keeps_corpus_and_results_out_of_git():
    text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "validation/webis_validation/data/*" in text and "validation/webis_validation/results/*" in text
