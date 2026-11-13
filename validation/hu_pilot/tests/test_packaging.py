"""A telepíthető pilot-csomag tesztjei (Cloudflare Pages): változatlan app + szakasz-feed, ellenőrzés, determinisztikus ZIP. Telepítés és hálózat nincs."""
import copy
import json
import zipfile
from pathlib import Path

import pytest

from validation.hu_pilot import feeds, packaging, run
from validation.hu_pilot.paths import IsolationError
from .test_hu_pilot import make_feed
from .conftest import make_titles


def make_app(tmp_path, version="v47.10", extra=None):
    app = tmp_path / "app" / "public"
    for rel, body in {"index.html": "<html><title>Média-Zaj</title></html>", "js/app.js": "import './modules/diag.js';", "js/modules/diag.js": f"export const APP_VERSION = '{version}';",
                      "sw.js": "self.x = 1", "manifest.json": json.dumps({"name": "x"}), "css/main.css": "body{}", **(extra or {})}.items():
        p = app / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    (app / "icons").mkdir(exist_ok=True)
    (app / "icons" / "icon-192.png").write_bytes(b"\x89PNG fake")
    return app


@pytest.fixture
def selected(tmp_path, cfg, feed_path):
    res = tmp_path / "res"
    run.do_select(cfg, feed_path, base=res)
    return res


def pkg(selected, app, cfg, stage):
    return run.do_package(cfg, app, stage, "abc123", base=selected)


def test_stage_packages_contain_only_their_own_titles_and_an_unchanged_app(tmp_path, cfg, selected):
    app = make_app(tmp_path)
    out1, out2 = pkg(selected, app, cfg, 1), pkg(selected, app, cfg, 2)
    assert out1["status"] == "OK" and out1["titles"] == 20 and out2["status"] == "OK" and out2["titles"] == 30 and out1["app_version"] == "v47.10"
    d = selected / "deploy"
    f1 = json.loads((d / "stage1/atm_history.json").read_text(encoding="utf-8"))
    f2 = json.loads((d / "stage2/atm_history.json").read_text(encoding="utf-8"))
    t1, t2 = {i["title"] for i in f1["items"]}, {i["title"] for i in f2["items"]}
    assert not t1 & t2
    for stage_dir, forbidden in ((d / "stage1", t2), (d / "stage2", t1)):
        blob = "".join(p.read_text(encoding="utf-8", errors="replace") for p in stage_dir.rglob("*") if p.is_file() and p.suffix != ".png")
        assert not any(t in blob for t in forbidden)
    for rel in ("index.html", "js/app.js", "js/modules/diag.js", "sw.js", "manifest.json", "css/main.css", "icons/icon-192.png"):
        assert (d / "stage1" / rel).read_bytes() == (app / rel).read_bytes()               # az app kódja bájtra változatlan
    assert (d / "stage1/_headers").read_text(encoding="utf-8").startswith("/atm_history.json\n  Cache-Control: no-store")
    assert (d / "stage1/robots.txt").read_text(encoding="utf-8") == "User-agent: *\nDisallow: /\n"


def test_version_mismatch_is_refused_and_the_wrong_folder_is_refused(tmp_path, cfg, selected):
    with pytest.raises(packaging.PackageError, match="verziója"):
        pkg(selected, make_app(tmp_path, "v47.9"), cfg, 1)
    with pytest.raises(packaging.PackageError, match="public"):
        pkg(selected, tmp_path, cfg, 1)


def test_a_real_feed_or_hidden_files_in_the_app_folder_never_get_in(tmp_path, cfg, selected):
    app = make_app(tmp_path, extra={"atm_history.json": json.dumps(make_feed(5)), ".env": "TOKEN=abc", ".git/config": "x"})
    out = pkg(selected, app, cfg, 1)
    d = selected / "deploy/stage1"
    assert out["status"] == "OK" and not (d / ".env").exists() and not (d / ".git").exists()
    f = json.loads((d / "atm_history.json").read_text(encoding="utf-8"))
    assert len(f["items"]) == 20 and all(i["source"] == "pilot" for i in f["items"])


def test_verification_catches_unwanted_files_leaks_and_wrong_feeds(tmp_path, cfg, selected):
    app = make_app(tmp_path, extra={"keys.pem": "-----BEGIN", "data/extra.json": "{}"})
    out = pkg(selected, app, cfg, 1)
    assert out["status"] == "HIBA" and any("keys.pem" in e or ".pem" in e for e in out["errors"])
    out = pkg(selected, make_app(tmp_path / "x"), cfg, 1)
    d = selected / "deploy/stage1"
    f = json.loads((d / "atm_history.json").read_text(encoding="utf-8"))
    titles = [i["title"] for i in f["items"]]
    assert not packaging.verify_site(d, titles, [], cfg)
    assert packaging.verify_site(d, titles[::-1], [], cfg)                                    # más sorrend
    assert packaging.verify_site(d, titles[:-1], [], cfg)                                     # hiányzó cím
    (d / "js" / "app.js").write_text("const x = " + json.dumps(titles[3]), encoding="utf-8")     # egy cím a kódban
    assert any("más szakasz címe" in e for e in packaging.verify_site(d, titles, [titles[3]], cfg))
    f["items"][0]["S"] = 0.4
    (d / "atm_history.json").write_text(json.dumps(f, ensure_ascii=False), encoding="utf-8")
    assert any("nem semleges" in e for e in packaging.verify_site(d, titles, [], cfg))
    f["items"][0]["S"] = 0
    f["profiles"] = {"x.hu": {"n": 1}}
    (d / "atm_history.json").write_text(json.dumps(f, ensure_ascii=False), encoding="utf-8")
    assert any("profil" in e for e in packaging.verify_site(d, titles, [], cfg))
    (d / "_headers").write_text("/*\n  X: y\n", encoding="utf-8")
    assert any("no-store" in e for e in packaging.verify_site(d, titles, [], cfg))


def test_zip_is_deterministic_has_index_at_the_root_and_matches_the_manifest(tmp_path, cfg, selected):
    app = make_app(tmp_path)
    a = pkg(selected, app, cfg, 2)
    z = selected / "deploy/mz_pilot_stage2.zip"
    first = z.read_bytes()
    b = pkg(selected, app, cfg, 2)
    assert z.read_bytes() == first and a["zip_sha256"] == b["zip_sha256"]
    names = zipfile.ZipFile(z).namelist()
    assert "index.html" in names and "atm_history.json" in names and "_headers" in names and names == sorted(names)
    man = json.loads((selected / "deploy/stage2_manifest.json").read_text(encoding="utf-8"))
    assert man["zip_sha256"] == a["zip_sha256"] and man["app_commit"] == "abc123" and set(man["files"]) == set(names)
    zf = zipfile.ZipFile(z)
    assert all(man["files"][n] == __import__("hashlib").sha256(zf.read(n)).hexdigest() for n in names)


def test_stage3_contains_only_the_disagreeing_titles_and_may_overlap_stage2_titles(tmp_path, cfg, selected):
    app = make_app(tmp_path)
    s2 = json.loads((selected / "pilot_stage2_measured.json").read_text(encoding="utf-8"))
    sub = dict(s2)
    sub["items"] = s2["items"][:4]
    sub["pilot"] = "stage3-adjudication"
    (selected / "pilot_stage3_adjudication.json").write_text(json.dumps(sub, ensure_ascii=False), encoding="utf-8")
    out = pkg(selected, app, cfg, 3)
    assert out["status"] == "OK" and out["titles"] == 4
    # a 3. szakasz címei a 2. szakaszéi közül valók: a tiltás csak az 1. szakasz (horgonyok) címeire vonatkozik
    blob = (selected / "deploy/stage3/atm_history.json").read_text(encoding="utf-8")
    assert s2["items"][10]["title"] not in blob


def test_packaging_writes_only_inside_results_and_has_no_network_code(tmp_path, cfg, selected):
    app = make_app(tmp_path)
    with pytest.raises(IsolationError):
        packaging.build_site(app, {"items": []}, tmp_path / "kivul", selected, cfg)
    src = (Path(packaging.__file__)).read_text(encoding="utf-8")
    for bad in ("urllib", "socket", "requests", "subprocess", "environ", "getenv", "import os"):
        assert bad not in src
