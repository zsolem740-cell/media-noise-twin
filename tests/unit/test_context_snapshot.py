"""A kontextus snapshot script tesztjei: maszkolás (a csonkolás előtt, csak az érték), kizárt mappák, részekre bontás, a docstring igazsága. Hálózat nincs."""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "context_snapshot.py"
def mk(*parts):
    """A kitalált titkokat futásidőben illesztjük össze, hogy a forrásban ne legyen kulcsforma-literál (a code_guard joggal tiltja)."""
    return "".join(parts)


KEY = mk("AIza", "SyFAKEFAKEFAKEFAKEFAKE12345")          # kitalált, nem valódi kulcs


@pytest.fixture
def cs(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("context_snapshot_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(mod, "ROOT", root)
    mod.TEST_ROOT = root
    return mod


def put(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ---------------------------------------------------------------- maszkolás

@pytest.mark.parametrize("raw,kept", [
    (mk("GEMINI_API_", 'KEY="realvalue12345678"'), mk("GEMINI_API_", 'KEY="[REDACTED_SECRET]"')),
    (mk("api_", "key = abc1234567890"), mk("api_", "key = [REDACTED_SECRET]")),
    (mk("pass", "word: hunter2hunter2"), mk("pass", "word: [REDACTED_SECRET]")),
    (mk("Authorization: Bear", "er abcdefghijklmnopqrstuvwxyz123456"), mk("Authorization: Bear", "er [REDACTED_SECRET]")),
])
def test_assignments_and_bearer_keep_the_name_and_hide_only_the_value(cs, raw, kept):
    assert cs.redact_secrets(raw) == kept


@pytest.mark.parametrize("secret", [KEY, mk("gsk", "_abcdefghijklmnopqrstuvwx1234"), mk("sk", "-abcdefghijklmnopqrstuvwxyz12"), mk("gh", "p_abcdefghijklmnopqrstuvwx1234"), mk("github_", "pat_abcdefghijklmnopqrst12")])
def test_known_key_shapes_are_replaced_entirely(cs, secret):
    out = cs.redact_secrets(f"x = '{secret}' # megjegyzés")
    assert secret not in out and "[REDACTED_SECRET]" in out and out.endswith("# megjegyzés")


def test_short_values_and_ordinary_code_are_left_alone(cs):
    for line in ("max_tokens = 1024", mk("tok", "en = 'x'"), "tokens_used += 5", mk("def f(api_", "key):")):
        assert cs.redact_secrets(line) == line


def test_a_key_straddling_the_truncation_boundary_is_masked_before_cutting(cs):
    for cut in range(0, len(KEY) + 1, 3):                                     # a határ a kulcs minden helyén
        root = cs.TEST_ROOT
        text = "a" * 200 + f"\nvalue = {KEY}\n" + "z" * 400                # névtelen kulcs: csak a kulcsforma maszkolhatja
        f = put(root, "app.py", text)
        boundary = text.index(KEY) + cut                                      # ennyi bájtnál vág a script
        out, truncated = cs.read_limited(f, boundary)
        assert truncated and "[TRUNCATED_FOR_CONTEXT_SNAPSHOT]" in out
        for frag in (KEY[:8], KEY[-8:], "FAKEFAKE"):
            assert frag not in out, (cut, frag)


def test_untruncated_files_are_masked_too(cs):
    f = put(cs.TEST_ROOT, "a.py", f"k = '{KEY}'\n")
    out, truncated = cs.read_limited(f, 10_000)
    assert not truncated and KEY not in out and "[REDACTED_SECRET]" in out


def test_truncation_is_exact_for_ascii(cs):
    f = put(cs.TEST_ROOT, "x.txt", "x" * 500)
    out, truncated = cs.read_limited(f, 100)
    assert truncated and out.startswith("x" * 100 + "\n") and not out.startswith("x" * 101)


def test_truncation_cuts_by_bytes_not_characters(cs):
    f = put(cs.TEST_ROOT, "hu.txt", "ő" * 500)                                 # 2 bájtos karakterek
    out, truncated = cs.read_limited(f, 100)
    assert truncated and out.startswith("ő" * 50) and not out.startswith("ő" * 51)


# ---------------------------------------------------------------- kizárások

@pytest.mark.parametrize("rel,ignored", [
    ("data/metrics/gemini_labels.json", True), ("validation/webis_validation/data/truth.json", True), ("mentesek/A.txt", True),
    ("results/token_ledger.csv", True), ("validation/hu_pilot/results/analysis.json", True), (".env", True), (".env.local", True),
    ("context_snapshot.txt", True), ("context_snapshot_part2.txt", True), ("dist_releases/x.zip", True), ("notes.exe", True),
    ("CLAUDE.md", False), ("scripts/a.py", False), ("docs/PILOT_RUNBOOK.md", False), ("validation/hu_pilot/config.json", False),
])
def test_ignore_rules(cs, rel, ignored):
    assert cs.is_ignored(Path(rel)) is ignored


# ---------------------------------------------------------------- teljes snapshot

def make_repo(cs):
    root = cs.TEST_ROOT
    put(root, "CLAUDE.md", "# Korlátok\nTilos az élő API-hívás.\n")
    put(root, "src/a.py", "print('a')\n")
    put(root, "src/b.py", f"KEY = '{KEY}'\n")
    put(root, "data/metrics/gemini_labels.json", '{"valódi": "adat"}')
    put(root, "mentesek/A.json", '{"szavazat": 1}')
    put(root, ".env", mk("TOK", "EN=shouldnotappear12345\n"))
    put(root, "results/x.json", "{}")
    return root


def test_snapshot_has_claude_md_first_masks_keys_and_skips_real_data(cs):
    root = make_repo(cs)
    out = root / "context_snapshot.txt"
    written = cs.build_snapshot(out, 40_000)
    text = out.read_text(encoding="utf-8")
    assert written == [out]
    assert text.index("=== FILE: CLAUDE.md ===") < text.index("=== FILE: src/a.py ===")
    for bad in (KEY, "shouldnotappear", "valódi", "szavazat", "gemini_labels", "mentesek/", "results/x.json"):
        assert bad not in text, bad
    assert "FILE_COUNT: 3" in text and "- src/b.py" in text


def test_snapshot_never_reads_itself_or_old_parts(cs):
    root = make_repo(cs)
    out = root / "context_snapshot.txt"
    cs.build_snapshot(out, 40_000)
    first = out.read_text(encoding="utf-8")
    cs.build_snapshot(out, 40_000)
    assert out.read_text(encoding="utf-8") == first                              # a második futás nem olvassa be az elsőt


# ---------------------------------------------------------------- részekre bontás

def test_split_parts_respects_the_limit_and_loses_nothing(cs):
    secs = ["a" * 50, "b" * 30, "c" * 300, "d" * 10]
    parts = cs.split_parts(secs, "M" * 20, 100)
    assert all(len(p) <= 100 for p in parts) and len(parts) >= 4
    assert "".join(parts) == "M" * 20 + "\n" + "\n".join(secs) + "\n"
    assert parts[0].startswith("M" * 20)                                          # az első rész a tartalomjegyzékkel kezdődik


def test_an_exact_fit_stays_in_one_part(cs):
    assert cs.split_parts(["x" * 40, "y" * 40], "m" * 17, 100) == ["m" * 17 + "\n" + "x" * 40 + "\n" + "y" * 40 + "\n"]        # 18 + 41 + 41 = 100


def test_split_parts_starts_new_parts_on_section_boundaries(cs):
    secs = ["x" * 40, "y" * 40, "z" * 40]
    parts = cs.split_parts(secs, "m", 100)
    assert parts == ["m\n" + "x" * 40 + "\n" + "y" * 40 + "\n", "z" * 40 + "\n"]


def test_max_chars_writes_numbered_parts_and_no_single_file(cs):
    root = make_repo(cs)
    for i in range(6):
        put(root, f"src/m{i}.py", f"# modul {i}\n" + "x = 1\n" * 40)
    out = root / "context_snapshot.txt"
    written = cs.build_snapshot(out, 40_000, max_chars=600)
    names = [p.name for p in written]
    assert len(written) >= 2 and names == [f"context_snapshot_part{i}.txt" for i in range(1, len(written) + 1)]
    assert not out.exists()
    texts = [p.read_text(encoding="utf-8") for p in written]
    assert all(len(t) <= 600 for t in texts)
    joined = "".join(texts)
    assert joined.index("=== FILE: CLAUDE.md ===") < joined.index("=== FILE: src/a.py ===") and KEY not in joined
    assert "=== FILE: src/m5.py ===" in joined


def test_rerun_removes_stale_parts_and_the_other_form(cs):
    root = make_repo(cs)
    for i in range(6):
        put(root, f"src/m{i}.py", "x = 1\n" * 60)
    out = root / "context_snapshot.txt"
    cs.build_snapshot(out, 40_000, max_chars=500)
    assert (root / "context_snapshot_part1.txt").exists()
    cs.build_snapshot(out, 40_000, max_chars=0)                                   # egyetlen fájl: a régi részek eltűnnek
    assert out.exists() and not list(root.glob("context_snapshot_part*.txt"))
    cs.build_snapshot(out, 40_000, max_chars=500)                                 # újra részek: az egységes fájl eltűnik
    assert not out.exists() and (root / "context_snapshot_part1.txt").exists()


def test_a_custom_output_name_and_its_parts_are_never_read_back(cs):
    root = make_repo(cs)
    for i in range(5):
        put(root, f"src/m{i}.py", "x = 1\n" * 60)
    out = root / "snap.txt"                                                       # a .txt engedélyezett kiterjesztés: csak az önkizárás védi
    cs.build_snapshot(out, 40_000)
    first = out.read_text(encoding="utf-8")
    cs.build_snapshot(out, 40_000)
    assert out.read_text(encoding="utf-8") == first and "FILE: snap.txt" not in first
    cs.build_snapshot(out, 40_000, max_chars=500)
    cs.build_snapshot(out, 40_000, max_chars=500)
    assert all("FILE: snap" not in p.read_text(encoding="utf-8") for p in root.glob("snap_part*.txt"))


# ---------------------------------------------------------------- a docstring igazsága

def test_every_option_in_the_docstring_exists_in_the_parser(cs, monkeypatch):
    doc = cs.__doc__
    mentioned = set(re.findall(r"--[a-z][a-z-]*", doc))
    monkeypatch.setattr(sys, "argv", ["context_snapshot.py"])
    parser_opts = set()
    import argparse
    orig = argparse.ArgumentParser.add_argument

    def spy(self, *names, **kw):
        parser_opts.update(n for n in names if n.startswith("--"))
        return orig(self, *names, **kw)
    monkeypatch.setattr(argparse.ArgumentParser, "add_argument", spy)
    args = cs.parse_args()
    assert mentioned and mentioned <= parser_opts, mentioned - parser_opts
    assert args.max_chars == 0 and args.max_file_bytes == cs.DEFAULT_MAX_FILE_BYTES
    assert "scripts/context_snapshot.py" in doc
