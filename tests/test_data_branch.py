"""A data ág kezelője (scripts/data_branch.sh) egy helyi, csupasz „origin” tárolóval."""
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "data_branch.sh"
F = "data/metrics/atm_history.json"


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    origin = tmp_path / "origin.git"
    sh(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(origin))
    w = tmp_path / "w"
    sh(tmp_path, "git", "clone", "-q", str(origin), str(w))
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        sh(w, "git", "config", k, v)
    (w / "data/metrics").mkdir(parents=True)
    (w / F).write_text('{"v": 1}')
    (w / "README.md").write_text("x")
    sh(w, "git", "add", "-A")
    sh(w, "git", "commit", "-q", "-m", "init")
    sh(w, "git", "push", "-q", "origin", "HEAD:main")
    return w


def run(w, *a):
    return sh(w, "bash", str(SCRIPT), *a)


def test_migration_and_roundtrip(repo):
    assert "changed=true" in run(repo, "push", "elso")
    assert "changed=false" in run(repo, "push", "masodik")          # változás nélkül nem ír
    run(repo, "untrack")
    assert F not in sh(repo, "git", "ls-files")                       # a main ágról kikerült
    assert (repo / F).read_text() == '{"v": 1}'                       # a munkakönyvtárban megmaradt
    (repo / F).write_text('{"v": 2}')
    assert "changed=true" in run(repo, "push", "harmadik")
    (repo / F).write_text("rossz")
    run(repo, "pull")
    assert (repo / F).read_text() == '{"v": 2}'
    log = sh(repo, "git", "log", "--oneline", "origin/data")
    assert len(log.strip().splitlines()) == 1                         # a data ágon mindig egyetlen commit


def test_pull_without_branch_keeps_files(repo):
    run(repo, "pull")
    assert (repo / F).read_text() == '{"v": 1}'
    run(repo, "untrack")                                              # data ág nélkül nem vesz ki semmit
    assert F in sh(repo, "git", "ls-files")
