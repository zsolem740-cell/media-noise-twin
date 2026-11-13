"""A magyar pilot tesztjei: nyelvfelismerés, kiválasztás, semleges feed, kappa/alfa, kapu, lezárás, elkülönítés. Hálózat és modell nélkül."""
import ast
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from validation.hu_pilot import analysis as an
from validation.hu_pilot import feeds, freeze, run, selection
from validation.hu_pilot.lang import detect_lang
from validation.hu_pilot.paths import IsolationError, REPO_ROOT, check_write
from .conftest import backup, make_feed, make_titles

MOD = Path(run.__file__).resolve().parent


# ---------------------------------------------------------------- nyelvfelismerés

def test_detect_lang_basics():
    assert detect_lang("Az új kormány nem mondta meg, hogy mikor lesz a döntés") == "hu"
    assert detect_lang("The government said that it will not be a new rule") == "other"
    assert detect_lang("") == "?" and detect_lang("   ") == "?"
    assert detect_lang("Szőlő", "") != "other"


@pytest.mark.skipif(shutil.which("node") is None or not (REPO_ROOT / "data/metrics/atm_history.json").exists(), reason="node vagy a hírmentés nincs meg")
def test_detect_lang_matches_the_js_original_on_the_real_feed(tmp_path):
    items = json.loads((REPO_ROOT / "data/metrics/atm_history.json").read_text(encoding="utf-8"))["items"][:600]
    rows = [{"t": i.get("title") or "", "d": i.get("source_domain") or ""} for i in items]
    (tmp_path / "rows.json").write_text(json.dumps(rows), encoding="utf-8")
    js = tmp_path / "p.mjs"
    shutil.copy(REPO_ROOT / "public/js/modules/lang.js", tmp_path / "lang.mjs")
    js.write_text("import fs from 'node:fs';import {detectLang} from './lang.mjs';"
                  f"const r=JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'rows.json'))},'utf8'));console.log(JSON.stringify(r.map(x=>detectLang(x.t,x.d))));", encoding="utf-8")
    out = json.loads(subprocess.run(["node", str(js)], capture_output=True, text=True, check=True).stdout)
    mine = [detect_lang(r["t"], r["d"]) for r in rows]
    diffs = [(i, a, b) for i, (a, b) in enumerate(zip(out, mine)) if a != b]
    assert not diffs, diffs[:5]


# ---------------------------------------------------------------- kiválasztás

def sel_of(feed, cfg):
    return selection.select(feed["items"], cfg)


def test_selection_sizes_no_overlap_caps_and_determinism(cfg):
    feed = make_feed()
    s = sel_of(feed, cfg)
    a, m = [i["id"] for i in s["anchors"]], [i["id"] for i in s["measured"]]
    assert len(a) == 20 and len(m) == 30 and not set(a) & set(m) and len(set(a + m)) == 50
    assert max(s["source_counts"].values()) <= cfg["filters"]["source_cap_total"]
    assert len(s["measured_random_ids"]) == 15 and len(s["measured_enriched_ids"]) == 15
    s2 = sel_of(make_feed(), cfg)
    assert [i["id"] for i in s2["anchors"]] == a and [i["id"] for i in s2["measured"]] == m


def test_enriched_titles_really_have_a_formal_feature_and_anchor_mix(cfg):
    s = sel_of(make_feed(), cfg)
    by = {i["id"]: i for i in s["measured"]}
    assert all(any(selection.features(by[i]["title"]).values()) for i in s["measured_enriched_ids"])
    feats = [selection.features(i["title"]) for i in s["anchors"]]
    for k, n in cfg["anchor_mix"].items():
        assert sum(1 for f in feats if f[k]) >= n


def test_filters_exclude_official_short_long_duplicates_and_non_hungarian(cfg):
    base = make_titles(3, 99)[0]
    extra = [{"id": "off", "title": base + " a", "official": True, "source": "Hivatalos"},
             {"id": "alert", "title": base + " b", "alert": True, "source": "Riasztás"},
             {"id": "short", "title": "Rövid cím", "source": "S"},
             {"id": "long", "title": ("hosszú és szőlő " * 20), "source": "L"},
             {"id": "en", "title": "The government said that it will not change the new rule after the vote", "source": "EN"},
             {"id": "notitle", "title": "", "source": "X"}, {"id": "", "title": base, "source": "Y"},
             {"id": "orig", "title": base, "source": "O"}, {"id": "dup", "title": base.upper(), "source": "D"}, {"id": "near", "title": base + " is", "source": "N"}]
    pool, why = selection.eligible(make_feed(extra=extra)["items"], cfg)
    ids = {i["id"] for i in pool}
    assert not ids & {"off", "alert", "short", "long", "en", "notitle", ""}
    assert ("orig" in ids) + ("dup" in ids) + ("near" in ids) == 1                       # a három közel-azonos címből egy marad
    assert why["hivatalos_vagy_riasztas"] == 2 and why["duplikatum"] >= 2


def test_selection_fails_loudly_when_the_pool_is_too_small(cfg):
    with pytest.raises(ValueError):
        selection.select(make_feed(40)["items"], cfg)


def test_anchor_override_is_used_and_validated(cfg):
    feed = make_feed()
    ids = [i["id"] for i in sel_of(feed, cfg)["anchors"]][::-1]
    s = selection.select(feed["items"], cfg, ids)
    assert [i["id"] for i in s["anchors"]] == ids
    with pytest.raises(ValueError):
        selection.select(feed["items"], cfg, ["nincs-ilyen"] * 20)


# ---------------------------------------------------------------- feed

def test_pilot_feed_is_neutral_and_leaks_nothing(cfg):
    items = make_feed()["items"][:5]
    f = feeds.build_feed(items, "stage1")
    for r, it in zip(f["items"], items):
        assert set(r) == feeds.ROW_KEYS and r["title"] == it["title"] and r["id"] == it["id"]
        assert all(r[k] == 0 for k in feeds.NEUTRAL_KEYS) and r["source"] == "pilot" and r["link"] == "" and r["summary"] == ""
        assert it["source"] not in json.dumps(r) and it["link"] not in json.dumps(r)
    assert f["profiles"] == {} and f["model"] == {}


def test_select_command_writes_only_into_results_and_never_overwrites(tmp_path, cfg, feed_path):
    out = run.do_select(cfg, feed_path, base=tmp_path / "res")
    assert out["anchors"] == 20 and out["measured"] == 30
    names = {p.name for p in (tmp_path / "res").iterdir()}
    assert names == {"selection.json", "pilot_stage1_anchors.json", "pilot_stage2_measured.json", "anchor_preview.txt"}
    with pytest.raises(FileExistsError):
        run.do_select(cfg, feed_path, base=tmp_path / "res")
    s1 = json.loads((tmp_path / "res/pilot_stage1_anchors.json").read_text(encoding="utf-8"))
    s2 = json.loads((tmp_path / "res/pilot_stage2_measured.json").read_text(encoding="utf-8"))
    assert len(s1["items"]) == 20 and len(s2["items"]) == 30
    preview = (tmp_path / "res/anchor_preview.txt").read_text(encoding="utf-8")
    assert len(preview.strip().splitlines()) == 20 and all(i["title"] in preview for i in s1["items"])
    assert not any(i["title"] in preview for i in s2["items"])                             # a mérési címek nem kerülnek az előnézetbe


# ---------------------------------------------------------------- kappa és alfa

R1 = [0, 0, 1, 1, 2, 2, 0, 1, 2, 0]
R2 = [0, 1, 1, 1, 2, 0, 0, 1, 2, 0]


def test_cohen_kappa_known_values():
    assert an.cohen_kappa(R1, R2) == pytest.approx(0.69697, abs=1e-4)
    assert an.cohen_kappa(R1, R2, weighted=True) == pytest.approx(0.65116, abs=1e-4)
    assert an.cohen_kappa(R1, R1) == pytest.approx(1.0) and an.cohen_kappa(R1, R1, weighted=True) == pytest.approx(1.0)
    assert an.cohen_kappa([1, 1, 1], [1, 1, 1]) is None and an.cohen_kappa([], []) is None
    assert an.confusion(R1, R2) == [[3, 1, 0], [0, 3, 0], [1, 0, 2]]


def test_krippendorff_alpha_reference_example():
    # Krippendorff (2011) példa: 4 megfigyelő, 12 egység, hiányzó értékekkel; nominális α ≈ 0,743, intervallum α ≈ 0,849
    cols = {"A": "1 2 3 3 2 1 4 1 2 * * *", "B": "1 2 3 3 2 2 4 1 2 5 * 3", "C": "* 3 3 3 2 3 4 2 2 5 1 *", "D": "1 2 3 3 2 4 4 1 2 5 1 *"}
    units = [[int(c.split()[u]) - 1 for c in cols.values() if c.split()[u] != "*"] for u in range(12)]
    assert an.krippendorff_alpha(units, "nominal", k=5) == pytest.approx(0.743, abs=1e-3)
    assert an.krippendorff_alpha(units, "interval", k=5) == pytest.approx(0.849, abs=1e-3)
    assert an.krippendorff_alpha([[0, 0], [1, 1], [2, 2]]) == pytest.approx(1.0)
    assert an.krippendorff_alpha([[1]]) is None


# ---------------------------------------------------------------- beolvasás

def write_exports(tmp_path, voters_votes, skipped=None, fmt="lines"):
    backs = [backup(v, vs, (skipped or {}).get(v, ())) for v, vs in voters_votes.items()]
    p = tmp_path / "export.txt"
    p.write_text("\n".join(json.dumps(b) for b in backs) if fmt == "lines" else json.dumps(backs if fmt == "array" else backs[0]), encoding="utf-8")
    return p


@pytest.mark.parametrize("fmt", ["lines", "array"])
def test_parse_exports_formats_and_filters(tmp_path, cfg, fmt):
    p = write_exports(tmp_path, {"A": [("x1", "fact"), ("x2", "bait"), ("x3", "mid"), ("x4", "fact", False)], "B": [("x1", "mid")]}, fmt=fmt)
    votes, rep = an.parse_exports([p], cfg)
    got = {(v["voter"], v["id"]): v["ordinal"] for v in votes}
    assert got == {("A", "x1"): 0, ("A", "x2"): 2, ("A", "x3"): 1, ("B", "x1"): 1}
    assert rep["not_blind"] == 1 and rep["backups"] == 2 and rep["files"][0]["sha256"]


def test_parse_exports_mids_list_duplicates_and_bad_records(tmp_path, cfg):
    b = backup("A", [("x1", "fact"), ("x1", "bait")], mids=[{"id": "x2", "vote": "mid", "title": "t", "ts": 5, "blind": True, "voter": "A"}])
    b["votes"][0]["ts"], b["votes"][1]["ts"] = 10, 5                                    # az újabb időbélyegű marad
    b["votes"] += [{"id": "bad", "vote": "maybe", "blind": True}, "szemét", {"vote": "fact", "blind": True}]
    p = tmp_path / "e.json"
    p.write_text(json.dumps(b), encoding="utf-8")
    votes, rep = an.parse_exports([p], cfg)
    assert {(v["id"], v["ordinal"]) for v in votes} == {("x1", 0), ("x2", 1)} and rep["duplicates_replaced"] == 1 and rep["invalid"] == 3


def test_parse_exports_ignores_foreign_json_and_garbage_lines(tmp_path, cfg):
    p = tmp_path / "e.txt"
    p.write_text('{"format": "mas"}\nnem json\n' + json.dumps(backup("A", [("x1", "fact")])), encoding="utf-8")
    votes, rep = an.parse_exports([p], cfg)
    assert len(votes) == 1 and rep["backups"] == 1


# ---------------------------------------------------------------- kapu

def votes_for(ids, a, b, tmp_path, cfg, c=None):
    vv = {"A": [(i, k) for i, k in zip(ids, a)], "B": [(i, k) for i, k in zip(ids, b)]}
    if c:
        vv["C"] = [(i, k) for i, k in zip(ids, c)]
    votes, rep = an.parse_exports([write_exports(tmp_path, vv)], cfg)
    return votes, rep


KIND = {0: "fact", 1: "mid", 2: "bait"}


def mk(rows, tmp_path, cfg):
    ids = [f"m{i:02d}" for i in range(len(rows))]
    return ids, *votes_for(ids, [KIND[r[0]] for r in rows], [KIND[r[1]] for r in rows], tmp_path, cfg)


def test_gate_pass_fail_and_inconclusive(tmp_path, cfg):
    good = [(0, 0)] * 10 + [(1, 1)] * 8 + [(2, 2)] * 8 + [(0, 1), (1, 2), (1, 0), (2, 1)]
    ids, votes, rep = mk(good, tmp_path, cfg)
    g = an.gate(an.ratings(votes, set(ids)), cfg)
    assert g["decision"] == "atment" and g["kappa_weighted"] > 0.5 and not g["warnings"]
    bad = [(0, 2), (2, 0), (1, 0), (0, 1), (2, 1), (1, 2)] * 5
    ids, votes, rep = mk(bad, tmp_path, cfg)
    g = an.gate(an.ratings(votes, set(ids)), cfg)
    assert g["decision"] == "elbukott" and g["kappa_weighted"] < 0.5
    small = [(0, 0), (1, 1), (2, 2), (0, 1), (1, 0), (2, 2), (0, 0), (1, 2)]
    ids, votes, rep = mk(small, tmp_path, cfg)
    g = an.gate(an.ratings(votes, set(ids)), cfg)
    assert g["decision"] in ("eldonthetetlen", "elbukott", "atment") and g["n_common"] == 8


def test_gate_flags_dominant_class_and_unmeasurable(tmp_path, cfg):
    rows = [(0, 0)] * 27 + [(1, 1)] + [(2, 2)] + [(0, 1)]
    ids, votes, rep = mk(rows, tmp_path, cfg)
    g = an.gate(an.ratings(votes, set(ids)), cfg)
    assert any("80%" in w for w in g["warnings"]) and any("kevesebb" in w for w in g["warnings"])
    ids, votes, rep = mk([(1, 1)] * 20, tmp_path, cfg)
    assert an.gate(an.ratings(votes, set(ids)), cfg)["decision"] == "nem_szamolhato"


def test_reference_is_the_mean_of_all_votes_and_third_vote_list(tmp_path, cfg):
    ids = ["m1", "m2", "m3"]
    votes, rep = votes_for(ids, ["fact", "bait", "mid"], ["fact", "mid", "mid"], tmp_path, cfg, c=["fact", "bait", "mid"])
    rat = an.ratings(votes, set(ids))
    ref = an.reference(rat)
    assert ref["m1"]["human_mean"] == 0 and ref["m2"]["human_mean"] == pytest.approx(5 / 3) and ref["m2"]["majority"] == 2 and ref["m3"]["majority"] == 1
    assert an.adjudication_ids({k: {x: y for x, y in v.items() if x != "C"} for k, v in rat.items()}, ["A", "B"]) == ["m2"]


def test_usage_stats_mid_and_skip_share(tmp_path, cfg):
    ids = [f"m{i}" for i in range(10)]
    votes, rep = votes_for(ids, ["mid"] * 7 + ["fact"] * 3, ["mid"] * 10, tmp_path, cfg)
    u = an.usage_stats(votes, set(ids), {"A": ["m1x"]}, cfg)
    assert u["mid_share"] == pytest.approx(0.85) and u["mid_share_ok"] is False and u["skipped"] == 0


# ---------------------------------------------------------------- teljes folyamat és lezárás

def full_flow(tmp_path, cfg, feed_path, agree=True):
    res = tmp_path / "res"
    run.do_select(cfg, feed_path, base=res)
    sel = json.loads((res / "selection.json").read_text(encoding="utf-8"))
    ids = sel["anchor_ids"] + sel["measured_ids"]
    a = [KIND[(n * 7) % 3] for n in range(len(ids))]
    b = a[:] if agree else [KIND[(n * 5 + 1) % 3] for n in range(len(ids))]
    c = a[:]
    exp = write_exports(tmp_path, {"A": list(zip(ids, a)), "B": list(zip(ids, b)), "C": list(zip(ids, c))})
    return res, sel, exp


def test_analyze_adjudication_and_freeze_flow(tmp_path, cfg, feed_path):
    res, sel, exp = full_flow(tmp_path, cfg, feed_path)
    out = run.do_analyze(cfg, [exp], base=res)
    assert out["gate"]["decision"] == "atment" and out["coverage"] == {"measured_all_primary_voted": 30, "measured_total": 30}
    assert (res / "human_reference.csv").read_text(encoding="utf-8").count("\n") == 31 and out["adjudication_ids"] == []
    assert run.do_adjudication(cfg, [exp], feed_path, base=res) == {"adjudication_titles": 0}
    with pytest.raises(freeze.NotFrozen):
        freeze.require_freeze(res, cfg)                                                      # lezárás előtt a modell nem indítható
    man = run.do_freeze(cfg, [exp], base=res)
    assert man["gate"]["decision"] == "atment" and len(man["measured_ids"]) == 30
    assert freeze.require_freeze(res, cfg, [exp])["created_utc"]
    with pytest.raises(FileExistsError):
        run.do_freeze(cfg, [exp], base=res)


def test_freeze_is_refused_when_the_gate_failed_and_detects_later_changes(tmp_path, cfg, feed_path):
    res, sel, exp = full_flow(tmp_path, cfg, feed_path, agree=False)
    out = run.do_analyze(cfg, [exp], base=res)
    assert out["gate"]["decision"] != "atment" and out["adjudication_ids"]
    if out["gate"]["decision"] == "elbukott":
        with pytest.raises(freeze.NotFrozen):
            run.do_freeze(cfg, [exp], base=res)
    res2, sel2, exp2 = full_flow(tmp_path / "ok", cfg, feed_path) if (tmp_path / "ok").mkdir() is None else (None, None, None)
    run.do_analyze(cfg, [exp2], base=res2)
    run.do_freeze(cfg, [exp2], base=res2)
    exp2.write_text(exp2.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(freeze.NotFrozen):
        freeze.require_freeze(res2, cfg, [exp2])
    (res2 / "human_reference.csv").write_text("x", encoding="utf-8")
    with pytest.raises(freeze.NotFrozen):
        freeze.require_freeze(res2, cfg)


def test_adjudication_feed_contains_only_the_disagreeing_measured_titles(tmp_path, cfg, feed_path):
    res, sel, exp = full_flow(tmp_path, cfg, feed_path, agree=False)
    out = run.do_analyze(cfg, [exp], base=res)
    r = run.do_adjudication(cfg, [exp], feed_path, base=res)
    f = json.loads((res / "pilot_stage3_adjudication.json").read_text(encoding="utf-8"))
    assert r["adjudication_titles"] == len(out["adjudication_ids"]) == len(f["items"]) and {i["id"] for i in f["items"]} == set(out["adjudication_ids"])
    assert set(out["adjudication_ids"]) <= set(sel["measured_ids"])


# ---------------------------------------------------------------- elkülönítés

def test_writes_are_confined_to_the_results_dir(tmp_path):
    with pytest.raises(IsolationError):
        check_write(tmp_path / "x.json", tmp_path / "results")
    with pytest.raises(IsolationError):
        check_write(tmp_path / "results" / ".." / "x.json", tmp_path / "results")


def test_module_has_no_network_model_env_or_other_module_imports():
    banned = {"requests", "urllib", "http", "socket", "anthropic", "openai", "google", "httpx", "subprocess", "os"}
    for f in MOD.glob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            names = [a.name for a in n.names] if isinstance(n, ast.Import) else ([n.module or ""] if isinstance(n, ast.ImportFrom) and not n.level else [])
            for nm in names:
                assert nm.split(".")[0] not in banned and not nm.startswith("validation.webis_validation"), (f.name, nm)
        src = f.read_text(encoding="utf-8")
        assert "environ" not in src and "getenv" not in src and "GROQ" not in src and "GEMINI" not in src, f.name


def test_results_are_ignored_by_git():
    t = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "validation/hu_pilot/results/*" in t


def test_source_cap_holds_even_when_one_source_dominates_the_feed(cfg):
    feed = make_feed(400)
    for i, it in enumerate(feed["items"]):
        if i % 3 == 0:
            it["source"] = "| Nagy Forrás"                                           # a hírek harmada egy forrásból (a normalizálás után is egy)
    s = selection.select(feed["items"], cfg)
    cnt = {}
    for it in s["anchors"] + s["measured"]:
        k = selection.source_key(it["source"])
        cnt[k] = cnt.get(k, 0) + 1
    assert cnt["nagy forrás"] <= cfg["filters"]["source_cap_total"] and max(cnt.values()) <= cfg["filters"]["source_cap_total"]
