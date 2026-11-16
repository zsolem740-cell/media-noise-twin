"""A Gemini-ellenőrzés (új 20 cím) tesztjei: hamis átvitellel, hálózat és kulcs nélkül."""
import copy
import csv
import json
from pathlib import Path

import pytest

from validation.webis_validation import gemini_check as gc
from validation.webis_validation import gemini_request as gr
from validation.webis_validation import gemini_smoke as gs
from validation.webis_validation import run as runmod
from validation.webis_validation.isolation import IsolationError, load_config

from .test_gemini import Clock, INPUTS, MODEL, Script, api, err, jl, mj

MODULE = Path(gc.__file__).resolve().parent


@pytest.fixture
def cfg():
    c = copy.deepcopy(load_config())
    c["gemini"]["smoke"].update(min_interval_s=0.0, backoff_s=[0.0, 0.0])
    return c


def go(tmp_path, cfg, script, model=MODEL):
    clock, res = Clock(), tmp_path / "results"
    rep = gc.run_check(INPUTS, script, cfg, res, model, sleep=clock.sleep, monotonic=clock.monotonic)
    return rep, res / "gemini_check"


def test_uses_the_existing_one_title_per_request_mode_and_same_rules(tmp_path, cfg):
    s = Script()
    rep, out = go(tmp_path, cfg, s)
    assert len(s.calls) == 20 and rep["requests_sent"] == 20 and rep["mode"].startswith("egy cím")
    assert rep["prompt_sha256"] == "c634bdcc62aa9c2e47f5e886c4d076d7676ab4f8631fb215dc90846f1f5da20f"
    assert rep["schema_sha256"] == "f3c2a7b3d03df7bb65032410b287bff69ef0e417c99aca6d8669cf24b8810e4a"
    for _, body in s.calls:
        assert set(body) == {"systemInstruction", "contents", "generationConfig"}
        assert body["systemInstruction"]["parts"][0]["text"] == gr.SYSTEM_INSTRUCTION


def test_writes_the_three_files_with_the_same_csv_columns_as_groq(tmp_path, cfg):
    rep, out = go(tmp_path, cfg, Script())
    assert {"gemini_results_check.csv", "gemini_log_check.jsonl", "gemini_summary_check.json"} <= {p.name for p in out.iterdir()}
    rows = list(csv.DictReader((out / "gemini_results_check.csv").open(encoding="utf-8", newline="")))
    from validation.webis_validation import groq_run as gq
    assert [r["id"] for r in rows] == [x["id"] for x in INPUTS] and all(r["status"] == "ok" for r in rows)
    assert list(rows[0]) == [f for f in gq.CSV_FIELDS if f != "batch_no"]
    assert float(rows[0]["scaled"]) == (int(rows[0]["total"]) / 8) and rows[0]["total"] == "3"
    log = jl(out / "gemini_log_check.jsonl")
    assert len(log) == 20 and all(l["outcome"] == "ok" and l["usage"]["totalTokenCount"] == 980 for l in log)
    summ = json.loads((out / "gemini_summary_check.json").read_text(encoding="utf-8"))
    assert summ["n_valid"] == 20 and summ["tokens"]["totalTokenCount"] == 19600 and summ["weighting"] == "nincs" and summ["groq_files_touched"] is False and summ["pass"]


def test_never_touches_or_mixes_with_groq_files(tmp_path, cfg):
    res = tmp_path / "results"
    (res / "groq").mkdir(parents=True)
    before = {}
    for n in ("groq_results_v2_check.csv", "groq_results_v3.csv", "groq_log_v3.jsonl"):
        (res / "groq" / n).write_text("groq", encoding="utf-8")
        before[n] = "groq"
    go(tmp_path, cfg, Script())
    assert {p.name: p.read_text(encoding="utf-8") for p in (res / "groq").iterdir()} == before
    assert not any(p.parent.name == "groq" for p in (res / "gemini_check").iterdir())


def test_refuses_to_overwrite_or_resume(tmp_path, cfg):
    go(tmp_path, cfg, Script())
    s2 = Script()
    with pytest.raises(FileExistsError):
        go(tmp_path, cfg, s2)
    assert s2.calls == []


def test_outside_results_dir_is_refused(tmp_path, cfg):
    with pytest.raises(IsolationError):
        c = copy.deepcopy(cfg)
        c["gemini"]["check"]["subdir"] = "../kivul"
        go(tmp_path, c, Script())


def test_daily_quota_stops_the_run_and_marks_the_rest(tmp_path, cfg):
    det = [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}]}]
    rep, out = go(tmp_path, cfg, Script([err(429, "quota", det)]))
    assert rep["requests_sent"] == 1 and rep["stop_reason"] == "quota_day" and rep["n_valid"] == 0
    rows = list(csv.DictReader((out / "gemini_results_check.csv").open(encoding="utf-8", newline="")))
    assert [r["status"] for r in rows].count("failed") == 1 and [r["status"] for r in rows].count("not_run") == 19


def test_blocked_and_invalid_titles_are_recorded_not_retried_when_blocked(tmp_path, cfg):
    blocked = gs.Raw(200, json.dumps({"promptFeedback": {"blockReason": "SAFETY"}, "usageMetadata": {"totalTokenCount": 5}}), 10)
    rep, out = go(tmp_path, cfg, Script([blocked]))
    assert rep["n_blocked"] == 1 and rep["n_valid"] == 19 and rep["requests_sent"] == 20
    rows = list(csv.DictReader((out / "gemini_results_check.csv").open(encoding="utf-8", newline="")))
    assert rows[0]["status"] == "failed" and "blocked" in rows[0]["failure"]


def test_restricted_or_unknown_model_is_refused(tmp_path, cfg):
    with pytest.raises(gs.NeedUserDecision):
        go(tmp_path, cfg, Script(), model="gemini-3.6-flash")


def test_dryrun_for_the_new_titles_is_valid(cfg):
    rows, errs = gc.build_dryrun(INPUTS, cfg)
    assert not errs and len(rows) == 20 and not gc.verify_dryrun(rows, INPUTS, cfg)


def test_cli_real_run_needs_go_and_the_transport_is_the_only_new_network_file():
    src = (MODULE / "run.py").read_text(encoding="utf-8")
    assert '"gemini-check-run" and argv[1:] == ["--go"]' in src and "gemini-check-dryrun" in src
    for f in ("gemini_check.py", "gemini_request.py", "gemini_smoke.py"):
        t = (MODULE / f).read_text(encoding="utf-8")
        assert not any(w in t for w in ("urlopen", "import urllib", "import socket", "os.environ", "getenv")), f
    t = (MODULE / "gemini_transport.py").read_text(encoding="utf-8")
    assert "NoRedirect" in t and 'ALLOWED_HOST = "generativelanguage.googleapis.com"' in t


def test_transport_refuses_without_key(cfg, monkeypatch):
    from validation.webis_validation import gemini_transport as gt
    monkeypatch.delenv(cfg["gemini"]["check"]["env_var"], raising=False)
    with pytest.raises(gt.MissingKey):
        gt.make_transport(cfg)
    with pytest.raises(gt.MissingKey):
        gt.list_models(cfg)


def test_missing_key_stops_before_any_request(cfg, monkeypatch, tmp_path):
    from validation.webis_validation import gemini_transport as gt
    monkeypatch.delenv(cfg["gemini"]["check"]["env_var"], raising=False)
    res = tmp_path / "results"
    (res / "groq").mkdir(parents=True)
    (res / "groq" / "groq_check_inputs_v3.jsonl").write_text("\n".join(json.dumps(x) for x in INPUTS) + "\n", encoding="utf-8")
    with pytest.raises(gt.MissingKey):
        runmod.do_gemini_check_run(cfg, res)
    assert not (res / "gemini_check").exists()


def test_transport_refuses_other_hosts(cfg, monkeypatch):
    from validation.webis_validation import gemini_transport as gt
    monkeypatch.setenv(cfg["gemini"]["check"]["env_var"], "placeholder")
    bad = copy.deepcopy(cfg)
    bad["gemini"]["check"]["host"] = "example.com"
    with pytest.raises(ValueError):
        gt.make_transport(bad)
    with pytest.raises(ValueError):
        gt.list_models(bad)
