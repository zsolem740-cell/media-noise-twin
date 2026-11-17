"""A Folytatás-jelző próbája: a döntési logika, az artifact-választás, az üzenet tartalma és a munkafolyamat biztonsági szabályai. Hálózat és modellhívás nincs (a hálózati zár is él)."""
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from validation.hu_pilot import quotawatch as qw
from validation.hu_pilot import resumewatch as rw
from .test_modelrun import Script, frozen, go, ok_raw, quota_day, UTC  # noqa: F401

REPO = Path(__file__).resolve().parents[3]
WF = REPO / ".github/workflows/resume-notify.yml"


def art(name, run_id, created="2026-11-17T13:19:00Z", expired=False, aid=1):
    return {"id": aid, "name": name, "expired": expired, "created_at": created, "workflow_run": {"id": run_id}}


def report(**kw):
    base = {"run_id": "pilot-1", "provider": "gemini", "model": "gemini-3.6-flash", "status": "stopped_quota", "total": 50, "done": 12, "pending": 38, "failed_terminal": 0,
            "resume_after_utc": "2026-11-18T08:05:00Z", "remaining_s": 0, "can_resume_now": True, "probes_left_today": 3, "violations": [], "verdict": "RENDBEN"}
    base.update(kw)
    return base


def at(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


# ---------- artifact-választás ----------
def test_pick_takes_the_newest_live_pilot_run_artifact_and_ignores_the_rest():
    lst = {"artifacts": [art("pilot-run-pilot-1", 100, "2026-11-17T13:19:00Z", aid=1), art("pilot-run-pilot-2", 200, "2026-11-18T09:00:00Z", aid=2),
                         art("pilot-run-regi", 300, "2026-11-19T09:00:00Z", expired=True, aid=3), art("resume-notified-200-20261118", 400, "2026-11-20T09:00:00Z", aid=4),
                         art("masik-artifact", 500, "2026-11-21T09:00:00Z", aid=5)]}
    assert rw.pick_artifact(lst) == {"artifact_name": "pilot-run-pilot-2", "run_name": "pilot-2", "actions_run_id": 200}
    assert rw.pick_artifact({"artifacts": []}) is None and rw.pick_artifact({}) is None and rw.pick_artifact(None) is None
    assert rw.pick_artifact({"artifacts": [art("pilot-run-x", 1, expired=True)]}) is None


@pytest.mark.parametrize("bad", ["pilot-run-a b", "pilot-run-a;rm -rf", "pilot-run-$(id)", "pilot-run-`id`", "pilot-run-../x", "pilot-run-" + "a" * 65, "pilot-run-", "pilot-run-á", "pilot-run-a\nb"])
def test_pick_refuses_unsafe_names_so_nothing_odd_reaches_the_shell(bad):
    assert rw.pick_artifact({"artifacts": [art(bad, 7)]}) is None


def test_pick_requires_a_real_run_id():
    for rid in (None, 0, -1, "12", 1.5):
        assert rw.pick_artifact({"artifacts": [{"id": 1, "name": "pilot-run-ok", "workflow_run": {"id": rid}}]}) is None


# ---------- döntés ----------
def test_notifies_only_for_a_quota_stop_that_can_be_resumed_and_was_not_announced_yet():
    d = rw.decide(report(), 44089687734, "pilot-1")
    assert d["notify"] is True and d["marker"] == "resume-notified-44089687734-20261118080500"
    for kw in (dict(status="complete"), dict(status="stopped_billing"), dict(status="stopped_fatal"), dict(status="stopped_request_cap"), dict(status="running"),
               dict(can_resume_now=False), dict(probes_left_today=0, can_resume_now=False)):
        n = rw.decide(report(**kw), 1, "pilot-1")
        assert n["notify"] is False and "message" not in n
    assert rw.decide(report(), 1, "pilot-1", notified=True) == {"notify": False, "reason": "erről a megállásról már ment értesítés"}
    assert rw.decide(report(), 1, "pilot 1; rm")["notify"] is False and rw.decide(report(), 1, "")["notify"] is False


def test_marker_name_is_stable_per_stop_and_changes_with_a_new_stop():
    a = rw.marker_name(report(), 5)
    assert a == rw.marker_name(report(), 5) and re.fullmatch(r"resume-notified-5-\d+", a)
    assert rw.marker_name(report(resume_after_utc="2026-11-19T08:05:00Z"), 5) != a and rw.marker_name(report(), 6) != a
    assert re.fullmatch(r"resume-notified-5-nincs", rw.marker_name(report(resume_after_utc=None), 5))


def test_message_has_the_steps_numbers_and_no_secret_or_voter_data(tmp_path):
    m = rw.decide(report(), 44089687734, "pilot-1")["message"]
    for need in ("pilot-1", "12 / 50", "hátra 38", "gemini", "mode run", "batch_size 0", "resume_run_id 44089687734", "INDITSD", "te indítod, én nem", "próba"):
        assert need in m, need
    assert "FIGYELEM" not in m
    v = rw.decide(report(violations=[{"rule": "x"}], verdict="SZABÁLYSÉRTÉS"), 1, "pilot-1")["message"]
    assert "FIGYELEM" in v and "1 szabálysértés" in v
    f = tmp_path / "m.txt"
    f.write_text(m, encoding="utf-8")
    r = subprocess.run([sys.executable, str(REPO / "scripts/outcheck.py"), str(f)], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0 and "TISZTA" in r.stdout, r.stdout + r.stderr                   # a Kimenő-ellenőr is átengedi
    low = m.lower()
    for banned in ("aiza", "gsk_", "ghp_", "api_key", "szavazó a", "szavazatok-"):
        assert banned not in low


# ---------- egy valódi (hamis átvitellel készült) megállt futásból ----------
def test_end_to_end_with_a_real_stopped_run_before_and_after_the_reset(frozen, cfg, tmp_path):
    tr = Script("gemini", [lambda b: ok_raw("gemini", b)] * 12 + [quota_day()])
    rep, run_dir, clock = go(frozen, cfg, tr, name="pilot-1")
    run = qw.load_run(run_dir)
    early = qw.assess(run, cfg, at("2026-11-15T08:04:59Z"))
    on = qw.assess(run, cfg, at("2026-11-15T08:05:00Z"))
    assert rw.decide(early, 99, "pilot-1")["notify"] is False
    d = rw.decide(on, 99, "pilot-1")
    assert d["notify"] is True and "12 / 50" in d["message"] and "resume_run_id 99" in d["message"]
    assert rw.decide(on, 99, "pilot-1", notified=True)["notify"] is False


def test_command_line_reads_files_and_never_writes_anything(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"artifacts": [art("pilot-run-pilot-1", 55)]}), encoding="utf-8")
    (tmp_path / "r.json").write_text(json.dumps(report()), encoding="utf-8")
    before = sorted(p.name for p in tmp_path.iterdir())

    def run(*a):
        return subprocess.run([sys.executable, "-m", "validation.hu_pilot.resumewatch", *a], capture_output=True, text=True, cwd=REPO)

    p = run("pick", str(tmp_path / "a.json"))
    assert p.returncode == 0 and json.loads(p.stdout)["actions_run_id"] == 55
    d = run("decide", str(tmp_path / "r.json"), "--actions-run-id", "55", "--run-name", "pilot-1")
    assert d.returncode == 0 and json.loads(d.stdout)["notify"] is True
    n = run("decide", str(tmp_path / "r.json"), "--actions-run-id", "55", "--run-name", "pilot-1", "--notified")
    assert json.loads(n.stdout)["notify"] is False
    m = run("marker", str(tmp_path / "r.json"), "--actions-run-id", "55")
    assert m.returncode == 0 and json.loads(m.stdout)["marker"].startswith("resume-notified-55-")
    assert run("pick", str(tmp_path / "nincs.json")).returncode == 2 and run("decide", str(tmp_path / "nincs.json"), "--actions-run-id", "1", "--run-name", "x").returncode == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == before


# ---------- a munkafolyamat biztonsági szabályai ----------
def _wf():
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def _code():
    """A munkafolyamat szövege a megjegyzések nélkül (a megjegyzés magyarázhat tiltott dolgokat, a kód nem használhatja őket)."""
    return "\n".join(l for l in WF.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#"))


def test_workflow_only_runs_on_schedule_or_by_hand_and_has_read_only_permissions():
    d = _wf()
    on = d[True]
    assert set(on) == {"schedule", "workflow_dispatch"}
    assert d["permissions"] == {"contents": "read", "actions": "read"}
    text = _code()
    for forbidden in ("pull_request", "issue_comment", "issues:", "workflow_run", "repository_dispatch", "pull_request_target"):
        assert forbidden not in text, forbidden


def test_workflow_has_no_model_keys_no_repo_writes_and_only_the_ntfy_secret():
    text = _code()
    assert re.findall(r"secrets\.([A-Za-z0-9_]+)", text) == ["NTFY_TOPIC"]
    for forbidden in ("GEMINI", "GROQ", "OPENAI", "run_live", "--live", "INDITSD\"", "git push", "git commit", "gh pr", "gh workflow", "gh run rerun", "gh run cancel", "merge", "api.github.com"):
        assert forbidden not in text, forbidden
    cmds = set(re.findall(r"(?<![A-Za-z])gh ((?:api|run download|[a-z]+))", text))
    assert cmds == {"api", "run download"}, cmds
    for write_flag in (" -X ", "--method", " -f ", " -F ", "--field", "--input", "--raw-field"):
        assert write_flag not in text, write_flag                                                      # csak olvasó (GET) hívások


def test_workflow_never_puts_user_controlled_text_into_a_shell_script_and_uses_known_actions_only():
    d = _wf()
    for step in d["jobs"]["notify"]["steps"]:
        if "run" in step:
            assert "${{" not in step["run"], step.get("name")                                                 # csak környezeti változón át
        if "uses" in step:
            assert step["uses"].split("@")[0] in {"actions/checkout", "actions/setup-python", "actions/upload-artifact"}, step["uses"]
    assert d["jobs"]["notify"]["timeout-minutes"] <= 5 and d["concurrency"]["cancel-in-progress"] is False


def test_workflow_sends_only_after_the_outgoing_check_and_only_to_ntfy():
    steps = _wf()["jobs"]["notify"]["steps"]
    names = [s.get("name", s.get("uses")) for s in steps]
    i_check = next(i for i, n in enumerate(names) if "Kimenő-ellenőr" in n)
    i_send = next(i for i, n in enumerate(names) if "Értesítés küldése" in n)
    i_mark = next(i for i, n in enumerate(names) if "Jelölő" in n)
    assert i_check < i_send < i_mark
    text = _code()
    assert re.findall(r"https://[A-Za-z0-9./_-]+", text) == ["https://ntfy.sh"]
    assert "scripts/outcheck.py" in steps[i_check]["run"]


def test_the_marker_step_runs_only_after_a_successful_send():
    steps = _wf()["jobs"]["notify"]["steps"]
    for s in steps:
        if "Jelölő" in s.get("name", "") or s.get("uses", "").startswith("actions/upload-artifact"):
            assert "steps.send.outputs.sent == 'true'" in s["if"]
