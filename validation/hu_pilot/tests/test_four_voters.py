"""Négy szavazó (A–D), azonos címek azonos sorrendben, külföldi nyelvű (en, de, sl) kiegészítő sor: kiválasztás, csomag, elemzés. D csak magyarul szavaz."""
import json
import subprocess
import shutil

import pytest

from validation.hu_pilot import analysis as an
from validation.hu_pilot import feeds, run, selection
from validation.hu_pilot.lang import detect_lang_code
from validation.hu_pilot.paths import REPO_ROOT
from .test_hu_pilot import KIND, write_exports
from .test_packaging import make_app


@pytest.fixture
def sel_res(tmp_path, cfg, feed_path):
    res = tmp_path / "res"
    run.do_select(cfg, feed_path, base=res)
    return res, json.loads((res / "selection.json").read_text(encoding="utf-8")), json.loads(feed_path.read_text(encoding="utf-8"))


def titles_of(res, name):
    return [i["title"] for i in json.loads((res / name).read_text(encoding="utf-8"))["items"]]


def test_foreign_selection_is_equal_per_language_detected_right_and_disjoint_from_hungarian(sel_res, cfg):
    res, sel, feed = sel_res
    by = {i["id"]: i for i in feed["items"]}
    fc = cfg["foreign"]
    assert list(sel["foreign_ids"]) == fc["languages"] and all(len(v) == fc["per_language"] for v in sel["foreign_ids"].values())
    for lang, ids in sel["foreign_ids"].items():
        assert all(detect_lang_code(by[i]["title"], "") == lang for i in ids)          # a felület is ezt a nyelvet ismeri fel
    hu = set(sel["anchor_ids"]) | set(sel["measured_ids"])
    allf = [i for v in sel["foreign_ids"].values() for i in v]
    assert len(allf) == len(set(allf)) == 60 and not hu & set(allf)
    assert sel["foreign_order"] == [sel["foreign_ids"][l][k] for k in range(fc["per_language"]) for l in fc["languages"]]       # váltogatott sorrend
    assert [detect_lang_code(by[i]["title"], "") for i in sel["foreign_order"][:6]] == ["en", "de", "sl", "en", "de", "sl"]
    assert titles_of(res, "pilot_stage4_foreign.json") == [by[i]["title"] for i in sel["foreign_order"]]                # a feed sorrendje = a rögzített közös sorrend
    assert titles_of(res, "pilot_stage1_anchors.json") == [by[i]["title"] for i in sel["anchor_ids"]]
    assert titles_of(res, "pilot_stage2_measured.json") == [by[i]["title"] for i in sel["measured_ids"]]


def test_foreign_selection_is_deterministic_and_fails_loudly_when_a_language_is_short(tmp_path, cfg, feed_path):
    a, b = tmp_path / "a", tmp_path / "b"
    run.do_select(cfg, feed_path, base=a)
    run.do_select(cfg, feed_path, base=b)
    assert (a / "pilot_stage4_foreign.json").read_bytes() == (b / "pilot_stage4_foreign.json").read_bytes()
    from .conftest import make_feed
    short = tmp_path / "short.json"
    short.write_text(json.dumps(make_feed(foreign=10)), encoding="utf-8")
    with pytest.raises(ValueError, match="nincs elég"):
        run.do_select(cfg, short, base=tmp_path / "c")


def test_all_stage_feeds_carry_the_pilot_flag_and_a_language_neutral_domain(sel_res):
    res, sel, feed = sel_res
    for name in ("pilot_stage1_anchors.json", "pilot_stage2_measured.json", "pilot_stage4_foreign.json"):
        d = json.loads((res / name).read_text(encoding="utf-8"))
        assert d["pilot"] and {i["source_domain"] for i in d["items"]} == {"pilot.invalid"}       # nincs .hu/.de/.si jel, amely a felület nyelvfelismerését eltérítené
        assert all(detect_lang_code(i["title"], i["source_domain"]) == detect_lang_code(i["title"], "") for i in d["items"])


def test_stage4_package_is_verified_ordered_and_does_not_contain_other_stages(tmp_path, cfg, sel_res):
    res, sel, feed = sel_res
    out = run.do_package(cfg, make_app(tmp_path), 4, "abc123", base=res)
    assert out["status"] == "OK" and out["titles"] == 60 and out["errors"] == []
    site = json.loads((res / "deploy/stage4/atm_history.json").read_text(encoding="utf-8"))
    assert [i["title"] for i in site["items"]] == titles_of(res, "pilot_stage4_foreign.json")
    blob = "".join(p.read_text(encoding="utf-8", errors="replace") for p in (res / "deploy/stage4").rglob("*") if p.is_file() and p.suffix != ".png")
    assert not any(t in blob for t in titles_of(res, "pilot_stage1_anchors.json") + titles_of(res, "pilot_stage2_measured.json"))


def test_select_foreign_adds_to_an_existing_selection_without_touching_the_hungarian_part(tmp_path, cfg, feed_path):
    res = tmp_path / "res"
    run.do_select(cfg, feed_path, base=res)
    full = json.loads((res / "selection.json").read_text(encoding="utf-8"))
    old = {k: v for k, v in full.items() if not k.startswith("foreign")}
    (res / "selection.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")          # a régi (külföldi rész nélküli) állapot
    (res / "pilot_stage4_foreign.json").unlink()
    h1, h2 = ((res / n).read_bytes() for n in ("pilot_stage1_anchors.json", "pilot_stage2_measured.json"))
    out = run.do_select_foreign(cfg, feed_path, base=res)
    new = json.loads((res / "selection.json").read_text(encoding="utf-8"))
    assert {k: v for k, v in new.items() if not k.startswith("foreign")} == old
    assert new["foreign_ids"] == full["foreign_ids"] and new["foreign_order"] == full["foreign_order"]            # ugyanaz, mint az egyben végzett kiválasztás
    assert (res / "pilot_stage1_anchors.json").read_bytes() == h1 and (res / "pilot_stage2_measured.json").read_bytes() == h2
    assert out["foreign"] == {"en": 20, "de": 20, "sl": 20}
    with pytest.raises(FileExistsError):
        run.do_select_foreign(cfg, feed_path, base=res)


def four_voter_exports(tmp_path, sel, hu_only=("D",)):
    """A, B, C minden magyar és külföldi címet értékel; D csak a magyarokat. A válaszok szavazónként eltérnek (D szigorúbb)."""
    hu = sel["anchor_ids"] + sel["measured_ids"]
    fo = sel["foreign_order"]
    shift = {"A": 0, "B": 0, "C": 1, "D": 2}
    votes = {}
    for v in "ABCD":
        ids = hu + ([] if v in hu_only else fo)
        votes[v] = [(i, KIND[(n * 7 + shift[v] * (n % 4 == 0)) % 3]) for n, i in enumerate(ids)]
    return write_exports(tmp_path, votes)


def test_analysis_compares_all_four_voters_by_group_and_language(tmp_path, cfg, sel_res):
    res, sel, feed = sel_res
    exp = four_voter_exports(tmp_path, sel)
    r = run.do_analyze(cfg, [exp], base=res)
    assert r["voters"] == ["A", "B", "C", "D"]
    assert {tuple(p["voters"]) for p in r["measured"]["pairs"]} == {("A", "B"), ("A", "C"), ("A", "D"), ("B", "C"), ("B", "D"), ("C", "D")}
    g = r["gate"]
    assert g["voters"] == ["A", "B", "C", "D"] and g["decision"] == "atment" and g["alpha"] >= cfg["gate"]["alpha_min"]       # a kapu mind a négy szavazó közös egyezésén dönt
    assert g["secondary_pair_kappa"]["pair"] == ["A", "B"] and g["secondary_pair_kappa"]["decides"] is False                 # az A-B kappa csak közölt szám
    assert set(r["foreign"]) == {"en", "de", "sl"}
    for lang, g in r["foreign"].items():
        assert g["voters"] == ["A", "B", "C"] and g["n_titles"] == g["n_titles_with_votes"] == 20 and len(g["pairs"]) == 3 and g["krippendorff_alpha_ordinal"] is not None
    prof = r["voter_profile"]
    assert prof["D"]["foreign_en"] == prof["D"]["foreign_de"] == prof["D"]["foreign_sl"] == 0 and prof["D"]["measured"] == 30 and prof["D"]["anchors"] == 20
    assert prof["A"]["foreign_en"] == prof["A"]["foreign_sl"] == 20
    assert abs(sum(prof["C"]["measured_distribution"].values()) - 1) < 1e-9
    assert (res / "analysis.json").exists()


def test_the_foreign_votes_do_not_change_the_hungarian_result(tmp_path, cfg, sel_res):
    res, sel, feed = sel_res
    for d in ("with", "without"):
        (tmp_path / d).mkdir()
    with_f = four_voter_exports(tmp_path / "with", sel)
    without_f = four_voter_exports(tmp_path / "without", sel, hu_only=("A", "B", "C", "D"))
    a = an.analyze(*an.parse_exports([with_f], cfg), sel, cfg)
    b = an.analyze(*an.parse_exports([without_f], cfg), sel, cfg)
    assert a["measured"]["pairs"] == b["measured"]["pairs"] and a["anchors"]["pairs"] == b["anchors"]["pairs"] and a["gate"] == b["gate"]
    assert a["foreign"]["en"]["voters"] == ["A", "B", "C"] and b["foreign"]["en"]["voters"] == []


@pytest.mark.skipif(shutil.which("node") is None, reason="node nincs meg")
def test_python_language_code_matches_the_js_original(tmp_path):
    items = json.loads((REPO_ROOT / "data/metrics/atm_history.json").read_text(encoding="utf-8"))["items"]
    rows = [{"t": i.get("title") or "", "d": d} for i in items for d in ("", i.get("source_domain") or "")]
    (tmp_path / "rows.json").write_text(json.dumps(rows), encoding="utf-8")
    shutil.copy(REPO_ROOT / "public/js/modules/lang.js", tmp_path / "lang.mjs")
    (tmp_path / "p.mjs").write_text("import fs from 'node:fs';import {detectLangCode} from './lang.mjs';"
                                    f"const r=JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'rows.json'))},'utf8'));console.log(JSON.stringify(r.map(x=>detectLangCode(x.t,x.d))));", encoding="utf-8")
    js = json.loads(subprocess.run(["node", str(tmp_path / "p.mjs")], capture_output=True, text=True, check=True).stdout)
    diffs = [(i, a, detect_lang_code(r["t"], r["d"])) for i, (a, r) in enumerate(zip(js, rows)) if a != detect_lang_code(r["t"], r["d"])]
    assert not diffs, diffs[:5]
