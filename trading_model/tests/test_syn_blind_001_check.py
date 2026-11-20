"""SYN-BLIND-001 független ellenőr tesztjei: ép adaton RENDBEN, szándékosan elrontott (ideiglenes, munkafán kívüli) másolatokon HIBA.
A HASH, a FORMULA és a CONTRACT ellenőrzés külön eredmény; az ellenőr nem importálja a generátort. A generátor itt csak a próbaadat előállítására és a különbségi
összevetésre szolgál (a tesztben, nem az ellenőrben)."""
import ast
import json
from decimal import Decimal
from pathlib import Path

import pytest

from trading_model.scenarios import syn_blind_001 as g
from trading_model.scenarios import syn_blind_001_check as c


@pytest.fixture
def good(tmp_path):
    out = {}
    for variant in g.VARIANTS:
        data_path, _sha, digest = g.write_outputs(variant, tmp_path)
        out[variant] = (data_path, digest)
    return out


def tampered(tmp_path, name, raw):
    path = tmp_path / name
    path.write_bytes(raw)
    return path


def run(path, variant, recorded):
    return c.check_file(path, variant, recorded)


def ok(result):
    """Az eredmény ÁLLAPOTA rendben ÉS a diagnosztika üres (a `Result` egyenlősége `[]`-lel az állapotot nem nézné)."""
    return result.state == c.OK and list(result) == []


def bad(result):
    return result.state == c.BAD and len(result) > 0


def na(result):
    return result.state == c.NA and len(result) > 0


def states(results):
    return {name: (results[name].state, list(results[name])) for name in c.NAMES}


ALL_OK = {name: (c.OK, []) for name in c.NAMES}


def test_good_files_pass_all_three_checks(good):
    for variant, (path, digest) in good.items():
        assert states(run(path, variant, digest)) == ALL_OK


def test_independent_recomputation_equals_generator_bytes():
    for variant in g.VARIANTS:
        assert c.expected_bytes(variant) == g.canonical_bytes(g.build_capture(variant))
        assert c.hashlib.sha256(c.expected_bytes(variant)).hexdigest() == g.sha256_hex(g.canonical_bytes(g.build_capture(variant)))
        cents = c.expected_cents(variant)
        for row, (o, h, l, cl) in zip(g.build_bars(variant), cents):
            assert tuple(int(x * 100) for x in (row["open"], row["high"], row["low"], row["close"])) == (o, h, l, cl)


def test_checker_does_not_import_generator_or_simulator():
    tree = ast.parse(Path(c.__file__).read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names += [(node.module or "")] + [a.name for a in node.names]
    for name in names:
        assert "syn_blind_001" not in name.replace("syn_blind_001_check", "") and "simulator" not in name and name != "importlib"
    assert "build_bars" not in Path(c.__file__).read_text(encoding="utf-8")


def test_changed_price_with_old_hash_fails_hash_and_formula(good, tmp_path):
    path, digest = good["base"]
    broken = tampered(tmp_path, "ar.json", path.read_bytes().replace(b'"close":100.08', b'"close":100.09', 1))
    result = run(broken, "base", digest)
    assert result["hash"] and result["formula"] and "1. sáv" in result["formula"][0]


def test_rehashed_tampering_passes_hash_but_fails_formula(good, tmp_path):
    path, _digest = good["base"]
    raw = path.read_bytes().replace(b'"close":100.08', b'"close":100.09', 1)
    result = run(tampered(tmp_path, "ujrahash.json", raw), "base", c.hashlib.sha256(raw).hexdigest())
    assert ok(result["hash"]) and bad(result["formula"])     # a hash-egyezés nem bizonyítja a képletnek való megfelelést


def test_formula_conformance_is_not_implied_by_a_matching_bar_count(good, tmp_path):
    path, digest = good["base"]
    obj = json.loads(path.read_text(), parse_float=Decimal)
    # szándékos, de formailag ép hiba: a 56. sáv rése eltűnik (nyitás = előző zárás)
    obj["bars"][55]["open"] = obj["bars"][54]["close"]
    raw = g.canonical_bytes(obj)
    result = run(tampered(tmp_path, "nincsres.json", raw), "base", c.hashlib.sha256(raw).hexdigest())
    assert ok(result["hash"]) and bad(result["formula"]) and any("56. sáv" in p for p in result["formula"])


@pytest.mark.parametrize("old,new,needle", [
    (b'"volume":1000000', b'"volume":1000001', "volume"),
    (b'"timestamp":"2026-01-02T00:00:00Z"', b'"timestamp":"2026-01-02T00:00:01Z"', "timestamp"),
    (b'"symbol":"SYN-BLIND-001"', b'"symbol":"SYN-BLIND-002"', "symbol"),
    (b'"synthetic":true', b'"synthetic":false', "synthetic"),
    (b'"timeframe":"1d"', b'"timeframe":"1h"', "timeframe"),
    (b'"capture_id":"SYN-BLIND-001-v1"', b'"capture_id":"SYN-BLIND-001-v2"', "capture_id"),
    (b'"schema":1', b'"schema":2', "schema"),
    (b'"open":100.00', b'"open":100.0', "2 tizedes"),
    (b'"open":100.00', b'"open":1e2', "2 tizedes"),
])
def test_field_tampering_is_detected_by_formula_check(good, tmp_path, old, new, needle):
    path, digest = good["base"]
    raw = path.read_bytes()
    assert old in raw
    result = run(tampered(tmp_path, "mezo.json", raw.replace(old, new, 1)), "base", digest)
    assert result["hash"] and any(needle in p for p in result["formula"]), result["formula"][:3]


def test_available_at_lookahead_is_caught_by_formula_and_contract(good, tmp_path):
    path, digest = good["base"]
    raw = path.read_bytes().replace(b'"available_at":"2026-01-03T00:00:00Z"', b'"available_at":"2026-01-02T00:00:00Z"', 1)
    result = run(tampered(tmp_path, "lookahead.json", raw), "base", digest)
    assert any("available_at" in p for p in result["formula"]) and bad(result["formula"]) and bad(result["contract"])


def test_high_below_low_is_caught_by_contract(good, tmp_path):
    path, digest = good["base"]
    raw = path.read_bytes().replace(b'"high":100.29,"low":99.70', b'"high":99.60,"low":99.70', 1)
    result = run(tampered(tmp_path, "ohlc.json", raw), "base", digest)
    assert bad(result["contract"]) and bad(result["formula"])


def test_structural_tampering(good, tmp_path):
    path, digest = good["base"]
    raw = path.read_bytes()
    obj = json.loads(raw.decode("ascii"), parse_float=str)
    cases = {
        "hiányzó sáv": b",".join(raw.split(b"},{", 1)[0:1]) + b"}" + b"],\"capture_id\"" + raw.split(b"],\"capture_id\"", 1)[1],
        "szóköz": raw.replace(b'"bars":', b'"bars": ', 1),
        "extra kulcs": raw.replace(b'"schema":1', b'"extra":1,"schema":1', 1),
        "ismétlődő kulcs": raw.replace(b'"schema":1', b'"schema":1,"schema":1', 1),
        "nem JSON": raw[:100],
        "nem ASCII": raw.replace(b"NOT MARKET", "NÓT MARKET".encode("utf-8"), 1),
    }
    for name, broken in cases.items():
        result = run(tampered(tmp_path, "s.json", broken), "base", digest)
        assert bad(result["hash"]) and (bad(result["formula"]) or bad(result["serialization"])), name
        if name in ("szóköz", "ismétlődő kulcs", "nem ASCII", "nem JSON"):
            assert bad(result["serialization"]), name
        (tmp_path / "s.json").unlink()
    assert obj["bars"]


def test_bar_dropped_and_duplicated(good, tmp_path):
    path, digest = good["base"]
    head, rest = path.read_bytes().split(b'"bars":[', 1)
    bars_part, tail = rest.split(b'],"capture_id"', 1)
    items = bars_part.split(b"},{")
    dropped = head + b'"bars":[' + b"},{".join(items[:60] + items[61:]) + b'],"capture_id"' + tail
    duplicated = head + b'"bars":[' + b"},{".join(items[:60] + [items[59]] + items[60:]) + b'],"capture_id"' + tail
    for name, raw in (("dropped", dropped), ("duplicated", duplicated)):
        result = run(tampered(tmp_path, name + ".json", raw), "base", digest)
        assert result["formula"] and result["hash"], name
        assert any("sávok száma" in p for p in result["formula"]), name


def test_wrong_variant_and_missing_hash(good):
    path, digest = good["base"]
    assert bad(run(path, "alt", digest)["formula"])
    assert na(run(path, "base", None)["hash"])
    assert na(run(path, "base", "A" * 64)["hash"]) and na(run(path, "base", "ab")["hash"])
    with pytest.raises(ValueError):
        c.check_file(path, "nincs")


def test_checker_only_reads(good):
    path, digest = good["alt"]
    before = path.read_bytes()
    run(path, "alt", digest)
    assert path.read_bytes() == before


def test_cli_exit_codes_and_separate_lines(good, tmp_path, capsys):
    path, digest = good["base"]
    sha_file = path.with_name(path.name + ".sha256")
    assert c.main(["--variant", "base", "--file", str(path), "--sha256-file", str(sha_file)]) == 0
    out = capsys.readouterr().out
    assert all(w in out for w in ("CONTRACT", "FORMULA", "SERIALIZATION", "HASH")) and "HIBA" not in out
    broken = tampered(tmp_path, "cli.json", path.read_bytes().replace(b'"close":100.08', b'"close":100.09', 1))
    assert c.main(["--variant", "base", "--file", str(broken), "--sha256", digest]) == 1
    assert "HIBA" in capsys.readouterr().out


def test_contract_valid_but_formula_deviating_price_is_detected(good, tmp_path):
    """Az 1. sáv zárása 100,08 helyett 100,09: az adatszerződés szerint érvényes (low <= min, high >= max), a hash újraszámolt, a bájtok kanonikusak -
    csak a FORMULA ellenőrzés jelez, és pontos diagnózist ad (változat, sávindex, mező, várt és kapott érték)."""
    path, _digest = good["base"]
    raw = path.read_bytes().replace(b'"close":100.08', b'"close":100.09', 1)
    result = run(tampered(tmp_path, "szerzodes_szerint_ervenyes.json", raw), "base", c.hashlib.sha256(raw).hexdigest())
    assert ok(result["contract"]) and ok(result["serialization"]) and ok(result["hash"]) and result["formula"].state == c.BAD
    assert result["formula"] == ["[base] 1. sáv, close: kapott '100.09', várt '100.08'"]


def test_timestamp_available_at_extra_bar_and_wrong_hash(good, tmp_path):
    path, digest = good["base"]
    raw = path.read_bytes()
    ts = run(tampered(tmp_path, "t.json", raw.replace(b'"timestamp":"2026-01-02T00:00:00Z"', b'"timestamp":"2026-01-02T00:00:01Z"', 1)), "base", digest)
    assert any("1. sáv, timestamp" in p and "kapott" in p and "várt" in p for p in ts["formula"])
    av = run(tampered(tmp_path, "a.json", raw.replace(b'"available_at":"2026-01-05T00:00:00Z"', b'"available_at":"2026-01-06T00:00:00Z"', 1)), "base", digest)
    assert any("4. sáv, available_at" in p for p in av["formula"])
    head, rest = raw.split(b'"bars":[', 1)
    bars_part, tail = rest.split(b'],"capture_id"', 1)
    extra = head + b'"bars":[' + bars_part + b",{" + bars_part.split(b"},{")[-1].replace(b"2026-05-01", b"2026-05-02") + b'],"capture_id"' + tail
    ex = run(tampered(tmp_path, "e.json", extra), "base", c.hashlib.sha256(extra).hexdigest())
    assert any("sávok száma" in p and "121" in p for p in ex["formula"]) and ok(ex["hash"]) and bad(ex["formula"])
    wrong = run(path, "base", "0" * 64)
    assert bad(wrong["hash"]) and ok(wrong["formula"]) and ok(wrong["serialization"]) and ok(wrong["contract"])


def test_wrong_variant_diagnosis_names_variant_bar_field(good):
    path, digest = good["base"]
    result = run(path, "alt", digest)
    assert ok(result["hash"]) and bad(result["formula"]) and result["formula"][0].startswith("[alt] ")
    assert any(p.startswith("[alt] 51. sáv, ") for p in result["formula"])


def test_serialization_result_is_separate_from_formula(good, tmp_path):
    path, _digest = good["alt"]
    raw = path.read_bytes().replace(b'"bars":', b'"bars": ', 1)       # az értékek mind egyeznek, csak a bájtalak nem kanonikus
    result = run(tampered(tmp_path, "szokoz.json", raw), "alt", c.hashlib.sha256(raw).hexdigest())
    assert ok(result["formula"]) and ok(result["contract"]) and ok(result["hash"]) and bad(result["serialization"])


# --- A felülvizsgálat utáni javítások: állapotok, diagnosztika, hibaágak, HASH, kerekítés ---
import os
from fractions import Fraction


def split_bars(raw):
    head, rest = raw.split(b'"bars":[', 1)
    bars_part, tail = rest.split(b'],"capture_id"', 1)
    return head, bars_part.split(b"},{"), tail


def join_bars(head, items, tail):
    return head + b'"bars":[' + b"},{".join(items) + b'],"capture_id"' + tail


def test_checker_rounding_hand_cases_distinguish_half_even_from_half_up():
    cases = [(Fraction(1, 2), 0, 1), (Fraction(3, 2), 2, 2), (Fraction(5, 2), 2, 3), (Fraction(7, 2), 4, 4), (Fraction(9, 2), 4, 5), (Fraction(-5, 2), -2, -2)]
    for value, half_even, half_up in cases:
        assert c.round_cents(value) == half_even
    assert sum(1 for _v, e, u in cases if e != u) >= 3
    assert c.round_cents(Fraction(2499, 1000)) == 2 and c.round_cents(Fraction(2501, 1000)) == 3


def test_missing_bar_is_identified_by_index_without_a_cascade(good, tmp_path):
    path, digest = good["base"]
    head, items, tail = split_bars(path.read_bytes())
    raw = join_bars(head, items[:60] + items[61:], tail)           # a 61. sáv (2026-03-03) hiányzik
    result = run(tampered(tmp_path, "hianyzo.json", raw), "base", c.hashlib.sha256(raw).hexdigest())
    assert list(result["formula"]) == ["[base] sávok száma: kapott 119, várt 120", "[base] hiányzó sáv: a(z) 61. sáv (2026-03-03T00:00:00Z) nincs a fájlban"]
    assert result["formula"].state == c.BAD and result["hash"].state == c.OK


def test_extra_and_duplicate_bars_are_identified(good, tmp_path):
    path, _digest = good["base"]
    head, items, tail = split_bars(path.read_bytes())
    last = items[-1]
    extra = items[:-1] + [last[:-1], last.replace(b"2026-05-01", b"2026-05-02")]
    raw = join_bars(head, extra, tail)
    formula = run(tampered(tmp_path, "tobblet.json", raw), "base", None)["formula"]
    assert len(formula) == 2 and "többlet sáv: a fájl 121. pozíciója (timestamp '2026-05-02T00:00:00Z'" in formula[1] and "'close': '100.52'" in formula[1]
    dup = join_bars(head, items[:-1] + [last[:-1], last], tail)               # a 120. sáv kétszer
    formula = run(tampered(tmp_path, "ismetlodo.json", dup), "base", None)["formula"]
    assert any("ismétlődő sáv: a(z) 120. sáv" in p and "120. és 121. pozícióján" in p for p in formula)


def test_wrong_timestamp_with_correct_count_is_a_field_diagnosis(good, tmp_path):
    path, _digest = good["base"]
    raw = path.read_bytes().replace(b'"timestamp":"2026-01-02T00:00:00Z"', b'"timestamp":"2026-01-02T00:00:01Z"', 1)
    formula = run(tampered(tmp_path, "ido.json", raw), "base", None)["formula"]
    assert formula == ["[base] 1. sáv, timestamp: kapott '2026-01-02T00:00:01Z', várt '2026-01-02T00:00:00Z'"]


def test_truncated_cli_output_reports_total_and_omitted_counts(good, capsys):
    path, digest = good["base"]
    assert c.main(["--variant", "alt", "--file", str(path), "--sha256", digest]) == 1
    out = capsys.readouterr().out
    total = len(run(path, "alt", digest)["formula"])
    assert total > c.SHOWN and f"{total} hiba" in out
    assert f"és még {total - c.SHOWN} további diagnózis kihagyva (összesen {total}, megjelenítve {c.SHOWN})" in out


def test_user_facing_bar_index_is_uniformly_one_based(good, tmp_path):
    path, digest = good["base"]
    raw = path.read_bytes().replace(b'"high":100.29,"low":99.70', b'"high":99.60,"low":99.70', 1)
    result = run(tampered(tmp_path, "ohlc.json", raw), "base", c.hashlib.sha256(raw).hexdigest())
    assert result["contract"] and all("1. sáv" in p for p in result["contract"]) and not any(p.endswith("/0") or "/0" in p for p in result["contract"])
    assert any(p.startswith("[base] 1. sáv, high:") for p in result["formula"])


@pytest.mark.parametrize("bars_text", [b"5", b"true", b"null", b'"x"', b"{}"])
def test_non_list_bars_does_not_crash_and_is_reported(good, tmp_path, bars_text):
    path, _digest = good["base"]
    head, rest = path.read_bytes().split(b'"bars":[', 1)
    tail = rest.split(b'],"capture_id"', 1)[1]
    raw = head + b'"bars":' + bars_text + b',"capture_id"' + tail
    result = run(tampered(tmp_path, "bars.json", raw), "base", c.hashlib.sha256(raw).hexdigest())
    assert set(result) == set(c.NAMES) and result["formula"].state == c.BAD and any("bars" in p for p in result["formula"])


def test_unreadable_or_unparseable_input_is_not_evaluable_not_a_traceback(tmp_path, capsys):
    missing = tmp_path / "nincs.json"
    result = run(missing, "base", "a" * 64)
    assert all(result[n].state == c.NA and "nem olvasható" in result[n][0] for n in c.NAMES)
    assert c.main(["--variant", "base", "--file", str(missing)]) == 2
    captured = capsys.readouterr()
    assert captured.err == "" and "NEM ÉRTÉKELHETŐ" in captured.out
    directory = run(tmp_path, "base", None)
    assert all(directory[n].state == c.NA for n in c.NAMES)
    for name, raw in (("ures", b""), ("utf8", b"\xff\xfe"), ("mely", b"[" * 200000), ("szemet", b"{")):
        result = run(tampered(tmp_path, name + ".json", raw), "base", c.hashlib.sha256(raw).hexdigest())
        assert result["formula"].state == c.NA and result["serialization"].state == c.BAD and result["hash"].state == c.OK, name
        assert result["contract"].state in (c.BAD, c.NA), name
        assert c.main(["--variant", "base", "--file", str(tmp_path / (name + ".json")), "--sha256", c.hashlib.sha256(raw).hexdigest()]) == 1
        assert capsys.readouterr().err == "", name


def test_hash_not_evaluable_states_and_exit_code(good, capsys):
    path, digest = good["base"]
    assert run(path, "base", None)["hash"].state == c.NA
    assert run(path, "base", "ABC")["hash"].state == c.NA and run(path, "base", "A" * 64)["hash"].state == c.NA
    assert run(path, "base", "0" * 64)["hash"].state == c.BAD
    assert c.main(["--variant", "base", "--file", str(path)]) == 2          # nincs hiba, de a HASH nem értékelhető
    assert "HASH           NEM ÉRTÉKELHETŐ" in capsys.readouterr().out
    assert c.main(["--variant", "base", "--file", str(path), "--sha256", digest]) == 0


def test_sidecar_format_and_filename_field_are_checked(good, tmp_path):
    path, digest = good["base"]
    sidecar = path.with_name(path.name + ".sha256")
    assert c.check_file(path, "base", sidecar_path=sidecar)["hash"].state == c.OK
    wrong_name = tampered(tmp_path, "mas.sha256", f"{digest}  masik_fajl.json\n".encode())
    result = c.check_file(path, "base", sidecar_path=wrong_name)["hash"]
    assert result.state == c.BAD and "másik fájlhoz tartozik" in result[0] and "'masik_fajl.json'" in result[0]
    for name, raw in (("egy_szokoz", f"{digest} {path.name}\n".encode()), ("nagybetu", f"{digest.upper()}  {path.name}\n".encode()), ("nincs_sorvég", f"{digest}  {path.name}".encode()),
                      ("ketto_sor", f"{digest}  {path.name}\n{digest}  {path.name}\n".encode()), ("ures", b"")):
        result = c.check_file(path, "base", sidecar_path=tampered(tmp_path, name + ".sha256", raw))["hash"]
        assert result.state == c.NA and "formátum" in result[0], name
    assert c.check_file(path, "base", sidecar_path=tmp_path / "nincs.sha256")["hash"].state == c.NA
    with pytest.raises(ValueError):
        c.check_file(path, "base", recorded_sha=digest, sidecar_path=sidecar)


def test_file_identity_and_scenario_conformance_are_reported_separately(good):
    """Az `alt` fájl a SAJÁT sidecarjával: a HASH (fájlazonosság) rendben, de `--variant base` mellett a FORMULA (forgatókönyv) hibás; az `alt` fájl a base hash-ével HASH-hibás."""
    alt_path, alt_digest = good["alt"]
    _base_path, base_digest = good["base"]
    own = c.check_file(alt_path, "base", sidecar_path=alt_path.with_name(alt_path.name + ".sha256"))
    assert own["hash"].state == c.OK and own["formula"].state == c.BAD and own["contract"].state == c.OK and own["serialization"].state == c.OK
    other = run(alt_path, "alt", base_digest)
    assert other["hash"].state == c.BAD and other["formula"].state == c.OK


def test_checker_leaves_a_corrupt_file_unmodified(good, tmp_path):
    path, _digest = good["base"]
    raw = path.read_bytes().replace(b'"close":100.08', b'"close":100.09', 1)
    broken = tampered(tmp_path, "javitatlan.json", raw)
    before = os.stat(broken).st_mtime_ns
    run(broken, "base", None)
    assert broken.read_bytes() == raw and os.stat(broken).st_mtime_ns == before


def test_fifo_device_directory_and_oversized_inputs_are_not_evaluable_and_never_block(tmp_path, capsys):
    fifo = tmp_path / "cso"
    os.mkfifo(fifo)
    for target in (fifo, Path("/dev/zero"), tmp_path):
        result = run(target, "base", None)
        assert all(result[n].state == c.NA and "nem szabályos fájl" in result[n][0] for n in c.NAMES), target
    big = tampered(tmp_path, "nagy.json", b" " * (c.MAX_BYTES + 1))
    assert all(run(big, "base", None)[n].state == c.NA and "túl nagy" in run(big, "base", None)[n][0] for n in c.NAMES)
    assert c.main(["--variant", "base", "--file", str(fifo)]) == 2 and capsys.readouterr().err == ""
    bad_sidecar = tampered(tmp_path, "nagy.sha256", b"a" * (c.MAX_SIDECAR_BYTES + 1))
    assert c.read_sidecar(bad_sidecar)[0] is None and "túl nagy" in c.read_sidecar(bad_sidecar)[1]
    assert c.read_sidecar(fifo)[0] is None and "nem szabályos fájl" in c.read_sidecar(fifo)[1]


def test_state_helpers_do_not_pass_a_wrong_state_with_an_empty_diagnosis():
    """A `good` fixture korábbi `== []` állítása az állapotot nem nézte: egy üres listás `hiba` vagy `nem értékelhető` eredmény átment volna. Az új segédfüggvények mindkettőt vizsgálják."""
    assert ok(c.Result(c.OK)) and not ok(c.Result(c.BAD, [])) and not ok(c.Result(c.NA, [])) and not ok(c.Result(c.OK, ["x"]))
    assert c.Result(c.BAD, []) == [] and c.Result(c.NA, []) == []                  # a régi egyenlőség-vizsgálat ezeket rendben lévőnek látta volna
    assert states({n: c.Result(c.BAD, []) for n in c.NAMES}) != ALL_OK
    assert not bad(c.Result(c.BAD, [])) and not na(c.Result(c.NA, []))
