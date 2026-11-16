"""A Kvótafigyelő próbája: valódi (hamis átvitellel készült) futásmappán és szándékosan elrontott naplókon. Csak olvas; a futásmappa bájtra azonos marad."""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from validation.hu_pilot import quotawatch as qw
from .test_modelrun import CANARY, Clock, Script, frozen, go, jl, ok_raw, quota_day, T0, UTC  # noqa: F401


def snapshot(d):
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(Path(d).rglob("*")) if p.is_file()}


def stopped(frozen, cfg, n_ok=12, name="kv"):
    tr = Script("gemini", [lambda b: ok_raw("gemini", b)] * n_ok + [quota_day()])
    rep, run_dir, clock = go(frozen, cfg, tr, name=name)
    assert rep["status"] == "stopped_quota"
    return run_dir


def at(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def test_stopped_run_reports_progress_wait_and_does_not_touch_any_file(frozen, cfg):
    d = stopped(frozen, cfg)
    before = snapshot(d)
    r = qw.assess(qw.load_run(d), cfg, at("2026-11-14T12:00:00Z"))
    assert (r["status"], r["done"], r["total"], r["pending"], r["failed_terminal"]) == ("stopped_quota", 12, 50, 38, 0)
    assert r["resume_after_utc"] == "2026-11-15T08:05:00Z" and r["remaining_s"] == 20 * 3600 + 5 * 60 and r["can_resume_now"] is False
    assert r["violations"] == [] and r["verdict"] == "RENDBEN" and "Várj" in r["advice"][0] and "még 1205 perc" in r["advice"][0]
    assert snapshot(d) == before


def test_resume_is_allowed_exactly_at_reset_plus_five_minutes_and_not_one_second_before(frozen, cfg):
    d = stopped(frozen, cfg)
    run = qw.load_run(d)
    early = qw.assess(run, cfg, at("2026-11-15T08:04:59Z"))
    on = qw.assess(run, cfg, at("2026-11-15T08:05:00Z"))
    assert early["can_resume_now"] is False and early["remaining_s"] == 1
    assert on["can_resume_now"] is True and on["remaining_s"] == 0 and "próbakérés" in on["advice"][0] and on["probes_left_today"] == 3


def test_probe_budget_is_counted_per_quota_day_and_exhaustion_moves_the_advice_to_the_next_day(frozen, cfg):
    d = stopped(frozen, cfg)
    run = qw.load_run(d)
    run["state"]["probes"] = [{"utc": "2026-11-15T08:06:00Z", "quota_day": "2026-11-15"}] * 3
    r = qw.assess(run, cfg, at("2026-11-15T09:00:00Z"))
    assert r["probes_today"] == 3 and r["probes_left_today"] == 0 and r["can_resume_now"] is False
    assert "elfogyott a napi 3 próba" in r["advice"][0] and "2026-11-16T08:05:00Z" in r["advice"][0]
    run["state"]["probes"] = [{"utc": "2026-11-14T10:00:00Z", "quota_day": "2026-11-14"}] * 3        # tegnapi próbák nem számítanak mára
    assert qw.assess(run, cfg, at("2026-11-15T09:00:00Z"))["probes_left_today"] == 3


def test_a_real_resumed_run_is_clean_and_complete(frozen, cfg):
    res, titles = frozen
    d = stopped(frozen, cfg)
    clock = Clock(datetime(2026, 11, 15, 8, 5, tzinfo=UTC))
    rep, d2, _ = go(frozen, cfg, Script("gemini"), clock=clock, name="kv")
    assert rep["status"] == "complete"
    r = qw.assess(qw.load_run(d), cfg, at("2026-11-15T09:00:00Z"))
    assert r["status"] == "complete" and r["done"] == 50 and r["pending"] == 0 and r["violations"] == [] and "kész" in r["advice"][0]


@pytest.mark.parametrize("mutate,rule", [
    (lambda run: run["log"][3].update(provider="groq"), "szolgaltatovaltas"),
    (lambda run: run["log"][2].pop("usage"), "naplomezo"),
    (lambda run: run["log"].append(dict(run["log"][0])), "ujrakuldes"),
    (lambda run: run["state"].update(probes=[{"utc": "x", "quota_day": "2026-11-15"}] * 4), "probaplafon"),
    (lambda run: run["scores"][0].update(provider="groq"), "szolgaltatovaltas"),
])
def test_rule_violations_in_the_log_are_detected(frozen, cfg, mutate, rule):
    d = stopped(frozen, cfg)
    run = qw.load_run(d)
    mutate(run)
    assert rule in {v["rule"] for v in qw.assess(run, cfg, at("2026-11-15T09:00:00Z"))["violations"]}


def test_a_request_inside_the_wait_window_and_a_non_probe_first_request_are_violations(frozen, cfg):
    d = stopped(frozen, cfg)
    run = qw.load_run(d)
    stop = run["stops"][0]
    early = {"utc": "2026-11-14T20:00:00Z", "provider": "gemini", "model_requested": "m", "outcome": "ok", "usage": {}, "id": "zzz", "probe": True}
    assert stop["utc"] < early["utc"] < stop["resume_after_utc"]
    r1 = copy.deepcopy(run)
    r1["log"].append(early)
    assert "korai-folytatas" in {v["rule"] for v in qw.assess(r1, cfg, at("2026-11-15T09:00:00Z"))["violations"]}
    r2 = copy.deepcopy(run)
    r2["log"].append(dict(early, utc="2026-11-15T08:06:00Z", probe=False))
    assert "nem-proba" in {v["rule"] for v in qw.assess(r2, cfg, at("2026-11-15T09:00:00Z"))["violations"]}
    r3 = copy.deepcopy(run)
    r3["log"].append(dict(early, utc="2026-11-15T08:06:00Z", probe=True))
    assert qw.assess(r3, cfg, at("2026-11-15T09:00:00Z"))["violations"] == []


def test_a_key_shaped_string_in_the_log_is_flagged_without_printing_it(frozen, cfg, capsys):
    d = stopped(frozen, cfg)
    with open(d / "log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"detail": CANARY}) + "\n")
    rc = qw.main([str(d), "--now", "2026-11-15T09:00:00Z"])
    out = capsys.readouterr().out
    assert rc == 1 and "titok" in out and CANARY not in out


def test_cli_exit_codes_and_missing_run(frozen, cfg, tmp_path, capsys):
    d = stopped(frozen, cfg)
    assert qw.main([str(d), "--now", "2026-11-15T09:00:00Z", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "RENDBEN"
    assert qw.main([str(tmp_path / "nincs")]) == 2
