"""A minimális szintetikus szimulátor próbái (docs/SZIMULATOR_SPEC.md). Hálózat nincs; a közös zár minden tesztben él (lásd test_network_guard.py).

Minden próba a `sim` modulon fut (alapértelmezés: a valódi `trading_model.simulator`), így a célzott mutációs próba (test_mutants_are_caught) ugyanezeket a próbákat futtatja a szándékosan elrontott változatokon.
A példák kézzel levezetettek (SZIMULATOR_SPEC.md 8. pont); a számok itt kézzel vannak felvéve, nem a szimulátor kimenetéből.
"""
import ast
import copy
import dataclasses
import datetime
import decimal
import importlib.util
import json
import sys
import tempfile
from decimal import Decimal as Dc
from pathlib import Path

import pytest

from trading_model import data as D
from trading_model import simulator as REAL
from trading_model import synthetic as S

SIM = REAL
BASE = datetime.datetime(2025, 12, 31, tzinfo=datetime.timezone.utc)      # a 0. nap; a k. nap = 2026-01-0k (k >= 1)
ONE_DAY = datetime.timedelta(days=1)


def T(day):
    return (BASE + datetime.timedelta(days=day)).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_of(moment):
    return round((moment - BASE) / ONE_DAY, 6)


def load(capture):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "s.json"
        path.write_text(json.dumps(capture), encoding="utf-8")
        series, problems = D.load_series(path, "s.json")
    assert series is not None, problems
    return series


def series_of(bars, avail=None, timeframe="1d", synthetic=True, symbol="SYN-T"):
    """bars: [(zárás napja, nyitó, záró)]; avail: {1-alapú sorszám: az elérhetővé válás napja}."""
    raw = []
    for i, (t, o, c) in enumerate(bars, 1):
        raw.append({"timestamp": T(t), "open": o, "high": max(o, c), "low": min(o, c), "close": c, "volume": 1, "available_at": T((avail or {}).get(i, t))})
    return load({"schema": 1, "synthetic": synthetic, "symbol": symbol, "timeframe": timeframe, "bars": raw})


def daily(prices, avail=None, **kw):
    return series_of([(k, o, c) for k, (o, c) in enumerate(prices, 1)], avail, **kw)


def params(**kw):
    base = {"initial_cash": "1000", "unit": "1", "fee_rate": "0", "fixed_fee": "0", "slippage": "0"}
    base.update(kw)
    return base


def by_len(mapping, log=None):
    def strategy(view):
        if log is not None:
            log.append(len(view))
        return mapping.get(len(view))
    return strategy


def marks_of(res):
    return [(day_of(m["time"]), m["kind"], m["value"]) for m in res["marks"]]


def fills_of(res):
    return [(day_of(f["time"]), f["side"], f["quantity"], f["price"]) for f in res["fills"]]


def check_identities(res):
    """A-D azonosságok a kimenetből, a szimulátortól függetlenül újraszámolva."""
    with decimal.localcontext() as ctx:
        ctx.prec = 100
        p = res["params"]
        s, r, f, u = p["slippage"], p["fee_rate"], p["fixed_fee"], p["unit"]
        cash, qty, total = p["initial_cash"], Dc(0), Dc(0)
        for fl in res["fills"]:
            sigma = 1 if fl["side"] == "BUY" else -1
            assert fl["cash_before"] == cash
            assert fl["price"] == fl["open"] * (1 + sigma * s)
            assert fl["notional"] == fl["quantity"] * fl["price"]
            assert fl["fee"] == r * fl["notional"] + f
            assert fl["slippage_cost"] == fl["quantity"] * fl["open"] * s
            delta = fl["cash_after"] - fl["cash_before"]
            assert delta == -sigma * fl["quantity"] * fl["open"] - fl["slippage_cost"] - fl["fee"]            # A
            total += delta
            cash = fl["cash_after"]
            qty += sigma * fl["quantity"]
            assert qty >= 0 and qty % u == 0                                                                  # B
            assert cash >= 0
        for m in res["marks"]:                                                                                # C
            before = [fl for fl in res["fills"] if fl["time"] < m["time"] or (fl["time"] == m["time"] and m["kind"] == "open_ref")]
            exp_cash = p["initial_cash"] + sum((fl["cash_after"] - fl["cash_before"] for fl in before), Dc(0))
            exp_qty = sum((fl["quantity"] if fl["side"] == "BUY" else -fl["quantity"] for fl in before), Dc(0))
            assert (m["cash"], m["quantity"]) == (exp_cash, exp_qty)
            assert m["value"] == m["cash"] + m["quantity"] * m["ref"] and m["cash"] >= 0
        assert res["final"]["cash"] == cash and res["final"]["quantity"] == qty
        if qty == 0:                                                                                          # D
            assert res["final"]["value"] - p["initial_cash"] == total


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------
# A-G példák
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_example_a_time_with_zero_costs_in_contiguous_bars(sim=SIM):
    s = daily([(100, 102), (104, 103), (105, 106), (108, 107), (110, 109)])
    res = sim.simulate(s, by_len({1: "LONG", 3: "FLAT"}), params())
    assert [o["eligible_bar"] + 1 for o in res["orders"]] == [3, 5]                                           # a 3. és az 5. sáv nyitója (1-alapú)
    assert fills_of(res) == [(2, "BUY", Dc(9), Dc(105)), (4, "SELL", Dc(9), Dc(110))]
    assert marks_of(res) == [(1, "close", Dc(1000)), (2, "close", Dc(1000)), (2, "open_ref", Dc(1000)), (3, "close", Dc(1009)),
                             (4, "close", Dc(1018)), (4, "open_ref", Dc(1045)), (5, "close", Dc(1045))]
    assert res["final"]["cash"] == Dc(1045) and res["final"]["quantity"] == 0 and res["final"]["value"] == Dc(1045)
    assert [day_of(d["time"]) for d in res["decisions"]] == [1, 2, 3, 4, 5]
    check_identities(res)


def test_example_b_trading_pause_and_non_overlapping_bars(sim=SIM):
    s = series_of([(1, 100, 102), (2, 104, 103), (4, 105, 106)])
    dur = datetime.timedelta(days=1)
    spans = [(b.timestamp - dur, b.timestamp) for b in s.bars]
    assert [(a.strftime("%Y-%m-%dT%H:%M:%SZ"), z.strftime("%Y-%m-%dT%H:%M:%SZ")) for a, z in spans] == [
        ("2025-12-31T00:00:00Z", "2026-01-01T00:00:00Z"), ("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"), ("2026-01-03T00:00:00Z", "2026-01-04T00:00:00Z")]
    assert all(spans[i][0] >= spans[i - 1][1] for i in (1, 2)) and spans[2][0] - spans[1][1] == ONE_DAY        # nincs átfedés, 1 nap szünet
    res = sim.simulate(s, by_len({2: "LONG"}), params())
    assert fills_of(res) == [(3, "BUY", Dc(9), Dc(105))]                                                      # a szünet után a következő nyitón, nincs többletkésés
    assert marks_of(res) == [(1, "close", Dc(1000)), (2, "close", Dc(1000)), (3, "open_ref", Dc(1000)), (4, "close", Dc(1009))]
    assert res["final"]["cash"] == Dc(55)
    check_identities(res)


def test_example_c_delayed_data_and_prefix_rule(sim=SIM):
    s = daily([(99 + k, 100 + k) for k in range(1, 9)], avail={3: 5.5})
    seen = []
    res = sim.simulate(s, lambda v: (seen.append(len(v)), "LONG" if len(v) >= 3 else None)[1], params())
    assert [day_of(d["time"]) for d in res["decisions"]] == [1, 2, 5.5, 6, 7, 8]                                # a 3-5. napon nincs döntés
    assert seen == [1, 2, 5, 6, 7, 8]                                                                         # a 4. sáv (available_at = 4. nap) sem látszik 5,5 előtt: előtag-szabály
    assert len(res["orders"]) == 1
    assert [day_of(o["created_at"]) for o in res["orders"]] == [5.5] and [o["eligible_bar"] + 1 for o in res["orders"]] == [7]
    assert fills_of(res) == [(6, "BUY", Dc(9), Dc(106))] and res["fills"][0]["cash_after"] == Dc(46)
    assert marks_of(res) == [(1, "close", Dc(1000)), (2, "close", Dc(1000)), (3, "close", Dc(1000)), (4, "close", Dc(1000)), (5, "close", Dc(1000)), (6, "close", Dc(1000)),
                             (6, "open_ref", Dc(1000)), (7, "close", Dc(1009)), (8, "close", Dc(1018))]
    assert res["final"]["value"] == Dc(1018)
    check_identities(res)


def test_example_d_price_gap_buy_and_sell_costs(sim=SIM):
    s = daily([(99, 100), (100, 101), (120, 125), (126, 128), (129, 131), (130, 129), (128, 127)])
    res = sim.simulate(s, by_len({1: "LONG", 4: "FLAT"}), params(fee_rate="0.001", fixed_fee="1.00", slippage="0.01"))
    buy, sell = res["fills"]
    assert (day_of(buy["time"]), buy["side"], buy["quantity"], buy["price"], buy["notional"], buy["fee"], buy["cash_after"]) == (
        2, "BUY", Dc(8), Dc("121.20"), Dc("969.60"), Dc("1.9696"), Dc("28.4304"))
    assert (day_of(sell["time"]), sell["side"], sell["quantity"], sell["price"], sell["notional"], sell["fee"], sell["cash_after"]) == (
        5, "SELL", Dc(8), Dc("128.70"), Dc("1029.60"), Dc("2.0296"), Dc("1056.0008"))
    assert [o["eligible_bar"] + 1 for o in res["orders"]] == [3, 6]
    assert marks_of(res) == [(1, "close", Dc(1000)), (2, "close", Dc(1000)), (2, "open_ref", Dc("988.4304")), (3, "close", Dc("1028.4304")),
                             (4, "close", Dc("1052.4304")), (5, "close", Dc("1076.4304")), (5, "open_ref", Dc("1056.0008")),
                             (6, "close", Dc("1056.0008")), (7, "close", Dc("1056.0008"))]
    assert res["final"]["value"] - Dc(1000) == Dc("56.0008") == 8 * (130 - 120) - (buy["fee"] + sell["fee"]) - (buy["slippage_cost"] + sell["slippage_cost"])
    assert (buy["slippage_cost"], sell["slippage_cost"]) == (Dc("9.60"), Dc("10.40"))
    assert buy["cash_after"] - buy["cash_before"] == -Dc("971.5696")
    check_identities(res)


def test_example_e1_e2_unaffordable_buys_are_rejected(sim=SIM):
    s1 = daily([(100, 100), (100, 100), (150, 150), (150, 150)])
    res = sim.simulate(s1, by_len({1: "LONG"}), params(initial_cash="100"))
    assert [(o["state"], o["reason"]) for o in res["orders"]] == [("REJECTED", "insufficient_cash")] and res["fills"] == []
    assert [p["reason"] for p in res["problems"]] == ["insufficient_cash"] and (res["final"]["cash"], res["final"]["quantity"]) == (Dc(100), Dc(0))
    assert all(m["kind"] == "close" for m in res["marks"]) and res["final"]["value"] == Dc(100)                 # elutasításkor nincs open_ref értékelés
    s2 = daily([(100, 100)] * 4)
    res2 = sim.simulate(s2, by_len({1: "LONG"}), params(initial_cash="100.5", fixed_fee="1"))
    assert [(o["state"], o["reason"]) for o in res2["orders"]] == [("REJECTED", "insufficient_cash")] and res2["final"]["cash"] == Dc("100.5")
    assert Dc("100.5") // Dc(100) == 1                                                                         # a díjat nem figyelembe vevő méretezés 1 db-ot venne (101 > 100,5)


def test_example_e3_a_repeated_target_after_rejection_creates_a_new_order_only_at_a_decision_event(sim=SIM):
    s = daily([(100, 100), (100, 100)] + [(150, 150)] * 4)
    res = sim.simulate(s, lambda v: "LONG", params(initial_cash="100"))
    assert [(o["state"], o["reason"]) for o in res["orders"]] == [("REJECTED", "insufficient_cash")] * 4 + [("EXPIRED", "end_of_data")] * 2
    assert [day_of(o["created_at"]) for o in res["orders"]] == [1, 2, 3, 4, 5, 6]                               # új megbízás csak döntési időpontban, nincs automatikus újrapróba
    assert [o["eligible_bar"] + 1 if o["eligible_bar"] is not None else None for o in res["orders"]] == [3, 4, 5, 6, None, None]
    assert [d["projected"] for d in res["decisions"]] == ["FLAT"] * 6                                         # a döntés látja a T-ben történt elutasítást
    assert len(res["problems"]) == 4 and res["fills"] == [] and res["final"]["cash"] == Dc(100)
    # azonos cél a vetített állapottal: nincs új megbízás (elég készpénz, a pozíció már long)
    ok = sim.simulate(daily([(100, 100)] * 6), lambda v: "LONG", params())
    assert len(ok["orders"]) == 1 and [d["action"] for d in ok["decisions"]].count("order") == 1 and len(ok["fills"]) == 1


def test_example_f_no_later_open_the_order_expires_at_creation(sim=SIM):
    res = sim.simulate(daily([(100, 100)] * 4), by_len({3: "LONG"}), params())
    assert [(o["state"], o["reason"], o["eligible_bar"]) for o in res["orders"]] == [("EXPIRED", "end_of_data", None)]
    assert [d["action"] for d in res["decisions"]] == ["none", "none", "expired", "none"]
    assert res["fills"] == [] and res["problems"] == [] and res["final"]["value"] == Dc(1000) and res["final"]["cash"] == Dc(1000)


def test_example_g_bar_available_after_the_last_close(sim=SIM):
    s = daily([(100, 100)] * 5, avail={2: 7})
    seen = []
    res = sim.simulate(s, lambda v: (seen.append(len(v)), "LONG" if len(v) >= 2 else None)[1], params())
    assert [day_of(d["time"]) for d in res["decisions"]] == [1, 7] and seen == [1, 5]
    assert [(o["state"], o["reason"], day_of(o["created_at"])) for o in res["orders"]] == [("EXPIRED", "end_of_data", 7)]
    assert [(day_of(m["time"]), m["value"]) for m in res["marks"]] == [(k, Dc(1000)) for k in range(1, 6)]
    assert day_of(res["final"]["end_time"]) == 7 and res["final"]["value"] == Dc(1000)                          # a záró érték az utolsó CLOSE, nem a késői döntés


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------
# Stratégia-szerződés, függő megbízás
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_strategy_only_gets_an_immutable_view_of_visible_bars(sim=SIM):
    s = daily([(99 + k, 100 + k) for k in range(1, 9)], avail={3: 5.5})
    views = []

    def strategy(view):
        views.append(view)
        return None
    sim.simulate(s, strategy, params())
    assert all(isinstance(v, tuple) and all(isinstance(b, sim.ViewBar) for b in v) for v in views)
    assert [f.name for f in dataclasses.fields(sim.ViewBar)] == ["timestamp", "open", "high", "low", "close", "volume"]    # nincs ár, számla- vagy megbízás-mező
    assert all(isinstance(b.open, Dc) for b in views[0])
    with pytest.raises(dataclasses.FrozenInstanceError):
        views[0][0].open = Dc(1)
    assert views[0] == views[-1][:1]                                                                          # a korábbi nézet a későbbi előtagja, nem változott
    assert max(len(v) for v in views[:3]) == 5 and len(views[2]) == 5 and len(views[1]) == 2                     # 5,5. napon 5 sáv, előtte csak 2


def test_an_invalid_strategy_target_is_a_blocking_error(sim=SIM):
    for bad in ("BUY", "long", 1, True):
        with pytest.raises(sim.SimulationError) as err:
            sim.simulate(daily([(100, 100)] * 3), lambda v: bad, params())
        assert err.value.reason == "strategy_target"


def test_the_same_target_creates_no_new_order_and_the_opposite_one_is_rejected_while_pending(sim=SIM):
    s = daily([(99 + k, 100 + k) for k in range(1, 9)], avail={3: 5.5, 4: 5.8})
    same = sim.simulate(s, by_len({3: "LONG", 5: "LONG"}), params())
    assert [day_of(d["time"]) for d in same["decisions"]] == [1, 2, 5.5, 5.8, 6, 7, 8]
    assert len(same["orders"]) == 1 and [d["action"] for d in same["decisions"]] == ["none", "none", "order", "none", "none", "none", "none"]
    assert same["problems"] == [] and fills_of(same) == [(6, "BUY", Dc(9), Dc(106))]
    opp = sim.simulate(s, by_len({3: "LONG", 5: "FLAT"}), params())
    assert [(o["order_id"], o["side"], o["state"], o["reason"]) for o in opp["orders"]] == [("O1", "BUY", "FILLED", None), ("O2", "SELL", "REJECTED", "opposite_while_pending")]
    assert [p["reason"] for p in opp["problems"]] == ["opposite_while_pending"]
    assert fills_of(opp) == [(6, "BUY", Dc(9), Dc(106))] and opp["final"]["quantity"] == 9                       # a függő megbízás változatlanul teljesült
    assert opp["orders"][0]["eligible_bar"] == 6 and opp["orders"][1]["eligible_bar"] is None
    check_identities(opp)


def test_a_sell_whose_fees_exceed_the_proceeds_is_rejected_without_negative_cash(sim=SIM):
    s = daily([(10, 10)] * 6)
    res = sim.simulate(s, by_len({1: "LONG", 4: "FLAT"}), params(initial_cash="100", fixed_fee="60"))
    assert [(o["side"], o["state"], o["reason"]) for o in res["orders"]] == [("BUY", "FILLED", None), ("SELL", "REJECTED", "fee_exceeds_cash")]
    assert (res["fills"][0]["quantity"], res["fills"][0]["cash_after"]) == (Dc(4), Dc(0))
    assert (res["final"]["cash"], res["final"]["quantity"], res["final"]["value"]) == (Dc(0), Dc(4), Dc(40))
    check_identities(res)


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------
# Jövőbeli ár (5a, 5b külön), méretezés, paraméterek, Decimal
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------

def _price_strategy(view):
    return "LONG" if view[-1].close > view[-1].open else "FLAT"


def test_5a_a_future_price_change_does_not_alter_decisions_and_intents_before_the_data_is_available(sim=SIM):
    for seed, m in ((1, 20), (2, 15), (3, 25)):
        cap = S.make_capture(seed, 40, lag_seconds=2 * 86400)
        mod = copy.deepcopy(cap)
        for b in mod["bars"][m:]:
            for key in ("open", "high", "low", "close"):
                b[key] = round(b[key] * 1.3, 6)
        a, b = load(cap), load(mod)
        first_visible = max(x.available_at for x in a.bars[:m + 1])
        prm = params(initial_cash="1000000")
        ra, rb = sim.simulate(a, _price_strategy, prm), sim.simulate(b, _price_strategy, prm)
        assert ra["problems"] == [] and rb["problems"] == []                                                   # előfeltétel: nincs elutasítás, amely a vetített állapotot eltérítené
        da = [(d["time"], d["view_len"], d["target"]) for d in ra["decisions"] if d["time"] < first_visible]
        db = [(d["time"], d["view_len"], d["target"]) for d in rb["decisions"] if d["time"] < first_visible]
        assert da and da == db and len(da) < len(ra["decisions"])                                              # nem üres, és van a módosított adat után is döntés
        intent = lambda o: (o["order_id"], o["side"], o["target"], o["created_at"], o["eligible_bar"])          # noqa: E731
        ia = [intent(o) for o in ra["orders"] if o["created_at"] < first_visible]
        ib = [intent(o) for o in rb["orders"] if o["created_at"] < first_visible]
        assert ia == ib
        assert ra["final"]["value"] != rb["final"]["value"]                                                    # az adatmódosítás ténylegesen számít a későbbi kimenetben


def test_5b_a_changed_fill_price_changes_price_and_quantity_by_the_formula_while_decisions_stay(sim=SIM):
    prm = params(fee_rate="0.001", fixed_fee="1.00", slippage="0.01")
    base = [(99, 100), (100, 101), (120, 125), (126, 128), (129, 131), (130, 129), (128, 127)]
    ref = sim.simulate(daily(base), by_len({1: "LONG", 4: "FLAT"}), prm)
    for new_open, price, qty, cash_after in (("110", "111.10", 8, "109.3112"), ("100", "101.00", 9, "89.091")):
        bars = [list(b) for b in base]
        bars[2][0] = int(new_open)
        res = sim.simulate(daily([tuple(b) for b in bars]), by_len({1: "LONG", 4: "FLAT"}), prm)
        buy = res["fills"][0]
        assert (buy["price"], buy["quantity"], buy["cash_after"]) == (Dc(price), Dc(qty), Dc(cash_after))
        assert ([(d["time"], d["view_len"], d["target"]) for d in res["decisions"][:2]] == [(d["time"], d["view_len"], d["target"]) for d in ref["decisions"][:2]])
        check_identities(res)
    assert ref["fills"][0]["quantity"] == 8 and ref["fills"][0]["price"] == Dc("121.20")


def test_sizing_rounds_down_to_the_unit_and_includes_the_costs(sim=SIM):
    flat = [(105, 105)] * 4
    half = sim.simulate(daily(flat), by_len({1: "LONG"}), params(unit="0.5"))
    assert (half["fills"][0]["quantity"], half["final"]["cash"]) == (Dc("9.5"), Dc("2.5"))                      # 1000 // 52,5 = 19 egység -> 9,5
    whole = sim.simulate(daily(flat), by_len({1: "LONG"}), params())
    assert (whole["fills"][0]["quantity"], whole["final"]["cash"]) == (Dc(9), Dc(55))
    rate = sim.simulate(daily([(100, 100)] * 4), by_len({1: "LONG"}), params(fee_rate="0.05"))                  # 1000 // 105 = 9 (945 <= 1000); 10 db: 1050 > 1000
    assert (rate["fills"][0]["quantity"], rate["fills"][0]["fee"], rate["final"]["cash"]) == (Dc(9), Dc(45), Dc(55))
    tiny = sim.simulate(daily([(1, 1)] * 4), by_len({1: "LONG"}), params(initial_cash="1", fixed_fee="2"))      # készpénz - díj < 0: q = 0, nem összeomlás
    assert [o["reason"] for o in tiny["orders"]] == ["insufficient_cash"] and tiny["final"]["cash"] == Dc(1)


@pytest.mark.parametrize("bad,reason", [
    ({"unit": None}, "param_missing"),
    ({"leverage": "2"}, "param_unknown"),
    ({"initial_cash": 1000.0}, "param_type"), ({"unit": True}, "param_type"), ({"fee_rate": [1]}, "param_type"), ({"fixed_fee": "abc"}, "param_type"),
    ({"unit": " 1"}, "param_type"), ({"fixed_fee": "1_0"}, "param_type"),
    ({"initial_cash": "NaN"}, "param_range"), ({"slippage": "Infinity"}, "param_range"), ({"unit": Dc("NaN")}, "param_range"),
    ({"initial_cash": "0"}, "param_range"), ({"initial_cash": "-5"}, "param_range"),
    ({"unit": "0"}, "param_range"), ({"unit": "-1"}, "param_range"),
    ({"fee_rate": "-0.001"}, "param_range"), ({"fixed_fee": "-1"}, "param_range"),
    ({"slippage": "-0.01"}, "param_range"), ({"slippage": "1"}, "param_range"), ({"slippage": "1.5"}, "param_range"),
])
def test_invalid_parameters_are_blocking_errors_and_the_run_does_not_start(bad, reason, sim=SIM):
    prm = params()
    for key, value in bad.items():
        if value is None:
            del prm[key]
        else:
            prm[key] = value
    calls = []
    with pytest.raises(sim.SimulationError) as err:
        sim.simulate(daily([(100, 100)] * 3), lambda v: calls.append(1), prm)
    assert err.value.reason == reason and calls == []


def test_parameter_validation_for_non_dict_and_boundary_values(sim=SIM):
    with pytest.raises(sim.SimulationError) as err:
        sim.simulate(daily([(100, 100)] * 3), by_len({}), ["1000"])
    assert err.value.reason == "param_type"
    for good in (params(slippage="0", fee_rate="0", fixed_fee="0"), params(slippage="0.999999"), params(unit="0.001", initial_cash=5),
                 params(initial_cash=Dc("1"), unit=Dc("0.5"))):
        assert sim.simulate(daily([(100, 100)] * 3), by_len({}), good)["final"]["value"] == good_cash(good)


def good_cash(prm):
    return Dc(prm["initial_cash"])


def test_decimal_rules(sim=SIM):
    assert sim.to_decimal(0.1) == Dc("0.1") and sim.to_decimal(0.1) != Dc(0.1) and sim.to_decimal(7) == Dc(7)
    with pytest.raises(TypeError):
        sim.to_decimal(True)
    before = decimal.getcontext().prec
    ctx = sim.make_context()
    assert (ctx.prec, ctx.rounding) == (60, decimal.ROUND_HALF_EVEN) and ctx.traps[decimal.Inexact] and ctx.traps[decimal.InvalidOperation]
    long_rate = "0." + "1" * 58                                                                                  # 58 jegyű arány: a szorzat nem fér 60 jegybe, nem kerekíthet csendben
    with pytest.raises(sim.SimulationError) as err:
        sim.simulate(daily([(105, 105)] * 4), by_len({1: "LONG"}), params(fee_rate=long_rate))
    assert err.value.reason == "decimal_precision"
    assert decimal.getcontext().prec == before                                                                  # a globális kontextus változatlan
    res = sim.simulate(daily([(105, 105)] * 4), by_len({1: "LONG"}), params())
    assert decimal.getcontext().prec == before

    def no_float(x):
        if isinstance(x, dict):
            return all(no_float(v) for v in x.values())
        if isinstance(x, list):
            return all(no_float(v) for v in x)
        return not isinstance(x, (float, Dc))
    out = sim.to_jsonable(res)
    assert no_float(out) and json.loads(json.dumps(out)) == out and out["final"]["cash"] == "55"
    tree = ast.parse(Path(sim.__file__).read_text(encoding="utf-8"))
    assert not any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div) for n in ast.walk(tree))               # nincs osztás: csak a lefelé vágó //
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "float" for n in ast.walk(tree))


def test_input_conditions_beyond_the_data_contract(sim=SIM):
    for kw, reason in (({"synthetic": False}, "input_not_synthetic"), ({"symbol": "XYZ-1"}, "input_symbol")):
        with pytest.raises(sim.SimulationError) as err:
            sim.simulate(daily([(100, 100)] * 3, **kw), by_len({}), params())
        assert err.value.reason == reason
    with pytest.raises(sim.SimulationError) as err:
        sim.simulate(series_of([(1, 100, 100), (1.5, 100, 100)]), by_len({}), params())                         # a sávok átfednek: a szomszédos zárások különbsége < 1 nap
    assert (err.value.reason, err.value.field) == ("input_overlap", "timestamp")
    sim.simulate(series_of([(1, 100, 100), (2, 100, 100), (4, 100, 100)]), by_len({}), params())              # pontosan egy időkeret és a szünet érvényes


def test_the_run_is_deterministic(sim=SIM):
    cap = S.make_capture(4, 50, lag_seconds=86400)
    prm = params(fee_rate="0.001", fixed_fee="1", slippage="0.01")
    a = sim.simulate(load(cap), _price_strategy, prm)
    b = sim.simulate(load(copy.deepcopy(cap)), _price_strategy, prm)
    assert a == b and sim.to_jsonable(a) == sim.to_jsonable(b)


_COMBOS = (
    dict(initial_cash="1000", unit="1", fee_rate="0.001", fixed_fee="1", slippage="0.01"),
    dict(initial_cash="500", unit="0.5", fee_rate="0", fixed_fee="0", slippage="0"),
    dict(initial_cash="20000", unit="0.001", fee_rate="0.0005", fixed_fee="2.5", slippage="0.002"),
    dict(initial_cash="150", unit="1", fee_rate="0.01", fixed_fee="0.5", slippage="0.05"),
)
_STRATEGIES = (lambda v: "LONG" if len(v) % 5 in (1, 2, 3) else "FLAT", _price_strategy, lambda v: "LONG" if len(v) % 2 else "FLAT")


def test_identities_cash_and_sizing_hold_on_generated_series(sim=SIM):
    checked = rejections = 0
    for seed in range(8):
        for lag in (0, 3 * 86400):
            series = load(S.make_capture(seed, 45, lag_seconds=lag))
            for prm in _COMBOS:
                for strat in _STRATEGIES:
                    res = sim.simulate(series, strat, prm)
                    check_identities(res)
                    p = res["params"]
                    with decimal.localcontext() as ctx:
                        ctx.prec = 100
                        for fl in res["fills"]:
                            if fl["side"] == "BUY":
                                step = fl["quantity"] + p["unit"]
                                assert fl["notional"] + fl["fee"] <= fl["cash_before"]                         # a teljes vételi terhelés nem nagyobb a készpénznél
                                assert step * fl["price"] * (1 + p["fee_rate"]) + p["fixed_fee"] > fl["cash_before"]    # maximalitás: egy egységgel több már nem férne
                        for pr in res["problems"]:
                            if pr["reason"] == "insufficient_cash":
                                rejections += 1
                                assert p["unit"] * pr["price"] * (1 + p["fee_rate"]) + p["fixed_fee"] > pr["cash"]
                    checked += 1
    assert checked == 8 * 2 * 4 * 3 and rejections > 0                                                          # a kemény eset (elutasítás) is előfordult


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------
# Célzott mutációs próba: a fenti próbák közül legalább egynek el kell buknia minden szándékos elrontásnál
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------

SUITE = (
    test_example_a_time_with_zero_costs_in_contiguous_bars, test_example_b_trading_pause_and_non_overlapping_bars, test_example_c_delayed_data_and_prefix_rule,
    test_example_d_price_gap_buy_and_sell_costs, test_example_e1_e2_unaffordable_buys_are_rejected,
    test_example_e3_a_repeated_target_after_rejection_creates_a_new_order_only_at_a_decision_event, test_example_f_no_later_open_the_order_expires_at_creation,
    test_example_g_bar_available_after_the_last_close, test_the_strategy_only_gets_an_immutable_view_of_visible_bars,
    test_the_same_target_creates_no_new_order_and_the_opposite_one_is_rejected_while_pending, test_a_sell_whose_fees_exceed_the_proceeds_is_rejected_without_negative_cash,
    test_5a_a_future_price_change_does_not_alter_decisions_and_intents_before_the_data_is_available,
    test_5b_a_changed_fill_price_changes_price_and_quantity_by_the_formula_while_decisions_stay, test_sizing_rounds_down_to_the_unit_and_includes_the_costs,
    test_decimal_rules, test_identities_cash_and_sizing_hold_on_generated_series,
)

_BISECT = "j_star = bisect.bisect_right(open_times, time)"
MUTANTS = {
    "nem_szigoru_nagyobb_mint": [(_BISECT, "j_star = bisect.bisect_left(open_times, time)")],
    "nincs_azonnali_lejarat": [(_BISECT, "j_star = min(bisect.bisect_right(open_times, time), n - 1)")],
    "meretezes_regi_aron": [("size_price = price", "size_price = vbars[idx - 1].close")],
    "dij_arany_nincs_a_meretben": [("(size_price * (1 + r) * u)", "(size_price * u)")],
    "fix_dij_nincs_a_meretben": [("avail = cash - f", "avail = cash")],
    "dij_nincs_a_meretben_es_nincs_ellenorzes": [("(size_price * (1 + r) * u)", "(size_price * u)"), ("if notional + fee > cash:", "if False:")],
    "elerhetoseg_elotag_nelkul": [("astar.append(running)", "astar.append(b.available_at)")],
    "close_a_teljesites_utan": [("_CLOSE, _OPEN, _DECISION = 0, 1, 3", "_CLOSE, _OPEN, _DECISION = 2, 1, 3")],
    "dontes_a_nyito_elott": [("_CLOSE, _OPEN, _DECISION = 0, 1, 3", "_CLOSE, _OPEN, _DECISION = 0, 3, 1")],
    "inexact_csapda_nelkul": [(", decimal.Inexact])", "])")],
    "vetitett_allapot_fuggo_nelkul": [('projected = "LONG" if pending["side"] == "BUY" else "FLAT"', 'projected = "LONG" if qty > 0 else "FLAT"')],
    "elutasitas_utan_fuggo_marad": [("order, pending = pending, None", "order = pending"), ('order["state"] = "FILLED"', 'order["state"] = "FILLED"; pending = None')],
    "eladasi_csuszas_elojele": [("price = open_ * (1 - s)", "price = open_ * (1 + s)")],
    "jovobeli_sav_latszik": [("m = bisect.bisect_right(astar, time)", "m = n")],
    "eladasi_dij_ellenorzes_nelkul": [("if cash + (notional - fee) < 0:", "if False:")],
}


def load_mutant(name, replacements, workdir):
    source = Path(REAL.__file__).read_text(encoding="utf-8")
    for old, new in replacements:
        assert source.count(old) == 1, (name, old)                                                              # a mutáció illesztési pontja pontosan egyszer szerepel
        source = source.replace(old, new)
    path = Path(workdir) / f"mutant_{name}.py"
    path.write_text(source, encoding="utf-8")
    modname = f"trading_model._mutant_{name}"
    spec = importlib.util.spec_from_file_location(modname, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[modname] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(modname, None)
        raise
    return module


def test_mutants_are_caught(sim=SIM):
    survivors = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, replacements in MUTANTS.items():
            mutant = load_mutant(name, replacements, tmp)
            try:
                killed_by = None
                for fn in SUITE:
                    try:
                        fn(mutant)
                    except (Exception, pytest.fail.Exception):
                        killed_by = fn.__name__
                        break
                if killed_by is None:
                    survivors.append(name)
            finally:
                sys.modules.pop(mutant.__name__, None)
    assert survivors == []
    # a valódi modul a teljes készleten átmegy (a mutációs próba nem hamis riasztás)
    for fn in SUITE:
        fn(REAL)
