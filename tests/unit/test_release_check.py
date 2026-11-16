"""A Kiadási ellenőr próbája: git, hálózat és kulcs nélkül (a tiszta függvényeken), plusz egy valódi, ideiglenes git-tárolón a collect-hez nem; azt a fő tesztek hamis bemenete fedi."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import policy_guard as pg  # noqa: E402
import release_check as rc  # noqa: E402

P = pg.load_policy()


def ev(changes, approved, allow_delete=(), files=None):
    files = files or {}
    tracked = [p for _, p in changes]
    return rc.evaluate(changes, list(approved), list(allow_delete), lambda p: files.get(p), tracked, P)


def stops(res):
    return {(s["rule"], s["where"]) for s in res["stops"]}


def test_glob_double_star_matches_any_depth_and_single_star_only_one_level():
    assert rc.matches("public/css/a.css", ["public/**"]) and rc.matches("public/a.css", ["public/**"])
    assert rc.matches("public/a.css", ["public/*"]) and not rc.matches("public/css/a.css", ["public/*"])
    assert rc.matches("PROJECT_VERSION", ["PROJECT_VERSION"]) and not rc.matches("PROJECT_VERSION2", ["PROJECT_VERSION"])
    assert rc.matches("a/b/c.py", ["**/c.py"]) and rc.matches("c.py", ["**/c.py"]) and not rc.matches("a/xc.py", ["**/c.py"])
    assert not rc.matches("publicx/a", ["public/**"])                          # a pont és a perjel nem joker


def test_change_inside_approved_scope_is_ok():
    r = ev([("M", "public/index.html"), ("A", "public/js/a.js"), ("M", "PROJECT_VERSION")], ["public/**", "PROJECT_VERSION"], files={"public/index.html": "x"})
    assert r["verdict"] == "RENDBEN" and r["stops"] == []
    assert r["summary"]["added"] == ["public/js/a.js"] and r["summary"]["modified"] == ["PROJECT_VERSION", "public/index.html"]


def test_file_outside_scope_stops():
    r = ev([("M", "public/index.html"), ("M", "docs/PILOT_RUNBOOK.md")], ["public/**"])
    assert r["verdict"] == "MEGÁLLNI" and stops(r) == {("jovahagyott-koron-kivul", "docs/PILOT_RUNBOOK.md")}


def test_deletion_stops_unless_explicitly_allowed_even_inside_the_scope():
    ch = [("D", "public/old.js"), ("M", "public/index.html")]
    assert stops(ev(ch, ["public/**"])) == {("torles", "public/old.js")}
    assert ev(ch, ["public/**"], ["public/old.js"])["verdict"] == "RENDBEN"
    assert stops(ev(ch, ["public/**"], ["docs/**"])) == {("torles", "public/old.js")}            # más törlési minta nem engedi


def test_empty_approved_scope_always_stops():
    r = ev([("M", "public/a")], [])
    assert ("nincs-jovahagyott-kor", "") in stops(r)


def test_guard_errors_stop_even_inside_the_scope_and_warnings_do_not():
    r = ev([("A", "results/x.csv")], ["results/**"])
    assert ("orzo:results-commit", "results/x.csv") in stops(r)
    key = "AIza" + "C" * 30
    r = ev([("M", "public/a.py")], ["public/**"], files={"public/a.py": f'k = "{key}"'})
    assert ("orzo:secret", "public/a.py:1") in stops(r) and key not in str(r)
    r = ev([("M", "validation/hu_pilot/x.py")], ["validation/**"], files={"validation/hu_pilot/x.py": "label_weight = 2\n"})
    assert r["verdict"] == "RENDBEN" and [w["rule"] for w in r["warnings"]] == ["weighting"]


def test_main_returns_2_for_missing_branch(capsys):
    assert rc.main(["--head", "nincs-ilyen-ag-xyz", "--approved", "x"]) == 2


def test_rename_is_a_deletion_of_the_old_path_plus_an_addition_and_copy_is_only_an_addition():
    ch = rc.parse_name_status("R100\tpublic/a.js\tdocs/a.js\nC100\tpublic/b.js\tpublic/c.js\nM\tpublic/d.js\nD\tpublic/e.js\n")
    assert ch == [("D", "public/a.js"), ("A", "docs/a.js"), ("A", "public/c.js"), ("M", "public/d.js"), ("D", "public/e.js")]
    r = ev(ch, ["public/**"])
    assert stops(r) == {("torles", "public/a.js"), ("torles", "public/e.js"), ("jovahagyott-koron-kivul", "docs/a.js")}
