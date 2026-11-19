"""Kereskedelmi modell: minimális SZINTETIKUS szimulátor. Specifikáció: docs/SZIMULATOR_SPEC.md (szimulációs feltevések, nem piaci végrehajtási modell).

Egy eszköz, csak long/flat, piaci megbízás, tőkeáttétel nélkül. Csak `synthetic: true`, `SYN-` jelölésű idősort fogad el. A kimenete a működés ellenőrzésére szolgál:
nem teljesítmény, nem kapu-bemenet, és nem optimalizálható. Hálózatot, szolgáltatót, kulcsot és környezeti beállítást nem használ; csak a Python standard könyvtárát.
A számítás `Decimal`-lal, helyi kontextusban történik (prec=60, Inexact csapda): semmit nem kerekít, a nem pontos művelet blokkoló hiba.
"""
import bisect
import dataclasses
import datetime
import decimal
from decimal import Decimal

from .data import TIMEFRAMES

PARAMS = ("initial_cash", "unit", "fee_rate", "fixed_fee", "slippage")
TARGETS = ("LONG", "FLAT")
_CLOSE, _OPEN, _DECISION = 0, 1, 3          # azonos időbélyegen belüli sorrend; a 2 az OPEN_MARK (nem külön esemény, a teljesítés után készül)


class SimulationError(Exception):
    """Blokkoló hiba: a futás nem indul el, vagy leáll. `reason` a rögzített értékkészletből való."""

    def __init__(self, reason, field=None, detail=""):
        super().__init__(f"{reason}" + (f" ({field})" if field else "") + (f": {detail}" if detail else ""))
        self.reason, self.field, self.detail = reason, field, detail


REASONS = ("param_missing", "param_unknown", "param_type", "param_range", "input_not_synthetic", "input_symbol", "input_overlap",
           "strategy_target", "sizing_violation", "decimal_precision")


@dataclasses.dataclass(frozen=True)
class ViewBar:
    """A stratégia számára látható sáv: változtathatatlan, csak árak és idő. Nincs benne teljesítési ár, számla- vagy megbízás-információ."""
    timestamp: datetime.datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


def make_context():
    """A szimulátor helyi Decimal-kontextusa (a globális kontextust nem érinti)."""
    return decimal.Context(prec=60, rounding=decimal.ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                           traps=[decimal.InvalidOperation, decimal.DivisionByZero, decimal.Overflow, decimal.Inexact])


def to_decimal(value):
    """A JSON-ból érkező szám pontos `Decimal`-lá alakítása: float esetén a legrövidebb körbeforduló alakon (`repr`) át, int esetén közvetlenül. Logikai és más típus tilos."""
    if isinstance(value, bool):
        raise TypeError("logikai érték nem szám")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    raise TypeError("nem szám")


def check_params(params):
    """Paraméterek ellenőrzése és `Decimal`-lá alakítása. Bármely hiba blokkoló (SimulationError), a futás el sem indul."""
    if not isinstance(params, dict):
        raise SimulationError("param_type", None, "a paraméterek szótár kell legyenek")
    for key in sorted(k for k in params if k not in PARAMS):
        raise SimulationError("param_unknown", str(key))
    for key in PARAMS:
        if key not in params:
            raise SimulationError("param_missing", key)
    out = {}
    for key in PARAMS:
        value = params[key]
        if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
            raise SimulationError("param_type", key, "csak str, int vagy Decimal lehet (a float tilos)")
        if isinstance(value, str):
            if value != value.strip() or "_" in value:
                raise SimulationError("param_type", key, "nem decimális szöveg")
            try:
                dec = Decimal(value)
            except decimal.InvalidOperation:
                raise SimulationError("param_type", key, "nem decimális szöveg") from None
        else:
            dec = Decimal(value)
        if not dec.is_finite():
            raise SimulationError("param_range", key, "nem véges")
        out[key] = dec
    if not out["initial_cash"] > 0:
        raise SimulationError("param_range", "initial_cash", "pozitív kell legyen")
    if not out["unit"] > 0:
        raise SimulationError("param_range", "unit", "pozitív kell legyen")
    if out["fee_rate"] < 0:
        raise SimulationError("param_range", "fee_rate", "nem negatív kell legyen")
    if out["fixed_fee"] < 0:
        raise SimulationError("param_range", "fixed_fee", "nem negatív kell legyen")
    if not 0 <= out["slippage"] < 1:
        raise SimulationError("param_range", "slippage", "0 <= s < 1 kell legyen")
    return out


def check_series(series):
    """A szimulátor saját bemeneti feltételei az adatszerződés ellenőrzésén túl."""
    if series.synthetic is not True:
        raise SimulationError("input_not_synthetic")
    if not series.symbol.startswith("SYN-"):
        raise SimulationError("input_symbol", "symbol")
    dur = datetime.timedelta(seconds=TIMEFRAMES[series.timeframe])
    previous_end = None
    for i, bar in enumerate(series.bars):
        if previous_end is not None and bar.timestamp - dur < previous_end:
            raise SimulationError("input_overlap", "timestamp", f"bar_index={i}")
        previous_end = bar.timestamp


def simulate(series, strategy, params):
    """Lefuttatja a szimulációt. `strategy(nézet) -> "LONG" | "FLAT" | None`; a nézet a látható sávok változtathatatlan sorozata (ViewBar tuple).
    Visszatérés: szótár (orders, fills, marks, decisions, problems, final). Blokkoló hiba: SimulationError."""
    parsed = check_params(params)
    check_series(series)
    try:
        with decimal.localcontext(make_context()):
            return _run(series, strategy, parsed)
    except decimal.DecimalException as exc:
        raise SimulationError("decimal_precision", None, type(exc).__name__) from exc


def _mark(time, index, kind, cash, qty, ref):
    return {"time": time, "bar_index": index, "kind": kind, "cash": cash, "quantity": qty, "ref": ref, "value": cash + qty * ref}


def _run(series, strategy, params):
    bars = series.bars
    n = len(bars)
    dur = datetime.timedelta(seconds=TIMEFRAMES[series.timeframe])
    u, r, f, s = params["unit"], params["fee_rate"], params["fixed_fee"], params["slippage"]
    vbars = [ViewBar(b.timestamp, *(to_decimal(x) for x in (b.open, b.high, b.low, b.close, b.volume))) for b in bars]
    open_times = [b.timestamp - dur for b in bars]
    astar, running = [], None
    for b in bars:
        running = b.available_at if running is None or b.available_at > running else running      # hatékony elérhetőség (előtag-szabály)
        astar.append(running)
    events = []
    for i in range(n):
        events.append((bars[i].timestamp, _CLOSE, i))
        events.append((open_times[i], _OPEN, i))
    for when in sorted(set(astar)):
        events.append((when, _DECISION, None))
    events.sort(key=lambda e: (e[0], e[1]))

    cash, qty, pending = params["initial_cash"], Decimal(0), None
    orders, fills, marks, decisions, problems = [], [], [], [], []

    def reject(order, reason, time, price):
        order["state"], order["reason"] = "REJECTED", reason
        problems.append({"time": time, "order_id": order["order_id"], "reason": reason, "side": order["side"], "price": price, "cash": cash})

    for time, kind, idx in events:
        if kind == _CLOSE:
            marks.append(_mark(time, idx, "close", cash, qty, vbars[idx].close))
        elif kind == _OPEN:
            if pending is None or pending["eligible_bar"] != idx:
                continue
            order, pending = pending, None                                                           # lezárt
            open_ = vbars[idx].open
            cash_before = cash
            if order["side"] == "BUY":
                price = open_ * (1 + s)
                size_price = price
                avail = cash - f
                if avail <= 0:
                    q = Decimal(0)
                else:
                    k = avail // (size_price * (1 + r) * u)                                          # lefelé vágó egész osztás: nincs osztás-kerekítés
                    q = k * u
                if q < u:
                    reject(order, "insufficient_cash", time, price)
                    continue
                notional = q * price
                fee = r * notional + f
                if notional + fee > cash:                                                            # ellenőrzés a képlet után: a terhelés nem lehet nagyobb a készpénznél
                    raise SimulationError("sizing_violation", None, f"order={order['order_id']}")
                cash = cash - (notional + fee)
                qty = qty + q
            else:
                price = open_ * (1 - s)
                q = qty
                notional = q * price
                fee = r * notional + f
                if cash + (notional - fee) < 0:
                    reject(order, "fee_exceeds_cash", time, price)
                    continue
                cash = cash + (notional - fee)
                qty = qty - q
            order["state"] = "FILLED"
            fills.append({"order_id": order["order_id"], "time": time, "bar_index": idx, "side": order["side"], "quantity": q, "open": open_, "price": price,
                          "notional": notional, "fee": fee, "slippage_cost": q * open_ * s, "cash_before": cash_before, "cash_after": cash})
            marks.append(_mark(time, idx, "open_ref", cash, qty, open_))
        else:
            m = bisect.bisect_right(astar, time)                                                     # a látható sávok száma (az astar monoton nem csökkenő)
            target = strategy(tuple(vbars[:m]))
            if target is not None and target not in TARGETS:
                raise SimulationError("strategy_target", None, "a cél LONG, FLAT vagy None lehet")
            if pending is not None:
                projected = "LONG" if pending["side"] == "BUY" else "FLAT"
            else:
                projected = "LONG" if qty > 0 else "FLAT"
            entry = {"time": time, "view_len": m, "target": target, "projected": projected, "action": "none", "order_id": None}
            if target is not None and target != projected:
                order = {"order_id": f"O{len(orders) + 1}", "side": "BUY" if target == "LONG" else "SELL", "target": target, "created_at": time,
                         "eligible_bar": None, "state": "PENDING", "reason": None}
                orders.append(order)
                entry["order_id"] = order["order_id"]
                if pending is not None:
                    reject(order, "opposite_while_pending", time, None)
                    entry["action"] = "rejected"
                else:
                    j_star = bisect.bisect_right(open_times, time)                                   # a legkisebb j, amelyre o_j > D (szigorúan)
                    if j_star >= n:
                        order["state"], order["reason"] = "EXPIRED", "end_of_data"
                        entry["action"] = "expired"
                    else:
                        order["eligible_bar"] = j_star
                        pending = order
                        entry["action"] = "order"
            decisions.append(entry)

    last = [mk for mk in marks if mk["kind"] == "close"][-1]
    return {"synthetic": True, "symbol": series.symbol, "timeframe": series.timeframe, "params": params, "orders": orders, "fills": fills, "marks": marks,
            "decisions": decisions, "problems": problems,
            "final": {"cash": cash, "quantity": qty, "value": last["value"], "end_time": events[-1][0]}}


def to_jsonable(value):
    """A kimenet szöveges (JSON-ba írható) alakja: Decimal -> `format(d, 'f')`, időpont -> ISO (Z), nincs float."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime.datetime):
        return value.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ").replace(".000000Z", "Z")
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value
