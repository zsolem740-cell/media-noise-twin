"""A szintetikus idősor-generátor próbái. Hálózat nincs; a közös zár minden tesztben él (lásd test_network_guard.py)."""
import datetime
import json
from pathlib import Path

import pytest

from trading_model import data as D
from trading_model import synthetic as S


def load(tmp_path, capture, name="s.json"):
    p = tmp_path / name
    p.write_text(S.dumps(capture), encoding="utf-8", newline="")
    return D.load_series(p, name)


def test_the_same_seed_gives_the_same_series_and_the_same_bytes():
    a, b = S.make_capture(7, 30), S.make_capture(7, 30)
    assert a == b and S.dumps(a) == S.dumps(b)
    assert S.dumps(S.make_capture(8, 30)) != S.dumps(a)
    assert S.make_capture(7, 31)["bars"][:30] == a["bars"]                     # a mag ugyanazt a sorozatot adja: hosszabb kérés az előző kezdete + újabb sávok


def test_the_generator_output_is_pinned_for_one_seed():
    """Az algoritmus megváltozását jelzi (a random.gauss a Python 3.x kiadásain azonos eredményt ad). Ha ez elbukik, a generátor viselkedése változott."""
    first = S.make_capture(1, 12)["bars"][0]
    assert first == {"timestamp": "2026-01-03T00:00:00Z", "open": 100.0, "high": 102.066354, "low": 99.966832, "close": 101.331978, "volume": 770636,
                     "available_at": "2026-01-03T00:00:00Z"}


def test_every_output_is_marked_synthetic_and_named_as_such():
    c = S.make_capture(3, 5)
    assert c["synthetic"] is True and c["symbol"].startswith("SYN-") and "SZINTETIKUS" in c["_note"] and c["capture_id"] == "synthetic-3-5" and c["schema"] == 1


@pytest.mark.parametrize("timeframe", sorted(D.TIMEFRAMES))
@pytest.mark.parametrize("seed", [0, 1, 2, 17, 12345, -5])
def test_generated_series_always_satisfy_the_data_contract(tmp_path, seed, timeframe):
    series, problems = load(tmp_path, S.make_capture(seed, 150, timeframe=timeframe, vol=0.05))
    assert problems == [] and series is not None and len(series.bars) == 150 and series.synthetic is True


def test_bars_are_chained_and_evenly_spaced_with_the_bar_end_as_timestamp(tmp_path):
    c = S.make_capture(5, 40, timeframe="1h", start="2026-03-01T10:00:00Z", start_price=50)
    series, problems = load(tmp_path, c)
    step = datetime.timedelta(seconds=D.TIMEFRAMES["1h"])
    assert series.bars[0].open == 50.0 and series.bars[0].timestamp == datetime.datetime(2026, 3, 1, 11, 0, tzinfo=datetime.timezone.utc)      # az első sáv vége: start + 1 időkeret
    for prev, cur in zip(series.bars, series.bars[1:]):
        assert cur.open == prev.close and cur.timestamp - prev.timestamp == step


def test_availability_is_the_bar_end_plus_the_requested_lag(tmp_path):
    for lag in (0, 1, 3600, 86400):
        series, problems = load(tmp_path, S.make_capture(2, 10, lag_seconds=lag))
        assert problems == [] and all((b.available_at - b.timestamp).total_seconds() == lag for b in series.bars)


def test_the_generator_cannot_produce_lookahead_or_inconsistent_bars(tmp_path):
    c = S.make_capture(9, 500, vol=0.2)
    assert all(b["available_at"] >= b["timestamp"] and b["high"] >= max(b["open"], b["close"], b["low"]) and b["low"] <= min(b["open"], b["close"], b["high"])
               and b["low"] > 0 and b["volume"] >= 0 for b in c["bars"])


@pytest.mark.parametrize("kwargs,error", [
    ({"seed": True}, TypeError), ({"seed": "1"}, TypeError), ({"seed": 1.5}, TypeError), ({"seed": None}, TypeError),
    ({"n": 0}, ValueError), ({"n": S.MAX_BARS + 1}, ValueError), ({"n": True}, ValueError), ({"n": 1.5}, ValueError), ({"n": -1}, ValueError),
    ({"symbol": "A"}, ValueError), ({"symbol": "syn-A"}, ValueError), ({"symbol": 5}, ValueError), ({"symbol": "SPY"}, ValueError),
    ({"timeframe": "1w"}, ValueError), ({"timeframe": None}, ValueError),
    ({"start_price": 0}, ValueError), ({"start_price": -1}, ValueError), ({"start_price": True}, ValueError), ({"start_price": "1"}, ValueError),
    ({"vol": -0.1}, ValueError), ({"vol": 0.3}, ValueError), ({"vol": True}, ValueError),
    ({"lag_seconds": -1}, ValueError), ({"lag_seconds": True}, ValueError), ({"lag_seconds": 1.5}, ValueError),
    ({"start": "2026-01-02"}, ValueError), ({"start": "2026-01-02T00:00:00+01:00"}, ValueError)])
def test_bad_arguments_are_refused(kwargs, error):
    args = {"seed": 1, "n": 5}
    args.update(kwargs)
    with pytest.raises(error):
        S.make_capture(**args)


def test_a_real_looking_symbol_is_refused_so_synthetic_data_cannot_pose_as_real():
    for sym in ("AAPL", "BTC-USD", "EURUSD", "SYN", "SYN_A"):
        with pytest.raises(ValueError):
            S.make_capture(1, 3, symbol=sym)


def test_dumps_is_valid_json_equal_to_the_capture_and_ends_with_a_newline():
    c = S.make_capture(4, 8)
    text = S.dumps(c)
    assert json.loads(text) == c and text.endswith("\n") and not text.endswith("\n\n") and "\r" not in text
    assert text.count("\n") == 8 + 2                                            # a fejléc sora, 8 sáv (az utolsó után a záró sor), a záró sortörés


def test_a_price_that_would_round_to_zero_is_refused_instead_of_emitting_an_invalid_bar():
    with pytest.raises(ValueError, match="nem pozitív"):
        S.make_capture(0, 10000, vol=0.2)                                       # extrém paraméterek: az ár a 6 tizedes kerekítés után nullára esne
    assert len(S.make_capture(0, 500, vol=0.2)["bars"]) == 500                  # mérsékelt hosszon ugyanez a mag hiba nélkül fut


def test_the_zero_volatility_zero_drift_series_is_flat_and_valid(tmp_path):
    series, problems = load(tmp_path, S.make_capture(1, 5, vol=0, drift=0))
    assert problems == [] and all(b.open == b.close == b.high == b.low == 100.0 for b in series.bars)


def test_generation_does_not_read_the_clock_or_touch_files(tmp_path, monkeypatch):
    before = sorted(p.name for p in Path(tmp_path).iterdir())
    real = datetime.datetime

    class Boom(real):
        @classmethod
        def now(cls, *a, **k):
            raise AssertionError("a generátor nem olvashatja az aktuális időt")
    monkeypatch.setattr(datetime, "datetime", Boom)
    S.make_capture(1, 5)
    assert sorted(p.name for p in Path(tmp_path).iterdir()) == before
