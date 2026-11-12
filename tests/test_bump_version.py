"""A verzióemelő (scripts/bump_version.py): a repó valódi fájljainak másolatán fut, a repót nem írja."""
import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FILES = ["PROJECT_VERSION", "public/js/modules/diag.js", "public/js/modules/audit.js", "public/index.html", "public/sw.js"]

spec = importlib.util.spec_from_file_location("bump_version", ROOT / "scripts" / "bump_version.py")
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)


@pytest.fixture
def copy(tmp_path):
    for f in FILES:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / f, tmp_path / f)
    return tmp_path


def sw_number(root):
    import re
    return int(re.search(r"mnt-v(\d+)'", (root / "public/sw.js").read_text(encoding="utf-8")).group(1))


def test_repo_versions_consistent():
    assert B.check(ROOT) == []                                        # a repóban a verzió mindenhol azonos


def test_bump_updates_every_place(copy):
    before = sw_number(copy)
    B.bump("v99.1", copy)
    assert set(B.read_versions(copy).values()) == {"v99.1"}
    assert B.check(copy) == []
    assert sw_number(copy) == before + 1                              # új verzió → új gyorsítótár-név
    B.bump("v99.1", copy)
    assert sw_number(copy) == before + 1                              # ugyanarra újrafuttatva nem lép tovább


def test_bump_changes_nothing_else(copy):
    old = {f: (copy / f).read_text(encoding="utf-8") for f in FILES}
    cur = B.read_versions(copy)["PROJECT_VERSION"]
    B.bump("v99.1", copy)
    B.bump(cur, copy)
    for f in FILES:
        if f != "public/sw.js":
            assert (copy / f).read_text(encoding="utf-8") == old[f]   # oda-vissza: bájtra azonos


def test_check_reports_mismatch(copy):
    (copy / "PROJECT_VERSION").write_text("v1.2\n")
    errors = B.check(copy)
    assert len(errors) == 3 and all("v1.2" in e for e in errors)


@pytest.mark.parametrize("bad", ["47.9", "v47.9-beta", "", "v47.9\nx"])
def test_invalid_version_rejected_before_writing(copy, bad):
    old = {f: (copy / f).read_text(encoding="utf-8") for f in FILES}
    with pytest.raises(B.VersionError):
        B.bump(bad, copy)
    assert {f: (copy / f).read_text(encoding="utf-8") for f in FILES} == old


def test_missing_marker_writes_nothing(copy):
    p = copy / "public/js/modules/audit.js"
    p.write_text(p.read_text(encoding="utf-8").replace("AUDIT_VERSION", "MAS_NEV"), encoding="utf-8")
    before = (copy / "PROJECT_VERSION").read_text()
    with pytest.raises(B.VersionError):
        B.bump("v99.1", copy)
    assert (copy / "PROJECT_VERSION").read_text() == before
