"""A Pilot-állapot próbája a pipeline valódi köztes állapotain (üres, kiválasztva, csomagolva, részleges és teljes szavazás, elemzés, lezárás, kvótamegállt futás). Csak olvas; az eredménymappa nem változik, és csak szavazóbetűk szerepelnek."""
import json

import pytest

from validation.hu_pilot import pilotstate as ps
from validation.hu_pilot import run
from .test_four_voters import four_voter_exports, write_exports
from .test_hu_pilot import KIND
from .test_packaging import make_app


def state(res, cfg, exports=()):
    return ps.assess(ps.collect(res, cfg, list(exports)), cfg)


def nxt(out):
    return " | ".join(out["next"])


@pytest.fixture
def sel_res(tmp_path, cfg, feed_path):
    res = tmp_path / "res"
    run.do_select(cfg, feed_path, base=res)
    return res, json.loads((res / "selection.json").read_text(encoding="utf-8"))


def test_empty_selected_and_packaged_states_give_the_right_next_step(tmp_path, cfg, feed_path):
    res = tmp_path / "res"
    res.mkdir()
    assert "Nincs kiválasztás" in nxt(state(res, cfg))
    run.do_select(cfg, feed_path, base=res)
    o = state(res, cfg)
    assert o["selection"]["anchors"] == 20 and o["selection"]["measured"] == 30 and "Hiányzó csomag: 1. szakasz, 2. szakasz, 4. szakasz" in nxt(o)
    app = make_app(tmp_path)
    for s in (1, 2, 4):
        run.do_package(cfg, app, s, "abc123", base=res)
    o = state(res, cfg)
    assert all(v["sha_ok"] for v in o["stages"].values()) and "Hiányzó csomag" not in nxt(o) and "Add meg a szavazói exportokat" in nxt(o)


def test_a_zip_that_no_longer_matches_its_manifest_is_reported(tmp_path, cfg, feed_path):
    res = tmp_path / "res"
    run.do_select(cfg, feed_path, base=res)
    run.do_package(cfg, make_app(tmp_path), 2, "abc123", base=res)
    zp = res / "deploy" / "mz_pilot_stage2.zip"
    zp.write_bytes(zp.read_bytes() + b"x")
    assert "nem egyezik a jegyzékkel: 2. szakasz" in nxt(state(res, cfg))


def votes_for_groups(sel, who):
    """who: {betű: [csoportok]} -> exportfájl-tartalom: a megadott csoportok minden címére szavaz."""
    groups = {"anchors": sel["anchor_ids"], "measured": sel["measured_ids"]}
    return {v: [(i, KIND[(n * 7) % 3]) for g in gs for n, i in enumerate(groups[g])] for v, gs in who.items()}


def test_partial_voting_names_who_is_still_missing_and_complete_voting_points_to_analyze(tmp_path, cfg, sel_res):
    import copy
    cfg = copy.deepcopy(cfg)
    cfg["gate"]["min_voters"] = 4                                                           # a négy szavazós ág a régi küszöbbel
    res, sel = sel_res
    exp = write_exports(tmp_path, votes_for_groups(sel, {"A": ["anchors", "measured"], "B": ["anchors", "measured"], "C": ["anchors"], "D": ["anchors"]}))
    o = state(res, cfg, [exp])
    assert o["complete"]["anchors"] == ["A", "B", "C", "D"] and o["complete"]["measured"] == ["A", "B"]
    assert "kész 2 / 4 szavazó (A, B); hiányzik: C, D" in nxt(o)
    (tmp_path / "x").mkdir()
    (tmp_path / "y").mkdir()
    assert state(res, cfg, [write_exports(tmp_path / "x", votes_for_groups(sel, {"A": ["anchors"], "B": ["anchors"]}))])["next"][-1].startswith("A horgonykör szavazása még nem teljes: kész 2 / 4")
    part = votes_for_groups(sel, {v: ["anchors", "measured"] for v in "ABCD"})
    part["C"] = part["C"][:25]                                                                # a horgonyok mind megvannak, de a mérési címekből csak 5
    (tmp_path / "z").mkdir()
    o2 = state(res, cfg, [write_exports(tmp_path / "z", part)])
    assert o2["complete"]["measured"] == ["A", "B", "D"] and "hiányzik: C" in nxt(o2) and o2["votes"]["by_voter"]["C"]["measured"] == 5
    full = write_exports(tmp_path / "y", votes_for_groups(sel, {v: ["anchors", "measured"] for v in "ABCD"}))
    assert "run analyze" in nxt(state(res, cfg, [full]))


def test_gate_freeze_and_a_quota_stopped_run_lead_to_the_right_next_steps(tmp_path, cfg, sel_res):
    res, sel = sel_res
    exp = four_voter_exports(tmp_path, sel)
    run.do_analyze(cfg, [exp], base=res)
    o = state(res, cfg, [exp])
    assert o["gate"]["decision"] in ("atment", "eldonthetetlen", "elbukott")
    if o["gate"]["decision"] != "elbukott":
        assert "a lezárás a felhasználó döntése" in nxt(o)
        run.do_freeze(cfg, [exp], base=res)
        o = state(res, cfg, [exp])
        assert o["frozen"] and "export-bundle" in nxt(o) and "csak a felhasználó indíthatja" in nxt(o)
        d = res / "model_runs" / "kv"
        d.mkdir(parents=True)
        (d / "state.json").write_text(json.dumps({"provider": "gemini", "status": "stopped_quota", "ids": ["a"] * 50}), encoding="utf-8")
        o = state(res, cfg, [exp])
        assert o["runs"] == [{"name": "kv", "provider": "gemini", "status": "stopped_quota", "titles": 50}] and "Kvótafigyelővel" in nxt(o)


@pytest.mark.parametrize("decision,expected", [("elbukott", "A kapu elbukott"), ("nem_szamolhato", "A kapu nem számolható"), ("atment", "a lezárás a felhasználó döntése"), ("eldonthetetlen", "eldönthetetlen")])
def test_every_gate_decision_has_its_own_next_step(cfg, decision, expected):
    info = {"selection": {"anchor_ids": ["a"], "measured_ids": ["m"]}, "analysis": {"gate": {"decision": decision, "alpha": 0.4, "alpha_min": 0.5, "voters": list("ABCD"), "warnings": []}},
            "frozen": False, "stages": {s: {"zip": True, "manifest": True, "sha_ok": True} for s in "124"}, "runs": [],
            "votes": {"sizes": {"anchors": 1, "measured": 1}, "by_voter": {v: {"anchors": 1, "measured": 1} for v in "ABCD"}}}
    assert expected in nxt(ps.assess(info, cfg))


def test_the_report_only_contains_voter_letters_and_counts_and_changes_nothing(tmp_path, cfg, sel_res, capsys):
    res, sel = sel_res
    exp = four_voter_exports(tmp_path, sel)
    before = {str(p): p.read_bytes() for p in sorted(res.rglob("*")) if p.is_file()}
    exp_before = exp.read_bytes()
    assert ps.main(["--results", str(res), "--exports", str(exp)]) == 0
    text = capsys.readouterr().out
    assert after_same(res, before) and exp.read_bytes() == exp_before
    titles = [json.loads((res / "pilot_stage1_anchors.json").read_text(encoding="utf-8"))["items"][0]["title"]]
    assert not any(t in text for t in titles) and "A: anchors 20/20, measured 30/30, foreign_en 20/20" in text and "ts" not in text.split("Következő lépés")[0].lower().split()
    assert ps.main(["--results", str(tmp_path / "nincs")]) == 0 and "Nincs kiválasztás" in capsys.readouterr().out


def after_same(res, before):
    return {str(p): p.read_bytes() for p in sorted(res.rglob("*")) if p.is_file()} == before


def test_with_two_required_voters_the_state_points_to_analyze_when_a_and_b_are_done(tmp_path, cfg, sel_res):
    res, sel = sel_res
    assert cfg["gate"]["min_voters"] == 2
    exp = write_exports(tmp_path, votes_for_groups(sel, {"A": ["anchors", "measured"], "B": ["anchors", "measured"], "C": ["anchors"], "D": ["anchors"]}))
    assert "run analyze" in nxt(state(res, cfg, [exp]))
    (tmp_path / "p").mkdir()
    only_a = write_exports(tmp_path / "p", votes_for_groups(sel, {"A": ["anchors", "measured"], "B": ["anchors"]}))
    o = state(res, cfg, [only_a])
    assert o["complete"]["measured"] == ["A"] and "kész 1 / 2 szavazó (A); hiányzik: B" in nxt(o)
