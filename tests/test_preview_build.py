"""A mobilos előnézet összeállítása (preview/build.py): az éles kód változatlansága, a szintetikus adat és a keret."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUB, PRE = ROOT / "public", ROOT / "preview"

spec = importlib.util.spec_from_file_location("preview_build", PRE / "build.py")
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("pv") / "out"
    return out, B.build(out)


def test_unchanged_files_are_byte_identical(built):
    out, report = built
    assert "js/app.js" in report["identical"]                          # az alkalmazás logikája érintetlen
    for rel in report["identical"]:
        assert (out / rel).read_bytes() == (PUB / rel).read_bytes(), rel
    for must in ("js/modules/model.js", "js/modules/learner.js", "js/modules/calibration.js", "js/modules/audit.js", "js/modules/reconcile.js",
                 "js/modules/backup.js", "js/modules/store.js", "js/modules/voters.js", "js/modules/quick.js", "js/modules/blind.js", "js/modules/filterEngine.js"):
        assert must in report["identical"], must                       # pontozás, AI, kappa, AUC, tárolás: bájtra azonos


def test_only_the_declared_files_differ(built):
    out, report = built
    live = {p.relative_to(PUB).as_posix() for p in (PUB / "js").rglob("*.js")}
    assert set(report["identical"]) | set(report["patched"]) | set(report["replaced"]) == live | {"css/main.css"}
    assert sorted(report["patched"]) == ["js/modules/globe.js", "js/modules/globe3d.js"]
    assert report["replaced"] == ["js/modules/uiRenderer.js"]


def test_patched_globe_files_differ_only_by_the_declared_changes(built):
    out, _ = built
    for rel, patches in B.PATCHES.items():
        text = (out / rel).read_text(encoding="utf-8")
        for old, new in patches:
            assert text.count(new) == 1
            text = text.replace(new, old)
        assert text == (PUB / rel).read_text(encoding="utf-8"), rel      # a változtatásokat visszafordítva az eredeti jön ki


def test_renderer_exports_cover_the_live_ones():
    names = lambda p: set(re.findall(r"^export (?:const|function|class) ([A-Za-z$_]+)", p.read_text(encoding="utf-8"), re.M))
    assert names(PUB / "js/modules/uiRenderer.js") <= names(PRE / "uiRenderer.js")


def test_build_stops_when_the_live_renderer_changed(monkeypatch):
    B.check_base()                                                       # most egyezik
    monkeypatch.setattr(B, "sha16", lambda p: "0" * 16)
    with pytest.raises(B.BuildError, match="megváltozott"):
        B.check_base()


def test_a_patch_that_no_longer_matches_fails_the_build(tmp_path, monkeypatch):
    monkeypatch.setitem(B.PATCHES, "js/modules/globe.js", [("nincs ilyen szöveg", "x")])
    with pytest.raises(B.BuildError, match="pontosan 1 kell"):
        B.build(tmp_path / "x")


def test_preview_page_has_every_element_the_app_needs():
    live = set(re.findall(r'\bid="([A-Za-z0-9_-]+)"', (PUB / "index.html").read_text(encoding="utf-8")))
    prev = set(re.findall(r'\bid="([A-Za-z0-9_-]+)"', (PRE / "index.html").read_text(encoding="utf-8")))
    assert live <= prev, sorted(live - prev)
    used = set()
    for p in (PUB / "js").rglob("*.js"):
        used |= set(re.findall(r"\$\('([A-Za-z0-9_-]+)'\)", p.read_text(encoding="utf-8")))
    assert used <= prev, sorted(used - prev)


def test_page_is_a_fragment_for_publishing(built):
    out, _ = built
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "<title>" in html[:300]
    assert not re.search(r"<(html|head|body)[\s>]|<!doctype", html, re.I)   # a keretet a közzététel adja
    assert 'src="guard.js"' in html and "ELŐNÉZET" in html


def test_local_build_adds_the_frame(tmp_path):
    B.build(tmp_path / "l", local=True)
    html = (tmp_path / "l" / "index.html").read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>") and "viewport-fit=cover" in html


def test_synthetic_data_is_invented_and_scored_by_the_real_engine(built):
    out, _ = built
    d = json.loads((out / "atm_history.json").read_text(encoding="utf-8"))
    assert len(d["items"]) >= 40
    assert all(i["source_domain"].endswith(".example") and i["id"].startswith("pv") for i in d["items"])   # kitalált forrás, kitalált azonosító
    assert all(i["link"].startswith("https://") and ".example/" in i["link"] for i in d["items"])
    assert {i["region"] for i in d["items"]} >= {"HU-VA", "HU-NAT", "AT-1", "SI-1", "INT"}
    atm = [i["ATM"] for i in d["items"]]
    assert min(atm) == 0 and max(atm) > 300                              # van nyugodt és hangos hír is
    assert d["model"]["thresholds"]["low"] < d["model"]["thresholds"]["high"]
    assert not any(k in d for k in ("votes", "voters"))                  # szavazat nem kerül bele


def test_blind_guard_and_isolation_are_in_place():
    g = (PRE / "guard.js").read_text(encoding="utf-8")
    assert "github.io" in g and "mnt-blindvote" in g and "__mntPts" in g and "__mntNeutral" in g
