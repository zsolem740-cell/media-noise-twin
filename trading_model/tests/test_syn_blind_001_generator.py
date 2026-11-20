"""SYN-BLIND-001 generátor tesztjei: kézzel kiszámolt példák, szakaszhatárok, H1 (reprodukálhatóság), H2 (szerializálás), kimeneti útvonal védelme.
Csak szintetikus adat; hálózat és szimulátor nélkül. A kimenetek a pytest ideiglenes (munkafán kívüli) könyvtárába kerülnek."""
import ast
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

from trading_model.scenarios import syn_blind_001 as g

SCEN = Path(g.__file__).resolve().parent
FORBIDDEN_NAMES = {"simulator", "importlib"}


def bars(variant="base"):
    return g.build_bars(variant)


def test_bar_1_hand_example():
    # nyitás 100,00; mozgás 0 + zaj(1) = 0,0008 -> zárás 100,08; kanócok: fel 0,0020, le 0,0030
    b = bars()[0]
    assert (b["open"], b["close"], b["high"], b["low"]) == (Decimal("100.00"), Decimal("100.08"), Decimal("100.29"), Decimal("99.70"))
    assert b["timestamp"] == "2026-01-02T00:00:00Z" and b["available_at"] == b["timestamp"] and b["volume"] == 1000000


def test_noise_and_wick_tables_by_hand():
    assert [g.noise(k) / Decimal("0.0004") for k in range(1, 12)] == [Decimal(x) for x in (2, -2, 5, 1, -3, 4, 0, -4, 3, -1, -5)]
    assert sum(g.noise(k) for k in range(1, 12)) == 0
    assert [g.wick_up(k) / Decimal("0.0005") for k in range(1, 8)] == [Decimal(x) for x in (4, 7, 3, 6, 2, 5, 1)]
    assert [g.wick_down(k) / Decimal("0.0005") for k in range(1, 8)] == [Decimal(x) for x in (6, 4, 2, 7, 5, 3, 1)]


def test_stage_specs_at_the_boundaries():
    base_of = lambda k: g.bar_spec(k, "base")
    assert base_of(20)[0] == 0 and base_of(21)[0] == Decimal("0.0030") and base_of(45)[0] == Decimal("0.0030")
    assert base_of(46)[0] == Decimal("0.0250") and base_of(48)[0] == Decimal("0.0250") and base_of(49)[0] == Decimal("-0.0110") and base_of(55)[0] == Decimal("-0.0110")
    assert [base_of(k)[0] for k in range(56, 61)] == [Decimal(x) for x in ("-0.0100", "-0.0100", "-0.0050", "-0.0050", "-0.0050")]
    assert base_of(61)[0] == Decimal("-0.0040") and base_of(63)[0] == Decimal("0.0080") and base_of(85)[0] == Decimal("-0.0040")
    assert base_of(86)[0] == Decimal("0.0050") and base_of(105)[0] == Decimal("0.0050") and base_of(106)[0] == 0
    # zaj-jelző: az S3 és S4 szakaszban nincs zaj
    assert [base_of(k)[2] for k in (45, 46, 55, 56, 60, 61)] == [1, 0, 0, 0, 0, 1]


def test_gap_only_on_bar_56():
    gaps = {k: g.bar_spec(k, "base")[1] for k in range(1, 121) if g.bar_spec(k, "base")[1] != 0}
    assert gaps == {56: Decimal("-0.1200")}
    rows = bars()
    assert rows[55]["open"] == Decimal("94.60") and rows[54]["close"] == Decimal("107.50")   # 107,50 * 0,88 = 94,60
    for k in range(2, 121):
        if k != 56:
            assert rows[k - 1]["open"] == rows[k - 2]["close"]


def test_ohlc_consistency_and_two_decimals():
    for variant in g.VARIANTS:
        for row in bars(variant):
            assert row["low"] <= min(row["open"], row["close"]) and row["high"] >= max(row["open"], row["close"]) and row["low"] > 0
            for name in ("open", "high", "low", "close"):
                assert row[name] == row[name].quantize(Decimal("0.01"))


def test_alt_shares_first_50_and_differs_after():
    base, alt = bars("base"), bars("alt")
    assert base[:50] == alt[:50] and base[50:] != alt[50:] and len(base) == len(alt) == 120
    assert all(g.bar_spec(k, "alt")[1] == 0 for k in range(1, 121))
    assert g.bar_spec(51, "alt") == (Decimal("0.0040"), Decimal("0"), 1)
    assert g.bar_spec(50, "alt") == g.bar_spec(50, "base")


def test_timestamps_daily_and_available_at():
    rows = bars()
    assert rows[0]["timestamp"] == "2026-01-02T00:00:00Z" and rows[-1]["timestamp"] == "2026-05-01T00:00:00Z"
    assert all(r["available_at"] == r["timestamp"] for r in rows)


def test_capture_marked_synthetic():
    for variant in g.VARIANTS:
        capture = g.build_capture(variant)
        assert capture["synthetic"] is True and capture["symbol"] == "SYN-BLIND-001" and capture["capture_id"].startswith("SYN-BLIND-001")
        assert capture["schema"] == 1 and capture["timeframe"] == "1d" and "NOT MARKET DATA" in capture["_note"]
    with pytest.raises(ValueError):
        g.build_bars("beta")
    with pytest.raises(ValueError):
        g.bar_spec(0, "base")
    with pytest.raises(ValueError):
        g.bar_spec(121, "base")


def test_h1_reproducibility_same_bytes_and_hash():
    for variant in g.VARIANTS:
        same, first, second = g.reproducibility_check(variant)
        assert same and first == second and len(first) == 64
    assert g.reproducibility_check("base")[1] != g.reproducibility_check("alt")[1]


def test_canonical_bytes_are_ascii_sorted_and_compact():
    raw = g.canonical_bytes(g.build_capture("base"))
    raw.decode("ascii")
    assert raw.startswith(b'{"_note":') and b" " not in raw.replace(b"SYNTHETIC PRE-REGISTERED SCENARIO SYN-BLIND-001; NOT MARKET DATA.", b"") and b"\n" not in raw
    assert b'"open":100.00' in raw and b'"synthetic":true' in raw


def test_h2_serialization_roundtrip(tmp_path):
    for variant in g.VARIANTS:
        data_path, sha_path, digest = g.write_outputs(variant, tmp_path)
        assert g.check_serialization(data_path) == []
        assert sha_path.read_text(encoding="ascii") == f"{digest}  {data_path.name}\n"
        assert g.sha256_hex(data_path.read_bytes()) == digest


def test_h2_detects_corruption(tmp_path):
    data_path, _sha, _digest = g.write_outputs("base", tmp_path)
    raw = data_path.read_bytes()
    cases = {
        "szóköz": raw.replace(b'"bars":', b'"bars": ', 1),
        "nem ASCII": raw.replace(b"NOT MARKET", "NÓT MARKET".encode("utf-8"), 1),
        "ismétlődő kulcs": raw.replace(b'"schema":1', b'"schema":1,"schema":1', 1),
        "NaN": raw.replace(b'"open":100.00', b'"open":NaN', 1),
        "csonka": raw[:-5],
    }
    for name, broken in cases.items():
        target = tmp_path / ("x_" + str(abs(hash(name))) + ".json")
        target.write_bytes(broken)
        assert g.check_serialization(target) != [], name


def test_out_dir_inside_worktree_is_refused(tmp_path):
    root = g.REPO_ROOT
    for inside in (root, root / "trading_model", root / "nincs_ilyen_mappa"):
        with pytest.raises(g.OutputPathError):
            g.resolve_out_dir(inside)
        with pytest.raises(g.OutputPathError):
            g.write_outputs("base", inside)
    assert not (root / "nincs_ilyen_mappa").exists()


def test_symlink_into_worktree_is_refused(tmp_path):
    link = tmp_path / "link"
    os.symlink(g.REPO_ROOT / "trading_model", link)
    with pytest.raises(g.OutputPathError):
        g.resolve_out_dir(link)
    with pytest.raises(g.OutputPathError):
        g.write_outputs("base", link / "valami")
    assert not (g.REPO_ROOT / "trading_model" / "valami").exists()


def test_symlink_outside_worktree_is_allowed(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    os.symlink(real, link)
    data_path, _sha, _digest = g.write_outputs("base", link)
    assert data_path.parent == real.resolve() and data_path.exists()


def test_existing_output_is_never_overwritten(tmp_path):
    data_path, sha_path, _digest = g.write_outputs("base", tmp_path)
    before = (data_path.read_bytes(), sha_path.read_bytes())
    with pytest.raises(g.OutputPathError):
        g.write_outputs("base", tmp_path)
    assert (data_path.read_bytes(), sha_path.read_bytes()) == before
    g.write_outputs("alt", tmp_path)          # a másik változat más fájlnév: nem ütközik


def test_dangling_symlink_target_is_not_followed(tmp_path):
    outside = tmp_path / "ide_nem_irhat"
    os.symlink(outside, tmp_path / g.FILE_NAMES["base"])
    with pytest.raises(g.OutputPathError):
        g.write_outputs("base", tmp_path)
    assert not outside.exists()


def test_cli_refuses_worktree_and_requires_an_action(tmp_path, capsys):
    assert g.main(["--variant", "base", "--out", str(g.REPO_ROOT / "trading_model" / "kimenet")]) == 2
    assert not (g.REPO_ROOT / "trading_model" / "kimenet").exists()
    with pytest.raises(SystemExit):
        g.main(["--variant", "base"])
    assert g.main(["--variant", "alt", "--hash-check"]) == 0
    assert g.main(["--variant", "base", "--out", str(tmp_path)]) == 0
    assert g.main(["--variant", "base", "--check-file", str(tmp_path / g.FILE_NAMES["base"])]) == 0
    out = capsys.readouterr().out
    assert "H1" in out and "H2" in out and "RENDBEN" in out


def test_generator_data_loads_under_the_data_contract(tmp_path):
    from trading_model import data
    for variant in g.VARIANTS:
        data_path, _sha, _digest = g.write_outputs(variant, tmp_path)
        series, problems = data.load_series(data_path)
        assert series is not None and not data.has_blocking(problems) and series.synthetic and len(series.bars) == 120


PACKAGE_PY_FILES = ("scenarios/__init__.py", "scenarios/syn_blind_001.py", "scenarios/syn_blind_001_check.py",
                    "tests/test_syn_blind_001_generator.py", "tests/test_syn_blind_001_check.py")


def test_new_modules_and_tests_do_not_import_the_simulator_or_import_dynamically():
    """A csomag PONTOS, név szerinti Python-fájllistáján fut (a csomagon kívüli fájlokra nem támaszkodik, és nem is számolja őket)."""
    base = SCEN.parent
    files = [base / name for name in PACKAGE_PY_FILES]
    assert all(path.is_file() for path in files)
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "")] + [a.name for a in node.names]
            else:
                if isinstance(node, ast.Name) and node.id in ("__import__", "eval", "exec"):
                    raise AssertionError(f"{path.name}: tiltott név {node.id}")
                continue
            for name in names:
                assert not any(part in FORBIDDEN_NAMES for part in name.split(".")), f"{path.name}: tiltott import {name}"


def leaked_stage_labels(capture):
    """A kimeneti adatba (kulcsba vagy értékbe) került szakaszcímkék listája."""
    raw = g.canonical_bytes(capture).decode("ascii")
    return [label for label, _first, _last in g.STAGES if label in raw]


def test_stage_labels_are_not_in_the_market_data_fields():
    for variant in g.VARIANTS:
        capture = g.build_capture(variant)
        assert set(capture) == {"_note", "bars", "capture_id", "schema", "symbol", "synthetic", "timeframe"}
        assert all(set(b) == {"timestamp", "open", "high", "low", "close", "volume", "available_at"} for b in capture["bars"])
        assert leaked_stage_labels(capture) == []


def test_stage_label_leak_detector_really_fails_on_an_injected_label():
    """Szándékosan beszúrt szakaszcímkével a vizsgálat elbukik (a detektor nem üres állítás)."""
    label = g.STAGES[2][0]
    for place in ("mező", "érték"):
        capture = g.build_capture("base")
        if place == "mező":
            capture["bars"][3]["stage"] = "x"
            capture["bars"][3][label] = 1
        else:
            capture["capture_id"] = capture["capture_id"] + "-" + label
        assert leaked_stage_labels(capture) == [label]
    capture = g.build_capture("alt")
    capture["bars"][0]["stage"] = g.STAGES[0][0]
    assert leaked_stage_labels(capture) == [g.STAGES[0][0]]
    assert set(capture["bars"][0]) != {"timestamp", "open", "high", "low", "close", "volume", "available_at"}


@pytest.mark.parametrize("module_file", ["syn_blind_001.py", "syn_blind_001_check.py"])
def test_module_import_has_no_side_effects_structurally(module_file):
    tree = ast.parse((SCEN / module_file).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Expr):
            assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)      # csak a modul-docstring
        elif isinstance(node, ast.If):
            assert ast.unparse(node.test) == "__name__ == '__main__'"
        else:
            assert isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef, ast.Assign)), type(node).__name__


# ===== Kiírási protokoll (B változat): nincs visszagörgetés, nyitott tmp-fájlleírók, sidecar-első közzététel =====
# Elsődleges bizonyíték: futásidejű hibainjektálás (os.link / os.unlink / kivételek). A szerkezeti (AST) őr csak kiegészítő.
EVIL = b"IDEGEN TARTALOM"


def sidecar_name(variant="base"):
    return g.FILE_NAMES[variant] + ".sha256"


def expected_sidecar_text(variant="base"):
    return f"{g.sha256_hex(g.canonical_bytes(g.build_capture(variant)))}  {g.FILE_NAMES[variant]}\n".encode("ascii")


def names(directory):
    return sorted(p.name for p in directory.iterdir())


def record_unlinks(monkeypatch, deny=False):
    """Minden os.unlink hívás útvonalát rögzíti (opcionálisan minden törlést megtagad)."""
    real, calls = os.unlink, []

    def spy(path, *args, **kwargs):
        calls.append(Path(path))
        if deny:
            raise PermissionError("szándékos törlési hiba")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", spy)
    return calls


def link_hook(monkeypatch, hook):
    """os.link csere: hook(sorszám, src, dst, real_link) -> (visszatérési érték vagy kivétel dobása)."""
    real, count = os.link, []

    def wrapper(src, dst, *args, **kwargs):
        count.append((Path(src), Path(dst)))
        return hook(len(count), Path(src), Path(dst), lambda: real(src, dst, *args, **kwargs))

    monkeypatch.setattr(os, "link", wrapper)
    return count


def test_failed_verification_leaves_no_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "serialization_problems", lambda raw: ["szándékos hiba"])
    with pytest.raises(g.GenerationError) as info:
        g.write_outputs("base", tmp_path)
    assert list(tmp_path.iterdir()) == [] and not (info.value.published or info.value.foreign or info.value.leftovers)


def test_cli_reports_failure_and_creates_nothing_on_generation_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(g, "serialization_problems", lambda raw: ["szándékos hiba"])
    assert g.main(["--variant", "base", "--out", str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert "Ez a hívás nem hagyott maga után fájlt" in captured.err and captured.out == "" and list(tmp_path.iterdir()) == []


def test_non_oserror_exception_during_write_is_wrapped_and_cleaned(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "serialization_problems", lambda raw: (_ for _ in ()).throw(RuntimeError("szándékos")))
    with pytest.raises(g.GenerationError) as info:
        g.write_outputs("base", tmp_path)
    assert isinstance(info.value.__cause__, RuntimeError) and list(tmp_path.iterdir()) == []


def test_publication_order_is_sidecar_first_data_last(tmp_path, monkeypatch):
    seen = link_hook(monkeypatch, lambda n, src, dst, real: real())
    g.write_outputs("base", tmp_path)
    assert [dst.name for _src, dst in seen] == [sidecar_name(), g.FILE_NAMES["base"]]


def test_complete_success_leaves_exactly_the_final_pair_and_no_tmp(tmp_path):
    written = g.write_outputs("base", tmp_path)
    assert written.leftovers == [] and names(tmp_path) == sorted([g.FILE_NAMES["base"], sidecar_name()])
    assert (tmp_path / sidecar_name()).read_bytes() == expected_sidecar_text()


def test_regression_d1_foreign_tmp_file_with_the_old_pid_name_is_not_deleted(tmp_path):
    name, pid = g.FILE_NAMES["base"], os.getpid()
    foreign = [tmp_path / f".{name}.tmp{pid}", tmp_path / f".{name}.sha256.tmp{pid}"]
    for path in foreign:
        path.write_bytes(EVIL)
    g.write_outputs("base", tmp_path)
    assert [p.read_bytes() for p in foreign] == [EVIL, EVIL]


def test_regression_d1_foreign_tmp_file_survives_a_failed_write_too(tmp_path, monkeypatch):
    foreign = tmp_path / f".{g.FILE_NAMES['base']}.tmp{os.getpid()}"
    foreign.write_bytes(EVIL)
    monkeypatch.setattr(g, "serialization_problems", lambda raw: ["szándékos hiba"])
    with pytest.raises(g.GenerationError):
        g.write_outputs("base", tmp_path)
    assert foreign.read_bytes() == EVIL


def test_unique_tmp_name_collision_is_retried_and_the_foreign_file_untouched(tmp_path, monkeypatch):
    name = g.FILE_NAMES["base"]
    tokens = iter(["aaaa", "aaaa", "bbbb", "cccc", "dddd", "eeee"])
    monkeypatch.setattr(g, "_tmp_token", lambda: next(tokens))
    foreign = tmp_path / f".{name}.aaaa.tmp"
    foreign.write_bytes(EVIL)
    g.write_outputs("base", tmp_path)
    assert foreign.read_bytes() == EVIL and (tmp_path / name).exists()


# --- Nincs visszagörgetés: a közzétett végleges fájl megmarad, a kimenet hiányos és jelentve van ---

def test_failed_second_publication_keeps_the_published_sidecar_and_reports_it(tmp_path, monkeypatch):
    unlinks = record_unlinks(monkeypatch)

    def hook(n, src, dst, real):
        if n == 2:
            raise OSError("szándékos link-hiba")
        return real()

    link_hook(monkeypatch, hook)
    with pytest.raises(g.GenerationError) as info:
        g.write_outputs("base", tmp_path)
    sidecar, data = tmp_path / sidecar_name(), tmp_path / g.FILE_NAMES["base"]
    assert "hard-link" in str(info.value)
    assert sidecar.read_bytes() == expected_sidecar_text() and not data.exists()          # NINCS visszagörgetés
    assert [p for p, _why in info.value.published] == [str(sidecar)] and not info.value.foreign and not info.value.leftovers
    assert sidecar not in unlinks and data not in unlinks                              # végleges névre nem hívódott unlink
    assert all(p.name.startswith(".") and p.name.endswith(".tmp") for p in unlinks)    # csak ideiglenes nevekre
    assert names(tmp_path) == [sidecar_name()]                                          # az ideiglenes nevek takarítva


def test_cli_exit_3_reports_incomplete_publication_never_success(tmp_path, monkeypatch, capsys):
    link_hook(monkeypatch, lambda n, src, dst, real: (_ for _ in ()).throw(OSError("szándékos")) if n == 2 else real())
    assert g.main(["--variant", "base", "--out", str(tmp_path / "out")]) == 3
    captured = capsys.readouterr()
    sidecar = tmp_path / "out" / sidecar_name()
    assert captured.out == "" and sidecar.exists()                                      # nincs "siker" kimenet (hash-sor)
    assert str(sidecar) in captured.err and "NEM visszagörgetett" in captured.err and "NEM sikeres, NEM befagyasztott" in captured.err and "hiányos" in captured.err


def test_second_final_name_created_meanwhile_is_preserved_and_the_first_is_kept(tmp_path, monkeypatch, capsys):
    victim = tmp_path / g.FILE_NAMES["base"]

    def hook(n, src, dst, real):
        if n == 2:
            victim.write_bytes(EVIL)                       # a második végleges név közben idegenként létrejön
        return real()

    link_hook(monkeypatch, hook)
    with pytest.raises(g.OutputPathError) as info:
        g.write_outputs("base", tmp_path)
    assert victim.read_bytes() == EVIL and (tmp_path / sidecar_name()).read_bytes() == expected_sidecar_text()
    assert [p for p, _w in info.value.preexisting] == [str(victim)] and [p for p, _w in info.value.published] == [str(tmp_path / sidecar_name())]
    assert names(tmp_path) == sorted([victim.name, sidecar_name()])


def test_cli_exit_3_when_the_data_name_appears_meanwhile(tmp_path, monkeypatch, capsys):
    victim = tmp_path / "out" / g.FILE_NAMES["base"]

    def hook(n, src, dst, real):
        if n == 2:
            victim.write_bytes(EVIL)
        return real()

    (tmp_path / "out").mkdir()
    link_hook(monkeypatch, hook)
    assert g.main(["--variant", "base", "--out", str(tmp_path / "out")]) == 3
    err = capsys.readouterr().err
    assert victim.read_bytes() == EVIL and str(tmp_path / "out" / sidecar_name()) in err and str(victim) in err and "már létező, érintetlenül hagyott fájl" in err


def test_first_final_name_created_meanwhile_publishes_nothing_and_exits_2(tmp_path, monkeypatch, capsys):
    victim = tmp_path / sidecar_name()

    def hook(n, src, dst, real):
        if n == 1:
            victim.write_bytes(EVIL)
        return real()

    link_hook(monkeypatch, hook)
    assert g.main(["--variant", "base", "--out", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert victim.read_bytes() == EVIL and names(tmp_path) == [sidecar_name()]          # semmi nem közzétett, nincs maradék
    assert "már létező, érintetlenül hagyott fájl" in err and str(victim) in err and "nem hagyott maga után fájlt" in err


def test_preexisting_conflicts_are_untouched_and_reported_with_exit_2(tmp_path, capsys):
    (tmp_path / g.FILE_NAMES["base"]).write_bytes(EVIL)
    (tmp_path / sidecar_name()).write_bytes(EVIL)
    with pytest.raises(g.OutputPathError) as info:
        g.write_outputs("base", tmp_path)
    assert len(info.value.preexisting) == 2 and not (info.value.published or info.value.foreign or info.value.leftovers)
    assert g.main(["--variant", "base", "--out", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert err.count("már létező, érintetlenül hagyott fájl") == 2 and [p.read_bytes() for p in tmp_path.iterdir()] == [EVIL, EVIL]


# --- Idegen csere: a tartalom megmarad, a hiba jelentett, soha nem sikeres ---

def test_foreign_replacement_of_a_published_final_is_preserved_and_reported(tmp_path, monkeypatch, capsys):
    unlinks = record_unlinks(monkeypatch)
    sidecar = tmp_path / sidecar_name()
    state = {}

    def hook(n, src, dst, real):
        if n == 2:
            state["old_ino"] = os.stat(sidecar).st_ino
            os.replace(sidecar, tmp_path / "elmozgatott")              # a közzétett végleges fájlt idegen fájl váltja fel
            sidecar.write_bytes(EVIL)
            state["new_ino"] = os.stat(sidecar).st_ino
            raise OSError("szándékos link-hiba")
        return real()

    link_hook(monkeypatch, hook)
    with pytest.raises(g.GenerationError) as info:
        g.write_outputs("base", tmp_path)
    assert sidecar.read_bytes() == EVIL                                               # az idegen tartalom megmaradt
    assert state["new_ino"] != state["old_ino"]                                       # a nyitva tartott fájlleíró miatt az inode nem használható újra
    assert [p for p, _w in info.value.foreign] == [str(sidecar)] and not info.value.published
    assert sidecar not in unlinks
    assert (tmp_path / "elmozgatott").read_bytes() == expected_sidecar_text()


@pytest.mark.parametrize("which", ["sidecar", "data"])
def test_foreign_replacement_of_a_tmp_file_before_publication_is_preserved_detected_and_reported(tmp_path, monkeypatch, which, capsys):
    unlinks = record_unlinks(monkeypatch)
    target_index = 1 if which == "sidecar" else 2
    state = {}

    def hook(n, src, dst, real):
        if n == target_index:
            state["old_ino"] = os.stat(src).st_ino
            os.replace(src, src.with_name("elmozgatott_" + which))            # az ideiglenes fájlt idegen váltja fel a link előtt
            src.write_bytes(EVIL)
            state["new_ino"] = os.stat(src).st_ino
            state["src"], state["dst"] = src, dst
        return real()

    link_hook(monkeypatch, hook)
    with pytest.raises(g.GenerationError) as info:
        g.write_outputs("base", tmp_path)
    assert state["new_ino"] != state["old_ino"]                                       # nyitott leíró: nincs inode-újrahasznosítás
    assert state["src"].read_bytes() == EVIL and state["dst"].read_bytes() == EVIL     # idegen tartalom a tmp és a végleges néven is megmaradt
    assert state["src"] not in unlinks and state["dst"] not in unlinks
    reported = {p for p, _w in info.value.foreign}
    assert str(state["src"]) in reported and str(state["dst"]) in reported
    assert str(state["dst"]) not in {p for p, _w in info.value.published}
    if which == "sidecar":                                                             # az idegen észlelése után nem közzétesszük tovább az adatfájlt
        assert not (tmp_path / g.FILE_NAMES["base"]).exists()


def test_cli_never_reports_success_after_a_foreign_replacement(tmp_path, monkeypatch, capsys):
    def hook(n, src, dst, real):
        if n == 1:
            os.replace(src, src.with_name("elmozgatott"))
            src.write_bytes(EVIL)
        return real()

    link_hook(monkeypatch, hook)
    assert g.main(["--variant", "base", "--out", str(tmp_path / "out")]) == 3
    captured = capsys.readouterr()
    assert captured.out == "" and "idegen" in captured.err and "NEM befagyasztott" in captured.err
    assert (tmp_path / "out" / sidecar_name()).read_bytes() == EVIL


def test_tmp_replaced_after_publication_is_not_deleted_and_exit_is_4(tmp_path, monkeypatch, capsys):
    unlinks = record_unlinks(monkeypatch)
    state = {}

    def hook(n, src, dst, real):
        result = real()
        if n == 2:                                                                     # az utolsó közzététel UTÁN cserélik le az ideiglenes nevet
            os.replace(src, src.with_name("elmozgatott"))
            src.write_bytes(EVIL)
            state["src"] = src
        return result

    link_hook(monkeypatch, hook)
    out = tmp_path / "out"
    assert g.main(["--variant", "base", "--out", str(out)]) == 4
    captured = capsys.readouterr()
    assert state["src"].read_bytes() == EVIL and state["src"] not in unlinks
    assert captured.out == "" and "NEM jogosult rekord-jóváhagyásra" in captured.err and str(state["src"]) in captured.err
    assert (out / sidecar_name()).read_bytes() == expected_sidecar_text()              # a végleges pár teljes


# --- A takarítás hibái ---

def test_regression_d3_cleanup_failure_does_not_mask_the_original_error(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "serialization_problems", lambda raw: ["szándékos hiba"])
    record_unlinks(monkeypatch, deny=True)
    with pytest.raises(g.GenerationError) as info:
        g.write_outputs("base", tmp_path)
    assert "szándékos hiba" in str(info.value) and info.value.leftovers and all(Path(p).exists() for p, _why in info.value.leftovers)
    assert all("nem törölhető" in why for _p, why in info.value.leftovers)


def test_regression_d3_leftover_tmp_after_a_successful_write_is_reported_not_raised(tmp_path, monkeypatch):
    real_unlink = os.unlink

    def deny_tmp(path, *args, **kwargs):
        if ".tmp" in Path(path).name:
            raise PermissionError("szándékos törlési hiba")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", deny_tmp)
    written = g.write_outputs("base", tmp_path)
    data_path, sha_path, _digest = written
    assert data_path.exists() and sha_path.exists() and len(written.leftovers) == 2 and all(Path(p).name.startswith(".") for p, _why in written.leftovers)


def test_cleanup_failure_after_partial_publication_neither_masks_nor_touches_the_finals(tmp_path, monkeypatch):
    unlinks = record_unlinks(monkeypatch, deny=True)
    link_hook(monkeypatch, lambda n, src, dst, real: (_ for _ in ()).throw(OSError("szándékos")) if n == 2 else real())
    with pytest.raises(g.GenerationError) as info:
        g.write_outputs("base", tmp_path)
    assert "hard-link" in str(info.value) and (tmp_path / sidecar_name()).read_bytes() == expected_sidecar_text()
    assert [p for p, _w in info.value.published] == [str(tmp_path / sidecar_name())] and len(info.value.leftovers) == 2
    assert all(p.name.startswith(".") and p.name.endswith(".tmp") for p in unlinks)


def test_cli_exit_codes_distinguish_success_failure_leftovers_and_residue(tmp_path, monkeypatch, capsys):
    out_ok, out_fail, out_left, out_tmp = (tmp_path / n for n in ("ok", "fail", "left", "tmp"))
    assert g.main(["--variant", "base", "--out", str(out_ok)]) == 0
    assert capsys.readouterr().out.strip().split()[0] == g.reproducibility_check("base")[1]
    monkeypatch.setattr(g, "serialization_problems", lambda raw: ["szándékos hiba"])
    assert g.main(["--variant", "base", "--out", str(out_fail)]) == 2                      # 2: nincs tulajdonítható kimenet
    assert "Ez a hívás nem hagyott maga után fájlt" in capsys.readouterr().err and list(out_fail.iterdir()) == []
    record_unlinks(monkeypatch, deny=True)
    assert g.main(["--variant", "base", "--out", str(out_left)]) == 3                      # 3: maradék ideiglenes fájl (sikertelen kiírás)
    err = capsys.readouterr().err
    assert "megmaradt ideiglenes" in err and ".tmp" in err and "nem törölhető" in err
    monkeypatch.undo()
    real_unlink = os.unlink
    monkeypatch.setattr(os, "unlink", lambda path, *a, **k: (_ for _ in ()).throw(PermissionError("szándékos")) if ".tmp" in Path(path).name else real_unlink(path, *a, **k))
    assert g.main(["--variant", "base", "--out", str(out_tmp)]) == 4                       # 4: teljes végleges pár, ideiglenes maradék
    captured = capsys.readouterr()
    digest = g.reproducibility_check("base")[1]
    assert captured.out == "" and digest in captured.err and "ideiglenes maradék" in captured.err and "NEM jogosult rekord-jóváhagyásra" in captured.err    # a hash-sor csak a 0-s kódnál kerül stdoutra
    assert (out_tmp / g.FILE_NAMES["base"]).exists()


# --- Megszakítás ---

@pytest.mark.parametrize("exc_type", [KeyboardInterrupt, SystemExit])
def test_interruption_before_publication_propagates_after_cleanup(tmp_path, monkeypatch, exc_type):
    monkeypatch.setattr(g, "serialization_problems", lambda raw: (_ for _ in ()).throw(exc_type()))
    with pytest.raises(exc_type):
        g.write_outputs("base", tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("exc_type", [KeyboardInterrupt, SystemExit])
def test_interruption_after_publication_propagates_and_reports_the_published_output(tmp_path, monkeypatch, exc_type):
    unlinks = record_unlinks(monkeypatch)
    link_hook(monkeypatch, lambda n, src, dst, real: (_ for _ in ()).throw(exc_type()) if n == 2 else real())
    with pytest.raises(exc_type) as info:
        g.write_outputs("base", tmp_path)
    sidecar = tmp_path / sidecar_name()
    assert sidecar.read_bytes() == expected_sidecar_text() and sidecar not in unlinks and names(tmp_path) == [sidecar_name()]
    assert str(sidecar) in " ".join(getattr(info.value, "__notes__", [])) and "hiányos, nem befagyasztott" in " ".join(info.value.__notes__)


def test_interruption_right_after_the_link_returns_still_reports_the_published_file(tmp_path, monkeypatch):
    def hook(n, src, dst, real):
        result = real()
        if n == 1:
            raise KeyboardInterrupt()                                        # a link megtörtént, de a hívó könyvelése még nem
        return result

    link_hook(monkeypatch, hook)
    with pytest.raises(KeyboardInterrupt) as info:
        g.write_outputs("base", tmp_path)
    sidecar = tmp_path / sidecar_name()
    assert sidecar.read_bytes() == expected_sidecar_text() and str(sidecar) in " ".join(info.value.__notes__)


@pytest.mark.parametrize("exc_type", [KeyboardInterrupt, SystemExit])
def test_cli_prints_the_published_output_note_and_propagates_the_interruption(tmp_path, monkeypatch, capsys, exc_type):
    link_hook(monkeypatch, lambda n, src, dst, real: (_ for _ in ()).throw(exc_type()) if n == 2 else real())
    with pytest.raises(exc_type):
        g.main(["--variant", "base", "--out", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert str(tmp_path / "out" / sidecar_name()) in err and "hiányos, nem befagyasztott" in err and "FIGYELEM" in err


# --- Fájlleírók ---

@pytest.mark.parametrize("scenario", ["success", "verification_failure", "link_failure", "interruption", "cleanup_denied"])
def test_tmp_file_descriptors_are_closed_on_every_exit(tmp_path, monkeypatch, scenario):
    real_open, fds = os.open, []

    def spy(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        if ".tmp" in Path(path).name:
            fds.append(fd)
        return fd

    monkeypatch.setattr(os, "open", spy)
    if scenario == "verification_failure":
        monkeypatch.setattr(g, "serialization_problems", lambda raw: ["szándékos hiba"])
    elif scenario == "link_failure":
        link_hook(monkeypatch, lambda n, src, dst, real: (_ for _ in ()).throw(OSError("szándékos")) if n == 2 else real())
    elif scenario == "interruption":
        link_hook(monkeypatch, lambda n, src, dst, real: (_ for _ in ()).throw(KeyboardInterrupt()) if n == 1 else real())
    elif scenario == "cleanup_denied":
        record_unlinks(monkeypatch, deny=True)
    try:
        g.write_outputs("base", tmp_path)
    except (g.OutputError, KeyboardInterrupt):
        pass
    assert len(fds) == 2
    for fd in fds:
        with pytest.raises(OSError):
            os.fstat(fd)                                                      # a leíró le van zárva


def test_the_held_descriptor_pins_the_inode_so_a_replacement_cannot_share_it(tmp_path, monkeypatch):
    """Determinisztikus tulajdonság (nem valószínűségi): amíg a hívás tartja a leírót, az unlink + újraírás új inode-ot ad."""
    state = {}

    def hook(n, src, dst, real):
        if n == 1:
            state["old"] = os.stat(src).st_ino
            os.unlink(src)
            src.write_bytes(EVIL)
            state["new"] = os.stat(src).st_ino
        return real()

    link_hook(monkeypatch, hook)
    with pytest.raises(g.GenerationError):
        g.write_outputs("base", tmp_path)
    assert state["new"] != state["old"] and state["new"] is not None


# --- A mkdir hibája ---

def test_mkdir_failure_is_reported_and_leaves_no_file(tmp_path, capsys):
    blocker = tmp_path / "fajl"
    blocker.write_bytes(b"x")
    for target in (blocker / "alatta", blocker):
        with pytest.raises(OSError):
            g.write_outputs("base", target)
        assert g.main(["--variant", "base", "--out", str(target)]) == 2
        assert "Ez a hívás nem hagyott maga után fájlt" in capsys.readouterr().err
    assert [p.name for p in tmp_path.iterdir()] == ["fajl"] and blocker.read_bytes() == b"x"


# --- Kiegészítő szerkezeti őr (az elsődleges bizonyíték a fenti futásidejű injektálás) ---

def test_only_the_tmp_cleanup_helper_may_remove_rename_or_truncate_files():
    tree = ast.parse((SCEN / "syn_blind_001.py").read_text(encoding="utf-8"))
    banned = {"unlink", "remove", "rename", "replace", "rmdir", "truncate", "ftruncate", "rmtree"}
    offenders = []
    for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for node in ast.walk(func):
            if isinstance(node, ast.Call):
                called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
                if called in banned and func.name != "_remove_tmp":
                    offenders.append((func.name, called))
    assert offenders == []


def test_explicit_cent_rounding_half_even_hand_cases():
    import decimal
    even, up = decimal.ROUND_HALF_EVEN, decimal.ROUND_HALF_UP
    cases = [("0.125", "0.12", "0.13"), ("0.135", "0.14", "0.14"), ("0.025", "0.02", "0.03"), ("100.005", "100.00", "100.01"), ("100.015", "100.02", "100.02"), ("2.675", "2.68", "2.68"), ("0.345", "0.34", "0.35")]
    for text, want_even, want_up in cases:
        assert g._round(Decimal(text), even) == Decimal(want_even), text
        assert g._round(Decimal(text), up) == Decimal(want_up), text
    assert sum(g._round(Decimal(t), even) != g._round(Decimal(t), up) for t, _e, _u in cases) >= 4     # az esetek tényleg megkülönböztetik a két módot
    assert g._round(Decimal("100.001"), decimal.ROUND_CEILING) == Decimal("100.01") and g._round(Decimal("100.009"), decimal.ROUND_FLOOR) == Decimal("100.00")

def test_story_uses_half_even_for_open_and_close_and_directed_modes_for_wicks(monkeypatch):
    import decimal
    seen = []
    real = g._round
    monkeypatch.setattr(g, "_round", lambda value, mode: (seen.append(mode), real(value, mode))[1])
    g.build_bars("base")
    assert len(seen) == 120 * 3 + 1                                   # 1 nyitási rés + sávonként close, high, low
    assert seen[0] == decimal.ROUND_HALF_EVEN                          # (1. sáv: zárás)
    assert set(seen) == {decimal.ROUND_HALF_EVEN, decimal.ROUND_CEILING, decimal.ROUND_FLOOR}
    assert seen.count(decimal.ROUND_HALF_EVEN) == 121 and seen.count(decimal.ROUND_CEILING) == 120 and seen.count(decimal.ROUND_FLOOR) == 120


# --- A második független felülvizsgálat (közzététel és takarítás) utáni pótlások ---

@pytest.mark.parametrize("how", ["replace", "delete"])
def test_sidecar_changed_after_the_data_link_is_caught_before_exit_0(tmp_path, monkeypatch, capsys, how):
    out = tmp_path / "out"
    sidecar = out / sidecar_name()

    def hook(n, src, dst, real):
        result = real()
        if n == 2:                                                                 # az adatfájl közzététele UTÁN változik meg a sidecar
            os.replace(sidecar, tmp_path / "elmozgatott")
            if how == "replace":
                sidecar.write_bytes(EVIL)
        return result

    link_hook(monkeypatch, hook)
    assert g.main(["--variant", "base", "--out", str(out)]) == 3
    captured = capsys.readouterr()
    assert captured.out == "" and str(sidecar) in captured.err and "NEM befagyasztott" in captured.err
    assert (sidecar.read_bytes() == EVIL) if how == "replace" else (not sidecar.exists())
    assert (out / g.FILE_NAMES["base"]).exists()


def test_a_published_name_that_vanishes_after_the_link_is_uncertain_exit_3(tmp_path, monkeypatch, capsys):
    real_unlink = os.unlink

    def hook(n, src, dst, real):
        result = real()
        if n == 1:
            real_unlink(dst)                                                       # a közzétett név a link után eltűnik
        return result

    link_hook(monkeypatch, hook)
    assert g.main(["--variant", "base", "--out", str(tmp_path / "out")]) == 3
    err = capsys.readouterr().err
    assert "eltűnt" in err and "bizonytalan" in err and "Ez a hívás nem hagyott maga után fájlt" not in err


@pytest.mark.parametrize("exc_type", [KeyboardInterrupt, SystemExit])
def test_interruption_during_the_success_cleanup_is_reported_not_silent(tmp_path, monkeypatch, exc_type):
    real_unlink, calls = os.unlink, []

    def interrupting(path, *args, **kwargs):
        calls.append(Path(path))
        if len(calls) == 1:
            raise exc_type()
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", interrupting)
    with pytest.raises(exc_type) as info:
        g.write_outputs("base", tmp_path)
    notes = " ".join(getattr(info.value, "__notes__", []))
    assert str(tmp_path / sidecar_name()) in notes and str(tmp_path / g.FILE_NAMES["base"]) in notes
    assert names(tmp_path) == sorted([g.FILE_NAMES["base"], sidecar_name()])            # a legjobb erőfeszítésű takarítás befejeződött, a pár teljes


def test_tmp_content_changed_before_verification_is_rejected_and_nothing_is_published(tmp_path, monkeypatch):
    def tamper(raw):
        victim = next(p for p in tmp_path.glob(".*.sha256.*.tmp"))
        victim.write_bytes(b"ROSSZ SIDECAR")                                           # ugyanaz az inode, más tartalom
        return []

    monkeypatch.setattr(g, "serialization_problems", tamper)
    with pytest.raises(g.GenerationError) as info:
        g.write_outputs("base", tmp_path)
    assert "ellenőrzése sikertelen" in str(info.value) and list(tmp_path.iterdir()) == [] and not info.value.published


def test_tmp_content_changed_through_the_tmp_name_before_the_link_is_caught_after_it(tmp_path, monkeypatch, capsys):
    def hook(n, src, dst, real):
        if n == 1:
            with open(src, "r+b") as handle:                                           # ugyanaz az inode: a végleges név is megváltozik
                handle.write(b"X")
        return real()

    link_hook(monkeypatch, hook)
    assert g.main(["--variant", "base", "--out", str(tmp_path / "out")]) == 3
    captured = capsys.readouterr()                                       # egyetlen kiolvasás: a stdout-ot és a stderr-t is ugyanabból a rögzítésből nézzük
    assert "tartalma a link után eltér" in captured.err and captured.out == ""


def _fstat_denied_for_tmp_fds(monkeypatch):
    real_open, real_fstat, tmp_fds, armed = os.open, os.fstat, set(), {"on": False}

    def spy_open(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        if ".tmp" in Path(path).name:
            tmp_fds.add(fd)
        return fd

    def fstat(fd):
        if armed["on"] and fd in tmp_fds:
            raise OSError(5, "szándékos fstat-hiba")
        return real_fstat(fd)

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "fstat", fstat)
    return armed


def test_unknown_tmp_state_is_never_deleted_and_is_reported(tmp_path, monkeypatch, capsys):
    armed = _fstat_denied_for_tmp_fds(monkeypatch)
    unlinks = record_unlinks(monkeypatch)

    def failing(raw):
        armed["on"] = True
        return ["szándékos hiba"]

    monkeypatch.setattr(g, "serialization_problems", failing)
    assert g.main(["--variant", "base", "--out", str(tmp_path / "out")]) == 3
    err = capsys.readouterr().err
    left = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert len(left) == 2 and all(n.endswith(".tmp") for n in left) and unlinks == []     # nem töröltük őket
    assert "az állapot nem állapítható meg" in err


def test_unknown_state_of_a_published_final_is_reported_as_uncertain(tmp_path, monkeypatch):
    armed = _fstat_denied_for_tmp_fds(monkeypatch)
    unlinks = record_unlinks(monkeypatch)

    def hook(n, src, dst, real):
        if n == 2:
            armed["on"] = True
            raise OSError("szándékos link-hiba")
        return real()

    link_hook(monkeypatch, hook)
    with pytest.raises(g.GenerationError) as info:
        g.write_outputs("base", tmp_path)
    assert any(p == str(tmp_path / sidecar_name()) and "bizonytalan" in why for p, why in info.value.foreign)
    assert (tmp_path / sidecar_name()).exists() and unlinks == []


def test_write_failure_after_creation_cleans_the_tmp_and_closes_the_descriptors(tmp_path, monkeypatch):
    real_open, real_write, fds, calls = os.open, os.write, [], []

    def spy_open(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        if ".tmp" in Path(path).name:
            fds.append(fd)
        return fd

    def failing_write(fd, data):
        calls.append(fd)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "write", failing_write)
    with pytest.raises(g.GenerationError) as info:
        g.write_outputs("base", tmp_path)
    assert isinstance(info.value.__cause__, OSError) and list(tmp_path.iterdir()) == [] and len(fds) == 1 == len(calls)
    with pytest.raises(OSError):
        os.fstat(fds[0])


def test_a_symlink_at_the_tmp_path_is_foreign_preserved_and_reported(tmp_path, monkeypatch):
    moved = tmp_path / "elmozgatott"

    def swap(raw):
        victim = next(p for p in tmp_path.glob(".*.tmp") if ".sha256." not in p.name)
        os.replace(victim, moved)
        os.symlink(moved, victim)                                                      # symlink a mozgatott saját inode-ra
        swap.victim = victim
        return ["szándékos hiba"]

    monkeypatch.setattr(g, "serialization_problems", swap)
    with pytest.raises(g.GenerationError) as info:
        g.write_outputs("base", tmp_path)
    assert os.path.islink(swap.victim) and moved.exists()                              # a symlink megmaradt, nem töröltük
    assert str(swap.victim) in {p for p, _w in info.value.foreign}


def test_concurrent_removal_of_a_tmp_name_is_not_an_error(tmp_path, monkeypatch):
    real_unlink = os.unlink

    def removed_meanwhile(path, *args, **kwargs):
        real_unlink(path, *args, **kwargs)
        raise FileNotFoundError(2, "már nincs")

    monkeypatch.setattr(os, "unlink", removed_meanwhile)
    written = g.write_outputs("base", tmp_path)
    assert written.leftovers == [] and names(tmp_path) == sorted([g.FILE_NAMES["base"], sidecar_name()])


def test_final_file_mode_follows_the_umask_like_a_normal_file(tmp_path):
    old = os.umask(0o022)
    try:
        data_path, sha_path, _digest = g.write_outputs("base", tmp_path)
    finally:
        os.umask(old)
    assert stat_mode(data_path) == 0o644 and stat_mode(sha_path) == 0o644


def stat_mode(path):
    import stat as _stat
    return _stat.S_IMODE(os.stat(path).st_mode)


def _hash_line_for(out_dir):
    """A siker-hash-sor pontos alakja: `<hash>  <adatfájl útvonala>`."""
    return f"{g.reproducibility_check('base')[1]}  {out_dir / g.FILE_NAMES['base']}"


def test_check_flag_failure_with_a_complete_write_exits_1_and_prints_no_hash_line_on_stdout(tmp_path, monkeypatch, capsys):
    """B1: sikeres, teljes `--out` mellett hibás --hash-check: kilépési kód 1, és a siker-hash-sor NEM kerül a standard kimenetre (csak a 0-s kódnál)."""
    real_check = g.reproducibility_check
    monkeypatch.setattr(g, "reproducibility_check", lambda variant: (False, "a" * 64, "b" * 64))
    out = tmp_path / "ok"
    assert g.main(["--variant", "base", "--hash-check", "--out", str(out)]) == 1
    captured = capsys.readouterr()
    hash_line = f"{real_check('base')[1]}  {out / g.FILE_NAMES['base']}"
    assert hash_line not in captured.out and str(out / g.FILE_NAMES["base"]) not in captured.out
    assert "NEM jogosult rekord-jóváhagyásra" in captured.err and hash_line in captured.err          # csak tájékoztatóként, a hibakimeneten
    assert (out / g.FILE_NAMES["base"]).exists() and (out / sidecar_name()).exists()                   # a kiírás maga teljes


def test_check_file_failure_with_a_complete_write_exits_1_and_prints_no_hash_line_on_stdout(tmp_path, capsys):
    corrupt = tmp_path / "rossz.json"
    corrupt.write_bytes(b"{ nem kanonikus json ")
    out = tmp_path / "ok"
    assert g.main(["--variant", "base", "--check-file", str(corrupt), "--out", str(out)]) == 1
    captured = capsys.readouterr()
    assert str(out / g.FILE_NAMES["base"]) not in captured.out and "H2" in captured.out and "HIBA" in captured.out
    assert "NEM jogosult rekord-jóváhagyásra" in captured.err


def test_hash_line_goes_to_stdout_only_with_exit_0(tmp_path, capsys):
    out = tmp_path / "ok"
    assert g.main(["--variant", "base", "--hash-check", "--out", str(out)]) == 0
    captured = capsys.readouterr()
    assert _hash_line_for(out) in captured.out.splitlines() and "NEM jogosult" not in captured.err


def test_failed_write_overrides_a_check_flag_failure_and_prints_no_hash_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(g, "reproducibility_check", lambda variant: (False, "a" * 64, "b" * 64))
    monkeypatch.setattr(g, "serialization_problems", lambda raw: ["szándékos hiba"])
    assert g.main(["--variant", "base", "--hash-check", "--out", str(tmp_path / "fail")]) == 2        # a sikertelen kiírás kódja felülírja az 1-et (dokumentált)
    captured = capsys.readouterr()
    assert "nem hagyott maga után fájlt" in captured.err and list((tmp_path / "fail").iterdir()) == []
    assert str(tmp_path / "fail") not in captured.out


def test_lstat_failure_on_a_tmp_name_is_unknown_not_absent_and_nothing_is_deleted(tmp_path, monkeypatch, capsys):
    real_lstat, armed = os.lstat, {"on": False}

    def lstat(path, *args, **kwargs):
        if armed["on"] and ".tmp" in Path(path).name:
            raise PermissionError(13, "szándékos lstat-hiba")
        return real_lstat(path, *args, **kwargs)

    unlinks = record_unlinks(monkeypatch)
    monkeypatch.setattr(os, "lstat", lstat)

    def failing(raw):
        armed["on"] = True
        return ["szándékos hiba"]

    monkeypatch.setattr(g, "serialization_problems", failing)
    assert g.main(["--variant", "base", "--out", str(tmp_path / "out")]) == 3
    armed["on"] = False
    err = capsys.readouterr().err
    assert unlinks == [] and len(list((tmp_path / "out").iterdir())) == 2 and "az állapot nem állapítható meg" in err


# --- A pár végi (0-s kód előtti) ellenőrzés tesztvédelme: az M29 és az M30 mutáns ellen ---
# Fázisalapú instrumentáció: a közzétételi fázist a végrehajtott `os.link` hívások száma adja (0 = még nincs link, 1 = a sidecar közzétéve, 2 = mindkét végleges fájl közzétéve),
# nem globális hívásszámlálás. Minden teszt (1) bizonyítja, hogy az injektált hiba ténylegesen és a szándékolt fázisban következett be; (2) a pontos kilépési kódot és
# diagnosztikát állítja, nem csak „nem nulla”-t; (3) kontrollteszttel igazolja, hogy a hibainjektáló gépezet hiba nélkül inert (0-s kód, hash-sor), tehát a bukás az
# injektált hibából ered, nem a fixture-ből vagy más futási hibából.

def _published_paths(err):
    """A hibakimenet „közzétett, NEM visszagörgetett végleges fájl” soraiban felsorolt útvonalak."""
    out = set()
    for line in err.splitlines():
        if "közzétett, NEM visszagörgetett végleges fájl" in line:
            out.add(line.split("(a kimenet hiányos): ", 1)[1].split(": ", 1)[0])
    return out


def _link_phase_tracker(monkeypatch):
    """A közzétételi fázis: a sikeresen végrehajtott `os.link` hívások száma (0, 1, 2)."""
    phase = {"links": 0}

    def hook(n, src, dst, real):
        result = real()
        phase["links"] = n
        return result

    link_hook(monkeypatch, hook)
    return phase


def _inject_sidecar_pread(monkeypatch, out, target_phase):
    """A sidecar ideiglenes fájl leírójára az `os.pread` EGYSZER I/O-hibát dob: a `target_phase` fázis ELSŐ sidecar-olvasásakor (None: nincs injektálás, csak a fázisok rögzítése).
    A fázisok szándékolt ellenőrzései: 0 = közzététel előtti ellenőrzés, 1 = a sidecar közzététele utáni tartalom-ellenőrzés, 2 = a pár végi újraellenőrzés."""
    phase = _link_phase_tracker(monkeypatch)
    sidecar_final, data_final = out / sidecar_name(), out / g.FILE_NAMES["base"]
    real_open, real_pread = os.open, os.pread
    sidecar_fds, seen, injected = set(), [], []

    def spy_open(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        name = Path(path).name
        if ".sha256." in name and name.endswith(".tmp"):
            sidecar_fds.add(fd)
        return fd

    def pread(fd, length, offset):
        if fd in sidecar_fds:
            seen.append(phase["links"])
            if target_phase is not None and phase["links"] == target_phase and not injected:
                injected.append({"phase": phase["links"], "sidecar_final": sidecar_final.exists(), "data_final": data_final.exists()})
                raise OSError(5, "szándékos I/O-hiba")
        return real_pread(fd, length, offset)

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "pread", pread)
    return seen, injected


def test_control_sidecar_pread_instrumentation_is_inert_without_injection(tmp_path, monkeypatch, capsys):
    """Kontroll (M29): injektálás nélkül a kiírás 0-s kóddal, a hash-sorral zárul, és a sidecar leírót mindhárom fázisban (közzététel előtt, a sidecar közzététele után, a pár végén) olvasta a kód."""
    out = tmp_path / "out"
    seen, injected = _inject_sidecar_pread(monkeypatch, out, None)
    assert g.main(["--variant", "base", "--out", str(out)]) == 0
    captured = capsys.readouterr()
    assert injected == [] and set(seen) == {0, 1, 2} and seen == sorted(seen)
    assert captured.out.strip() == f"{g.reproducibility_check('base')[1]}  {out / g.FILE_NAMES['base']}" and captured.err == ""


@pytest.mark.parametrize("target_phase,expected_exit,published", [
    pytest.param(0, 2, set(), id="before-publication"),               # a közzététel előtti ellenőrzés: semmi sincs közzétéve
    pytest.param(1, 3, {"sidecar"}, id="after-sidecar-publication"),  # a sidecar közzététele után, az adatfájl előtt
    pytest.param(2, 3, {"sidecar", "data"}, id="final-pair-recheck"), # a pár végi újraellenőrzés: mindkét végleges fájl közzétéve
])
def test_pread_failure_on_the_sidecar_tmp_never_yields_exit_0(tmp_path, monkeypatch, capsys, target_phase, expected_exit, published):
    """M29-védelem: az `os.pread` hibája (csak a sidecar ideiglenes leírón, a szándékolt fázisban) semelyik ellenőrzési ponton nem minősülhet „a tartalom egyezik”-nek."""
    unlinks = record_unlinks(monkeypatch)
    out = tmp_path / "out"
    sidecar, data = out / sidecar_name(), out / g.FILE_NAMES["base"]
    seen, injected = _inject_sidecar_pread(monkeypatch, out, target_phase)
    assert g.main(["--variant", "base", "--out", str(out)]) == expected_exit
    captured = capsys.readouterr()
    # 1. az injektált hiba ténylegesen, pontosan egyszer és a szándékolt fázisban következett be; a fázist a tényleges végleges fájlok megléte is megerősíti
    assert injected == [{"phase": target_phase, "sidecar_final": target_phase >= 1, "data_final": target_phase >= 2}]
    # 2. pontos diagnosztika és kilépési kód; nincs sikeres hash-sor a standard kimeneten
    assert "a kiírás sikertelen: [Errno 5] szándékos I/O-hiba" in captured.err
    assert captured.out == "" and f"{g.reproducibility_check('base')[1]}  " not in captured.out
    expected_paths = {{"sidecar": str(sidecar), "data": str(data)}[k] for k in published}
    assert _published_paths(captured.err) == expected_paths
    if published:
        assert "NEM visszagörgetett" in captured.err
    else:
        assert "Ez a hívás nem hagyott maga után fájlt." in captured.err and "közzétett" not in captured.err
    # 3. a közzétett végleges fájlok érintetlenek (tartalom, nincs törlés), az ideiglenesek takarítva
    if "sidecar" in published:
        assert sidecar.read_bytes() == expected_sidecar_text()
    if "data" in published:
        assert data.read_bytes() == g.canonical_bytes(g.build_capture("base"))
    assert sidecar not in unlinks and data not in unlinks
    assert sorted(p.name for p in out.iterdir()) == sorted(Path(p).name for p in expected_paths)


def _instrument_final_recheck(monkeypatch, out, inject):
    """Fázisalapú eseménynapló. A sidecar végleges nevére az `lstat` hibát dob (inject=True), de CSAK a 2. fázisban, azaz a második sikeres link UTÁN. Események: (fajta, fázis)."""
    phase = _link_phase_tracker(monkeypatch)
    sidecar = out / sidecar_name()
    real_open, real_pread, real_lstat = os.open, os.pread, os.lstat
    data_fds, events = set(), []

    def spy_open(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        name = Path(path).name
        if name.endswith(".tmp") and ".sha256." not in name:
            data_fds.add(fd)
        return fd

    def pread(fd, length, offset):
        if fd in data_fds:
            events.append(("data-pread", phase["links"]))
        return real_pread(fd, length, offset)

    def lstat(path, *args, **kwargs):
        if phase["links"] == 2 and Path(path) == sidecar:
            events.append(("sidecar-lstat-injected" if inject else "sidecar-lstat", 2))
            if inject:
                raise PermissionError(13, "szándékos lstat-hiba")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "pread", pread)
    monkeypatch.setattr(os, "lstat", lstat)
    return events


def _phase2_kinds(events):
    return [kind for kind, links in events if links == 2]


def test_control_final_recheck_instrumentation_is_inert_without_injection(tmp_path, monkeypatch, capsys):
    """Kontroll (M30): injektálás nélkül a kiírás 0-s kóddal zárul, és a 2. fázisban (a második link után) a sorrend: az adatfájl közzététel utáni ellenőrzése, a sidecar pár végi `lstat`-ja, az adatfájl pár végi ellenőrzése."""
    out = tmp_path / "out"
    events = _instrument_final_recheck(monkeypatch, out, inject=False)
    assert g.main(["--variant", "base", "--out", str(out)]) == 0
    captured = capsys.readouterr()
    assert _phase2_kinds(events) == ["data-pread", "sidecar-lstat", "data-pread"]
    assert captured.out.strip() == f"{g.reproducibility_check('base')[1]}  {out / g.FILE_NAMES['base']}" and captured.err == ""


def test_late_lstat_failure_on_the_sidecar_final_blocks_exit_0(tmp_path, monkeypatch, capsys):
    """M30-védelem: ha a sidecar végleges nevének állapota csak a pár végi újraellenőrzéskor (a második sikeres link után) nem állapítható meg, az nem adhat 0-s kódot."""
    unlinks = record_unlinks(monkeypatch)
    out = tmp_path / "out"
    sidecar, data = out / sidecar_name(), out / g.FILE_NAMES["base"]
    events = _instrument_final_recheck(monkeypatch, out, inject=True)
    assert g.main(["--variant", "base", "--out", str(out)]) == 3
    captured = capsys.readouterr()
    # 1. a hiba a SZÁNDÉKOLT fázisban jött: a második link után az adatfájl közzététel utáni ellenőrzése már lefutott (egy korábbi ellenőrzés nem számolhatja el a hibát),
    #    az első injektált hiba a sidecar pár végi lépésében jött, és az adatfájl pár végi ellenőrzése utána már nem futott le (a kód a sidecar-lépésnél megállt)
    kinds = _phase2_kinds(events)
    assert kinds[:2] == ["data-pread", "sidecar-lstat-injected"] and "data-pread" not in kinds[2:]
    assert [kind for kind, links in events if links < 2 and kind.endswith("injected")] == []      # a második link előtt nem volt injektált hiba
    # 2. pontos diagnosztika és kilépési kód; nincs sikeres hash-sor
    assert f"a végleges pár végső ellenőrzése sikertelen (unknown): {sidecar}" in captured.err
    assert f"{sidecar}: az állapot nem állapítható meg (bizonytalan végleges állapot)" in captured.err
    assert captured.out == "" and f"{g.reproducibility_check('base')[1]}  " not in captured.out
    assert _published_paths(captured.err) == {str(data)}          # az adatfájl közzétett; a sidecar állapota bizonytalan, nem „közzétett”-ként jelentett
    # 3. a végleges fájlok érintetlenek (tartalom, nincs törlés), az ideiglenesek takarítva
    assert sidecar.read_bytes() == expected_sidecar_text() and data.read_bytes() == g.canonical_bytes(g.build_capture("base"))
    assert sidecar not in unlinks and data not in unlinks
    assert sorted(p.name for p in out.iterdir()) == sorted([g.FILE_NAMES["base"], sidecar_name()])
