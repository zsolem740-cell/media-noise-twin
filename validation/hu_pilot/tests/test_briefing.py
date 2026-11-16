"""Az Elemző (megbeszélő lap) próbája: ismert szavazatokból ismert számok; a lap csak betűket és címeket tartalmaz; az export és a repó érintetlen marad."""
import json

import pytest

from validation.hu_pilot import briefing as B
from validation.hu_pilot.paths import IsolationError

KIND = {0: "fact", 1: "mid", 2: "bait"}


def export(tmp_path, voter, votes, titles):
    p = tmp_path / f"szavazatok-{voter}.json"
    rows = [{"id": i, "vote": KIND[v], "title": titles[i], "ts": 1000 + n, "blind": True, "voter": voter, "domain": "x"} for n, (i, v) in enumerate(votes.items())]
    p.write_text(json.dumps({"format": "mnt-backup", "version": 1, "voter": voter, "votes": rows, "mids": [], "skipped": []}), encoding="utf-8")
    return str(p)


def setup(tmp_path, matrix, titles=None):
    """matrix: {cím-azonosító: {szavazó: 0/1/2}}"""
    ids = list(matrix)
    titles = titles or {i: f"Cím {i}" for i in ids}
    res = tmp_path / "res"
    res.mkdir()
    (res / "selection.json").write_text(json.dumps({"anchor_ids": ids, "measured_ids": []}), encoding="utf-8")
    voters = sorted({v for r in matrix.values() for v in r})
    paths = [export(tmp_path, v, {i: matrix[i][v] for i in ids if v in matrix[i]}, titles) for v in voters]
    return res, paths, ids


M = {"a": {"A": 0, "B": 0, "C": 0, "D": 0},        # egyhangú
     "b": {"A": 2, "B": 2, "C": 2, "D": 2},        # egyhangú
     "c": {"A": 0, "B": 0, "C": 2, "D": 2},        # vitatott (sd = 1)
     "d": {"A": 0, "B": 1, "C": 1, "D": 1},        # nem vitatott (sd < 0,8)
     "e": {"A": 1, "B": 1, "C": 1, "D": 0}}


def test_known_votes_give_known_numbers(tmp_path, cfg):
    res, paths, ids = setup(tmp_path, M)
    rows, voters, st = B.build(__import__("validation.hu_pilot.analysis", fromlist=["x"]).parse_exports(paths, cfg)[0], ids, cfg)
    assert voters == ["A", "B", "C", "D"] and st["n_titles"] == 5 and st["n_unanimous"] == 2 and st["n_contested"] == 1
    assert [r["contested"] for r in rows] == [False, False, True, False, False] and [r["n"] for r in rows] == [1, 2, 3, 4, 5]
    assert st["strictness"] == {"A": (0 + 2 + 0 + 0 + 1) / 5, "B": (0 + 2 + 0 + 1 + 1) / 5, "C": (0 + 2 + 2 + 1 + 1) / 5, "D": (0 + 2 + 2 + 1 + 0) / 5}
    assert rows[2]["sd"] == pytest.approx(1.0) and st["n_complete_titles"] == 5


def test_perfect_agreement_gives_alpha_one_and_no_questions(tmp_path, cfg):
    same = {"x": {"A": 0, "B": 0}, "y": {"A": 1, "B": 1}, "z": {"A": 2, "B": 2}, "w": {"A": 0, "B": 0}}
    res, paths, ids = setup(tmp_path, same)
    r = B.make(paths, cfg, "anchors", base=res)
    assert r["stats"]["alpha_ordinal"] == pytest.approx(1.0) and r["stats"]["n_contested"] == 0 and r["n_questions"] == 0
    assert "Nincs vitatott cím" in (res / r["file"]).read_text(encoding="utf-8")


def test_questions_name_the_voters_by_letter_sorted_by_dispute_and_capped(tmp_path, cfg):
    mild = {"A": 0, "B": 0, "C": 0, "D": 2}                       # szórás 0,87
    strong = {"A": 0, "B": 0, "C": 2, "D": 2}                     # szórás 1,0
    big = {f"t{i}": dict(mild) for i in range(8)}
    big["t8"] = dict(strong)                                      # a sorrendben hátul, de a legvitatottabb
    res, paths, ids = setup(tmp_path, big)
    import validation.hu_pilot.analysis as A
    rows, voters, st = B.build(A.parse_exports(paths, cfg)[0], ids, cfg)
    qs = B.questions(rows, cfg["label_names"])
    assert len(qs) == B.MAX_QUESTIONS == 6 and st["n_contested"] == 9
    assert qs[0]["n"] == 9 and qs[0]["text"].startswith("A, B: Nyugodt; C, D: Hangos.") and "Melyik szava" in qs[0]["text"]
    assert [q["n"] for q in qs[1:]] == [1, 2, 3, 4, 5]            # azonos szórásnál a sorrend a cím száma szerint


def test_a_title_missing_one_voter_is_not_unanimous(tmp_path, cfg):
    res, paths, ids = setup(tmp_path, {"a": {"A": 0, "B": 0, "C": 0}, "b": {"A": 1, "B": 1, "C": 1, "D": 1}})
    import validation.hu_pilot.analysis as A
    rows, voters, st = B.build(A.parse_exports(paths, cfg)[0], ids, cfg)
    assert [r["unanimous"] for r in rows] == [False, True] and st["n_unanimous"] == 1 and st["n_complete_titles"] == 1


def test_page_escapes_titles_has_only_letters_and_no_personal_terms(tmp_path, cfg):
    evil = {"a": '<script>alert("x")</script> & "idézet"', "b": "Rendes cím"}
    res, paths, ids = setup(tmp_path, {"a": {"A": 0, "B": 2}, "b": {"A": 1, "B": 1}}, evil)
    page = (res / B.make(paths, cfg, "anchors", base=res)["file"]).read_text(encoding="utf-8")
    assert "<script>alert" not in page.split("<main>")[1] and "&lt;script&gt;" in page and "&amp;" in page
    import re
    for banned in ("éves", "férfi", " nő ", "lány"):
        assert banned not in page
    assert not re.search(r"\w@\w", page)                                                     # nincs e-mail-cím
    assert "<b>A</b>" in page and "<b>B</b>" in page and "Nyugodt" in page and "Hangos" in page


def test_exports_stay_byte_identical_and_output_goes_only_to_the_results_dir(tmp_path, cfg):
    res, paths, ids = setup(tmp_path, M)
    before = {p: open(p, "rb").read() for p in paths}
    B.make(paths, cfg, "anchors", base=res)
    assert {p: open(p, "rb").read() for p in paths} == before
    assert (res / "megbeszelo_anchors.html").exists()
    with pytest.raises(IsolationError):
        B.make(paths, cfg, "anchors", out_name="../kint.html", base=res)
    assert not (tmp_path / "kint.html").exists()


def test_missing_group_votes_are_refused_with_a_clear_message(tmp_path, cfg, capsys):
    res, paths, ids = setup(tmp_path, M)
    with pytest.raises(ValueError, match="nincs egyetlen vak szavazat"):
        B.make(paths, cfg, "measured", base=res)


def test_non_blind_votes_do_not_count(tmp_path, cfg):
    res, paths, ids = setup(tmp_path, {"a": {"A": 0, "B": 0}})
    d = json.loads(open(paths[0], encoding="utf-8").read())
    d["votes"][0]["blind"] = False
    open(paths[0], "w", encoding="utf-8").write(json.dumps(d))
    with pytest.raises(ValueError):
        B.make([paths[0]], cfg, "anchors", base=res)
