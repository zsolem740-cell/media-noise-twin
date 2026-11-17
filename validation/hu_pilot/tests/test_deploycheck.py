"""A Telepítés-ellenőr próbája valódi (a pipeline-nal készült) csomagokon, szándékosan elrontott zipekkel. Telepítés és hálózat nincs; az ellenőrzött fájlok nem változnak."""
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from validation.hu_pilot import deploycheck as dc
from validation.hu_pilot import run
from .test_packaging import make_app


@pytest.fixture
def pkgs(tmp_path, cfg, feed_path):
    res = tmp_path / "res"
    run.do_select(cfg, feed_path, base=res)
    app = make_app(tmp_path)
    for s in (1, 2, 4):
        run.do_package(cfg, app, s, "abc123", base=res)
    sel = json.loads((res / "selection.json").read_text(encoding="utf-8"))
    return res, sel


def load(res, stage):
    d = res / "deploy"
    return d / f"mz_pilot_stage{stage}.zip", json.loads((d / f"stage{stage}_manifest.json").read_text(encoding="utf-8"))


def failed(checks):
    return {c["check"] for c in checks if not c["ok"]}


def rebuild(zp, manifest, out, change=None, drop=(), add=None, fix_manifest=True):
    """Új zip a régi tartalmából; change: {fájl: új bájtok}. A jegyzék lenyomatait (és a zip lenyomatát) igazítja, hogy csak a tartalmi hiba maradjon."""
    zin = zipfile.ZipFile(zp)
    data = {n: zin.read(n) for n in zin.namelist() if not n.endswith("/") and n not in drop}
    data.update(change or {})
    data.update(add or {})
    with zipfile.ZipFile(out, "w") as z:
        for n, b in data.items():
            z.writestr(n, b)
    m = json.loads(json.dumps(manifest))
    if fix_manifest:
        m["files"] = {n: hashlib.sha256(b).hexdigest() for n, b in data.items()}
        m["zip_sha256"] = hashlib.sha256(Path(out).read_bytes()).hexdigest()
    return m


def feed_of(zp):
    return json.loads(zipfile.ZipFile(zp).read("atm_history.json").decode("utf-8"))


def put(feed):
    return json.dumps(feed, ensure_ascii=False).encode("utf-8")


@pytest.mark.parametrize("stage", [1, 2, 4])
def test_every_real_stage_package_passes_all_checks(pkgs, cfg, stage):
    res, sel = pkgs
    zp, man = load(res, stage)
    checks = dc.run_checks(zp, man, stage, sel, cfg)
    assert failed(checks) == set() and len(checks) >= 10


def test_a_changed_zip_with_an_unchanged_manifest_fails_the_hash_checks(pkgs, cfg, tmp_path):
    res, sel = pkgs
    zp, man = load(res, 2)
    bad = tmp_path / "bad.zip"
    rebuild(zp, man, bad, change={"css/main.css": b"body{color:red}"}, fix_manifest=False)
    assert {"zip_sha256_egyezik_a_jegyzekkel", "fajlok_egyeznek_a_jegyzek_lenyomataival"} <= failed(dc.run_checks(bad, man, 2, sel, cfg))


def test_extra_or_missing_titles_or_swapped_order_fail_only_the_title_check(pkgs, cfg, tmp_path):
    res, sel = pkgs
    zp, man = load(res, 2)
    f = feed_of(zp)
    cases = {"extra": f["items"] + [dict(f["items"][0], id="zzz", title="Más cím")], "missing": f["items"][:-1], "swapped": [f["items"][1], f["items"][0]] + f["items"][2:]}
    for name, items in cases.items():
        bad = tmp_path / f"{name}.zip"
        m = rebuild(zp, man, bad, change={"atm_history.json": put({**f, "items": items})})
        assert failed(dc.run_checks(bad, m, 2, sel, cfg)) == {"cimek_pontosan_a_szakaszeiv_sorrendre_is"}, name


def test_a_title_shared_with_another_stage_and_a_wrong_pilot_field_are_detected(pkgs, cfg, tmp_path):
    res, sel = pkgs
    zp, man = load(res, 2)
    f = feed_of(zp)
    shared = dict(f["items"][0], id=sel["anchor_ids"][0])
    bad = tmp_path / "shared.zip"
    m = rebuild(zp, man, bad, change={"atm_history.json": put({**f, "items": [shared] + f["items"][1:]})})
    assert "nincs_kozos_cim_a_tobbi_szakasszal" in failed(dc.run_checks(bad, m, 2, sel, cfg))
    bad2 = tmp_path / "pilot.zip"
    m2 = rebuild(zp, man, bad2, change={"atm_history.json": put({**f, "pilot": "stage1-anchors"})})
    assert failed(dc.run_checks(bad2, m2, 2, sel, cfg)) == {"feed_pilot_mezo"}


@pytest.mark.parametrize("field,value", [("link", "https://valodi.hu/x"), ("source", "telex"), ("ATM", 3), ("summary", "szöveg"), ("alert", True), ("title", " ")])
def test_a_non_neutral_row_is_detected(pkgs, cfg, tmp_path, field, value):
    res, sel = pkgs
    zp, man = load(res, 1)
    f = feed_of(zp)
    f["items"][0][field] = value
    bad = tmp_path / "n.zip"
    m = rebuild(zp, man, bad, change={"atm_history.json": put(f)})
    assert failed(dc.run_checks(bad, m, 1, sel, cfg)) == {"sorok_semlegesek_nincs_forras_link_pontszam"}


def test_wrong_app_version_unsafe_paths_missing_files_and_headers_are_detected(pkgs, cfg, tmp_path):
    res, sel = pkgs
    zp, man = load(res, 2)
    m = dict(man, app_version="v47.11")
    assert failed(dc.run_checks(zp, m, 2, sel, cfg)) == {"alkalmazas_verzioja"}
    bad = tmp_path / "u.zip"
    mu = rebuild(zp, man, bad, add={"../kint.txt": b"x"})
    assert "biztonsagos_utvonalak" in failed(dc.run_checks(bad, mu, 2, sel, cfg))
    bad2 = tmp_path / "r.zip"
    mr = rebuild(zp, man, bad2, drop=("robots.txt",))
    assert "kotelezo_fajlok" in failed(dc.run_checks(bad2, mr, 2, sel, cfg))
    bad3 = tmp_path / "h.zip"
    mh = rebuild(zp, man, bad3, change={"_headers": b"/*\n  X: y\n"})
    assert failed(dc.run_checks(bad3, mh, 2, sel, cfg)) == {"headers_fajl_a_csomagolo_szerint"}


def test_cli_exit_codes_and_the_checked_files_stay_byte_identical(pkgs, cfg, tmp_path, capsys):
    res, sel = pkgs
    zp, man = load(res, 2)
    before = zp.read_bytes()
    assert dc.main(["2", "--results", str(res)]) == 0 and "RENDBEN" in capsys.readouterr().out
    assert zp.read_bytes() == before
    bad = tmp_path / "x.zip"
    zp.rename(tmp_path / "keep.zip")
    bad.write_bytes(b"nem zip")
    assert dc.main(["2", "--results", str(res), "--zip", str(bad)]) == 1
    assert dc.main(["2", "--results", str(tmp_path / "nincs")]) == 2
