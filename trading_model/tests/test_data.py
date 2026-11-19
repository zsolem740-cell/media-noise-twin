"""Az árfolyam-adatszerződés próbái. Csak a repóba tett SZINTETIKUS fixture-t és az ideiglenes mappába írt mintákat használja; hálózat nincs.
A hálózati zárat a közös autouse fixture adja (lásd test_network_guard.py)."""
import ast
import copy
import json
import re
from pathlib import Path

import pytest

from trading_model import data as D
from trading_model import synthetic as S

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures" / "synthetic_bars_a.json"
DOC = HERE.parent / "docs" / "ADATSZERZODES.md"
T0 = "2026-01-02T00:00:00Z"


def bar(ts=T0, **kw):
    b = {"timestamp": ts, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100, "available_at": ts}
    b.update(kw)
    return b


def cap(bars=None, **top):
    d = {"schema": 1, "synthetic": True, "symbol": "SYN-A", "timeframe": "1d", "bars": [bar()] if bars is None else bars}
    d.update(top)
    return d


def put(tmp_path, data, name="a.json"):
    p = tmp_path / name
    p.write_bytes(bytes(data) if isinstance(data, (bytes, bytearray)) else json.dumps(data, ensure_ascii=False).encode("utf-8"))
    return p


def load(tmp_path, data):
    return D.load_series(put(tmp_path, data), "a.json")


def pairs(problems):
    return [(p["field"], p["reason"], p["bar_index"]) for p in problems]


# ---------------------------------------------------------------- a repó szintetikus fixture-je

def test_the_fixture_is_valid_marked_synthetic_and_loses_nothing():
    series, problems = D.load_series(FIX, "synthetic_bars_a.json")
    assert problems == [] and series is not None
    assert series.synthetic is True and series.symbol.startswith("SYN-") and len(series.bars) == 12 and series.capture_id == "synthetic-1-12"
    raw = json.loads(FIX.read_text(encoding="utf-8"))
    assert "SZINTETIKUS" in raw["_note"] and raw["synthetic"] is True
    assert len(FIX.read_text(encoding="utf-8")) < 4000


def test_the_fixture_is_exactly_what_the_generator_produces():
    assert FIX.read_text(encoding="utf-8") == S.dumps(S.make_capture(1, 12))


def test_the_fixture_has_no_secrets_and_no_real_market_identifiers():
    text = FIX.read_text(encoding="utf-8")
    assert not re.search(r"(?i)api[_-]?key|secret|token|password|bearer|gsk_|AIza|@|https?://", text)


def test_loading_never_modifies_the_input_file(tmp_path):
    p = put(tmp_path, cap([bar(), bar("2026-01-03T00:00:00Z")]))
    before = p.read_bytes()
    D.load_series(p)
    D.load_series(put(tmp_path, cap([bar(open="x")]), "b.json"))
    assert p.read_bytes() == before


def test_a_valid_series_has_utc_aware_times_and_exact_values(tmp_path):
    series, problems = load(tmp_path, cap([bar("2026-01-02T01:00:00+01:00", available_at="2026-01-02T00:30:00.5Z"), bar("2026-01-03T00:00:00Z", open=1, high=1, low=1, close=1, volume=0)]))
    assert problems == [] and len(series.bars) == 2
    b = series.bars[0]
    assert b.timestamp.isoformat() == "2026-01-02T00:00:00+00:00" and b.available_at.isoformat() == "2026-01-02T00:30:00.500000+00:00"
    assert (b.open, b.high, b.low, b.close, b.volume) == (10, 11, 9, 10.5, 100)
    assert series.bars[1].volume == 0 and series.bars[1].open == series.bars[1].high == series.bars[1].low == series.bars[1].close == 1      # lapos sáv, nulla forgalom: érvényes


# ---------------------------------------------------------------- hiányzó mezők és típusok (nincs típusátalakítás)

@pytest.mark.parametrize("key", D.BAR_FIELDS)
def test_a_missing_or_null_bar_field_is_reported_and_blocks_the_series(tmp_path, key):
    gone = bar()
    del gone[key]
    for variant in (gone, bar(**{key: None})):
        series, problems = load(tmp_path, cap([bar("2025-12-31T00:00:00Z"), variant]))
        assert series is None and pairs(problems) == [(key, "missing", 1)]


@pytest.mark.parametrize("key", ["open", "high", "low", "close", "volume"])
@pytest.mark.parametrize("bad", ["1", "10", "abc", True, False, [1], {"a": 1}])
def test_a_number_field_of_the_wrong_type_is_never_converted(tmp_path, key, bad):
    series, problems = load(tmp_path, cap([bar(**{key: bad})]))
    assert series is None and pairs(problems) == [(key, "invalid_type", 0)]


@pytest.mark.parametrize("key", ["timestamp", "available_at"])
@pytest.mark.parametrize("bad", [5, 1.5, True, ["2026-01-02T00:00:00Z"], {}])
def test_a_time_field_of_the_wrong_type_is_reported(tmp_path, key, bad):
    series, problems = load(tmp_path, cap([bar(**{key: bad})]))
    assert series is None and pairs(problems) == [(key, "invalid_type", 0)]


@pytest.mark.parametrize("key,value", [("open", 0), ("high", 0), ("low", -1), ("close", -0.5), ("volume", -1), ("volume", -0.001)])
def test_non_positive_prices_and_negative_volume_are_invalid(tmp_path, key, value):
    series, problems = load(tmp_path, cap([bar(**{key: value})]))
    assert series is None and (key, "invalid_value", 0) in pairs(problems)


def test_nan_and_infinite_values_are_invalid_values():
    for v in (float("nan"), float("inf"), float("-inf"), 10 ** 400):
        for field in ("open", "volume"):
            assert D.check_number(v, field) == (None, "invalid_value")


def test_an_overflowing_number_in_the_file_is_an_invalid_value_not_a_crash(tmp_path):
    text = re.sub(r'"volume": \d+', '"volume": 1e999', json.dumps(cap([bar()])), count=1)
    series, problems = load(tmp_path, text.encode())
    assert series is None and pairs(problems) == [("volume", "invalid_value", 0)]


@pytest.mark.parametrize("value", [0, 0.0, 1, 1e-9, 123456789012])
def test_zero_volume_and_tiny_or_huge_finite_values_are_accepted(value):
    assert D.check_number(value, "volume") == (value, None)


def test_a_zero_price_is_never_accepted():
    assert D.check_number(0, "open") == (None, "invalid_value") and D.check_number(1e-12, "open") == (1e-12, None)


# ---------------------------------------------------------------- OHLC-összhang

def test_high_below_the_open_close_range_is_inconsistent(tmp_path):
    series, problems = load(tmp_path, cap([bar(high=10.4)]))                  # a záró 10,5
    assert series is None and pairs(problems) == [("high", "ohlc_inconsistent", 0)]


def test_low_above_the_open_is_inconsistent(tmp_path):
    series, problems = load(tmp_path, cap([bar(low=10.2)]))                   # a nyitó 10
    assert series is None and pairs(problems) == [("low", "ohlc_inconsistent", 0)]


def test_high_below_low_reports_both_fields_in_field_order(tmp_path):
    series, problems = load(tmp_path, cap([bar(open=10, high=8, low=9, close=9.5)]))
    assert series is None and pairs(problems) == [("high", "ohlc_inconsistent", 0), ("low", "ohlc_inconsistent", 0)]


@pytest.mark.parametrize("b", [dict(open=10, high=10.5, low=10, close=10.5), dict(open=10, high=10, low=10, close=10), dict(open=10, high=11, low=9, close=9)])
def test_touching_bounds_are_consistent(tmp_path, b):
    series, problems = load(tmp_path, cap([bar(**b)]))
    assert problems == [] and series is not None


def test_the_ohlc_rule_is_skipped_when_a_price_is_already_invalid(tmp_path):
    series, problems = load(tmp_path, cap([bar(high="x", low=20)]))
    assert pairs(problems) == [("high", "invalid_type", 0)]                   # egy hibára egy bejegyzés, nincs másodlagos zaj


# ---------------------------------------------------------------- időpontok és jövőbe látás

@pytest.mark.parametrize("value,reason", [
    ("2026-01-02", "invalid_time"), ("2026-01-02T00:00:00", "missing_timezone"), ("2026-01-02T00:00:00.5", "missing_timezone"), ("2026-13-01T00:00:00Z", "invalid_time"),
    ("2026-02-30T00:00:00Z", "invalid_time"), ("2026-01-02T24:00:00Z", "invalid_time"), ("2026-01-02T00:60:00Z", "invalid_time"), ("2026-01-02T00:00:60Z", "invalid_time"),
    ("2026-01-02T00:00:00+01:75", "invalid_time"), ("2026-01-02T00:00:00+24:00", "invalid_time"), ("2026-01-02t00:00:00z", "invalid_time"),
    ("2026-01-02 00:00:00Z", "invalid_time"), ("2026-01-02T00:00Z", "invalid_time"), ("2026-01-02T00:00:00+0100", "invalid_time"),
    (" 2026-01-02T00:00:00Z", "invalid_time"), ("2026-01-02T00:00:00Z ", "invalid_time"), ("2026-01-02T00:00:00Z\n", "invalid_time"), ("tegnap", "invalid_time"), ("", "invalid_time")])
def test_invalid_times_are_reported_with_a_fixed_reason(tmp_path, value, reason):
    for key in ("timestamp", "available_at"):
        series, problems = load(tmp_path, cap([bar(**{key: value})]))
        assert series is None and pairs(problems) == [(key, reason, 0)]


def test_availability_before_the_bar_end_is_lookahead(tmp_path):
    series, problems = load(tmp_path, cap([bar(available_at="2026-01-01T23:59:59Z")]))
    assert series is None and pairs(problems) == [("available_at", "lookahead", 0)]


@pytest.mark.parametrize("available_at", [T0, "2026-01-02T00:00:01Z", "2026-01-05T00:00:00Z", "2026-01-02T01:00:00+01:00"])
def test_availability_at_or_after_the_bar_end_is_accepted(tmp_path, available_at):
    series, problems = load(tmp_path, cap([bar(available_at=available_at)]))
    assert problems == [] and series.bars[0].available_at >= series.bars[0].timestamp                 # a "+01:00" ugyanaz a pillanat


def test_lookahead_is_judged_on_the_instant_not_on_the_text(tmp_path):
    series, problems = load(tmp_path, cap([bar(ts="2026-01-02T00:00:00Z", available_at="2026-01-02T00:30:00+01:00")]))        # = 2026-01-01T23:30:00Z
    assert series is None and pairs(problems) == [("available_at", "lookahead", 0)]


# ---------------------------------------------------------------- sorrend

def test_equal_timestamps_are_duplicates_even_with_a_different_zone_notation(tmp_path):
    series, problems = load(tmp_path, cap([bar("2026-01-02T00:00:00Z"), bar("2026-01-02T01:00:00+01:00")]))
    assert series is None and pairs(problems) == [("timestamp", "duplicate_timestamp", 1)]


def test_going_back_in_time_is_not_increasing_and_the_reference_stays_the_latest(tmp_path):
    bars = [bar("2026-01-03T00:00:00Z"), bar("2026-01-02T00:00:00Z"), bar("2026-01-03T00:00:00Z")]
    series, problems = load(tmp_path, cap(bars))
    assert series is None and pairs(problems) == [("timestamp", "not_increasing", 1), ("timestamp", "duplicate_timestamp", 2)]


def test_strictly_increasing_bars_pass_and_the_order_is_kept(tmp_path):
    ts = ["2026-01-02T00:00:00Z", "2026-01-02T00:00:00.000001Z", "2026-01-03T00:00:00Z"]
    series, problems = load(tmp_path, cap([bar(t) for t in ts]))
    assert problems == [] and [b.timestamp.isoformat() for b in series.bars] == ["2026-01-02T00:00:00+00:00", "2026-01-02T00:00:00.000001+00:00", "2026-01-03T00:00:00+00:00"]


def test_a_bad_bar_in_the_middle_blocks_the_series_and_nothing_is_dropped_silently(tmp_path):
    bars = [bar("2026-01-02T00:00:00Z"), bar("2026-01-03T00:00:00Z", open="x"), bar("2026-01-04T00:00:00Z")]
    series, problems = load(tmp_path, cap(bars))
    assert series is None and pairs(problems) == [("open", "invalid_type", 1)]


def test_an_invalid_bar_still_takes_part_in_the_order_check_when_its_time_is_valid(tmp_path):
    bars = [bar("2026-01-03T00:00:00Z"), bar("2026-01-02T00:00:00Z", open="x")]
    series, problems = load(tmp_path, cap(bars))
    assert pairs(problems) == [("open", "invalid_type", 1), ("timestamp", "not_increasing", 1)]


# ---------------------------------------------------------------- szerkezet, sérült fájl, ismeretlen kulcs

@pytest.mark.parametrize("raw", [b"", b"   ", b"{nem json", b'{"schema": 1,', b"\xff\xfe\x00{", b"\x80\x81", b"\xef\xbb\xbf" + json.dumps(cap()).encode(),
                                 b'{"schema": 1, "schema": 1, "synthetic": true, "symbol": "SYN-A", "timeframe": "1d", "bars": []}',
                                 b'{"schema": 1, "synthetic": true, "symbol": "SYN-A", "timeframe": "1d", "bars": [NaN]}',
                                 b'{"schema": 1, "synthetic": true, "symbol": "SYN-A", "timeframe": "1d", "bars": [Infinity]}'])
def test_a_corrupt_file_is_a_file_level_error(tmp_path, raw):
    series, problems = load(tmp_path, raw)
    assert series is None and problems == [{"field": None, "reason": "invalid_json", "symbol": None, "input_file": "a.json", "bar_index": None}]


@pytest.mark.parametrize("content", [[], 5, "szöveg", None, True, [cap()]])
def test_a_non_object_top_level_is_an_invalid_structure(tmp_path, content):
    series, problems = load(tmp_path, json.dumps(content).encode())
    assert series is None and pairs(problems) == [(None, "invalid_structure", None)]


@pytest.mark.parametrize("top", [
    {"schema": "1"}, {"schema": 1.0}, {"schema": True}, {"schema": 2}, {"schema": None},
    {"synthetic": "true"}, {"synthetic": 1}, {"synthetic": None},
    {"symbol": None}, {"symbol": 5}, {"symbol": ""}, {"symbol": "a b"}, {"symbol": "-x"}, {"symbol": "x" * 33}, {"symbol": "árfolyam"},
    {"timeframe": "1w"}, {"timeframe": "1D"}, {"timeframe": None}, {"timeframe": 5},
    {"bars": None}, {"bars": {}}, {"bars": "x"}, {"bars": []}])
def test_a_bad_top_level_field_is_an_invalid_structure(tmp_path, top):
    d = cap()
    d.update(top)                                  # nem cap(**top): a "bars" kulcs a bars paraméterbe kerülne, és a hibás érték elveszne
    series, problems = load(tmp_path, d)
    assert series is None and [(p["field"], p["reason"], p["bar_index"]) for p in problems] == [(None, "invalid_structure", None)]


@pytest.mark.parametrize("missing", ["schema", "synthetic", "symbol", "timeframe", "bars"])
def test_a_missing_top_level_field_is_an_invalid_structure(tmp_path, missing):
    d = cap()
    del d[missing]
    series, problems = load(tmp_path, d)
    assert series is None and pairs(problems) == [(None, "invalid_structure", None)]


@pytest.mark.parametrize("item", [None, 5, 1.5, True, "szöveg", ["x"], []])
def test_a_non_object_bar_is_an_invalid_record_with_its_index(tmp_path, item):
    series, problems = load(tmp_path, cap([bar(), item]))
    assert series is None and pairs(problems) == [(None, "invalid_record", 1)]


def test_unknown_keys_are_reported_but_do_not_block(tmp_path):
    series, problems = load(tmp_path, cap([bar(extra=1)], zebra=2, capture_id="c1", _note="x"))
    assert series is not None and series.capture_id == "c1"
    assert pairs(problems) == [("zebra", "unknown_field", None), ("extra", "unknown_field", 0)]
    assert not D.has_blocking(problems)


def test_an_unknown_key_does_not_hide_a_blocking_problem(tmp_path):
    series, problems = load(tmp_path, cap([bar(extra=1, close=-1)]))
    assert series is None and ("close", "invalid_value", 0) in pairs(problems) and D.has_blocking(problems)


def test_the_symbol_is_carried_into_the_problem_entries(tmp_path):
    series, problems = load(tmp_path, cap([bar(open="x")], symbol="SYN-Z.1"))
    assert [p["symbol"] for p in problems] == ["SYN-Z.1"] and problems[0]["input_file"] == "a.json"


def test_input_file_defaults_to_the_file_name_and_can_be_overridden(tmp_path):
    p = put(tmp_path, b"{", "named.json")
    assert D.load_series(p)[1][0]["input_file"] == "named.json" and D.load_series(p, "x/y.json")[1][0]["input_file"] == "x/y.json"


# ---------------------------------------------------------------- kimeneti szerződés és dokumentáció

def test_every_problem_has_exactly_the_documented_keys_and_a_documented_reason(tmp_path):
    cases = [b"{", [], cap([bar(open="x"), 5, bar(low=99), bar(available_at="2020-01-01T00:00:00Z"), bar(T0), bar("2025-01-01T00:00:00Z", extra=1)], zebra=1)]
    seen = set()
    for i, c in enumerate(cases):
        series, problems = D.load_series(put(tmp_path, c, f"c{i}.json"), f"c{i}.json")
        for p in problems:
            assert tuple(p) == D.PROBLEM_KEYS and p["reason"] in D.REASONS
            seen.add(p["reason"])
    assert {"invalid_json", "invalid_structure", "invalid_type", "invalid_record", "ohlc_inconsistent", "lookahead", "not_increasing", "unknown_field"} <= seen


def test_the_documentation_lists_every_fixed_value():
    text = DOC.read_text(encoding="utf-8")
    for v in D.REASONS + D.BAR_FIELDS + D.PROBLEM_KEYS + tuple(D.TIMEFRAMES) + D.TOP_KEYS:
        assert f"`{v}`" in text, v


def test_every_reason_is_asserted_by_at_least_one_test_in_this_file():
    src = Path(__file__).read_text(encoding="utf-8")
    missing = [r for r in D.REASONS if f'"{r}"' not in src]
    assert not missing, missing


def test_the_non_blocking_and_file_level_sets_are_consistent_with_the_reasons():
    assert set(D.NON_BLOCKING) <= set(D.REASONS) and set(D.FILE_LEVEL) <= set(D.REASONS)
    assert D.NON_BLOCKING == ("unknown_field",) and D.FILE_LEVEL == ("invalid_json", "invalid_structure")


def test_modules_import_only_the_allowed_standard_library_and_never_call_str():
    allowed = {"data.py": {"dataclasses", "datetime", "json", "math", "re", "pathlib"}, "synthetic.py": {"datetime", "json", "math", "random", ".data"}}
    for name, names_ok in allowed.items():
        src = (HERE.parent / name).read_text(encoding="utf-8")
        names, str_calls = set(), []
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Import):
                names |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                names.add(("." * n.level) + (n.module or ""))
            elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "str":
                str_calls.append(n.lineno)
        assert names == names_ok, (name, names)
        assert "environ" not in src and "getenv" not in src and not str_calls, (name, str_calls)
