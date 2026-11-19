"""Kereskedelmi modell: minimális SZINTETIKUS szimulátor. Specifikáció: docs/SZIMULATOR_SPEC.md (szimulációs feltevések, nem piaci végrehajtási modell).

Egy eszköz, csak long/flat, piaci megbízás, tőkeáttétel nélkül. Csak `synthetic: true`, `SYN-` jelölésű idősort fogad el. A kimenete a működés ellenőrzésére szolgál:
nem teljesítmény, nem kapu-bemenet, és nem optimalizálható. Hálózatot, szolgáltatót, kulcsot és környezeti beállítást nem használ; csak a Python standard könyvtárát.
A számítás `Decimal`-lal, helyi kontextusban történik (prec=60, Inexact csapda): semmit nem kerekít, a nem pontos művelet blokkoló hiba.

A stratégia MEGBÍZHATÓ, folyamaton belüli visszahívás (callback). A nézet korlátozása (változtathatatlan sávok, nincs ár, számla vagy megbízás) API-szerződés,
NEM biztonsági sandbox: a stratégia ugyanabban a Python-folyamatban fut, és szándékosan rosszindulatú kód elérheti a motor belső állapotát. Folyamatizolációt a szimulátor nem épít.
A stratégia saját, a motorétól független Decimal-kontextusban fut; a kivételei `strategy_error` hibaként jelennek meg, nem a motor pontossági hibájaként.
"""
import bisect
import dataclasses
import datetime
import decimal
import re
from decimal import Decimal

from .data import NON_BLOCKING, TIMEFRAMES, Bar, Series, check_bar

PARAMS = ("initial_cash", "unit", "fee_rate", "fixed_fee", "slippage")
TARGETS = ("LONG", "FLAT")
_CLOSE, _OPEN, _DECISION = 0, 1, 3          # azonos időbélyegen belüli sorrend; a 2 az OPEN_MARK (nem külön esemény, a teljesítés után készül)
MAX_DIGITS = 20                             # a paraméter legfeljebb ennyi értékes jegyű lehet (ábrázolási korlát, nem a későbbi pontosság garanciája)
MAX_EXPONENT = 30                           # a paraméter kiigazított kitevőjének abszolút értéke legfeljebb ennyi
_SYMBOL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}", re.ASCII)   # az adatszerződés szimbólum-szabálya (a teszt egyezésüket őrzi)


class SimulationError(Exception):
    """Blokkoló hiba: a futás nem indul el, vagy leáll. `reason` a rögzített értékkészletből való."""

    def __init__(self, reason, field=None, detail=""):
        super().__init__(f"{reason}" + (f" ({field})" if field else "") + (f": {detail}" if detail else ""))
        self.reason, self.field, self.detail = reason, field, detail


REASONS = ("param_missing", "param_unknown", "param_type", "param_range", "input_contract", "input_not_synthetic", "input_symbol", "input_overlap",
           "strategy_error", "strategy_target", "sizing_violation", "decimal_precision")


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


def make_strategy_context():
    """A stratégia saját Decimal-kontextusa: a motorétól és a hívóétól független, rögzített alapérték (prec=28, nincs Inexact csapda)."""
    return decimal.Context(prec=28, rounding=decimal.ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                           traps=[decimal.InvalidOperation, decimal.DivisionByZero, decimal.Overflow])


def to_decimal(value):
    """A JSON-ból érkező szám pontos `Decimal`-lá alakítása: float esetén a legrövidebb körbeforduló alakon (`repr`) át, int esetén közvetlenül. Logikai és más típus tilos."""
    if isinstance(value, bool):
        raise TypeError("logikai érték nem szám")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    raise TypeError("nem szám")


def _parse_param(key, value):
    """Egy paraméter típus-, ábrázolási és végesség-ellenőrzése. A hívó Decimal-kontextusától független (a hívó a motor saját kontextusában fut)."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise SimulationError("param_type", key, "csak str, int vagy Decimal lehet (a float tilos)")
    if isinstance(value, str):
        if not value.isascii() or value != value.strip() or "_" in value:
            raise SimulationError("param_type", key, "nem decimális szöveg")
        try:
            dec = Decimal(value)
        except decimal.InvalidOperation:
            raise SimulationError("param_type", key, "nem decimális szöveg") from None
    else:
        dec = Decimal(value)
    if not dec.is_finite():
        raise SimulationError("param_range", key, "nem véges")
    if dec == 0:
        return Decimal(0)                                                                                    # a negatív nulla és a nagy kitevőjű nulla pozitív, egyszerű nullává alakul
    if len(dec.as_tuple().digits) > MAX_DIGITS:
        raise SimulationError("param_range", key, f"legfeljebb {MAX_DIGITS} értékes jegy")
    if abs(dec.adjusted()) > MAX_EXPONENT:
        raise SimulationError("param_range", key, f"a kiigazított kitevő abszolút értéke legfeljebb {MAX_EXPONENT}")
    return dec


def check_params(params):
    """Paraméterek előzetes ellenőrzése (a futás indulása előtt): típus, tartomány és ábrázolási korlát. Bármely hiba blokkoló (SimulationError), a futás el sem indul.
    Sorrend (determinisztikus): nem szöveg típusú kulcs, ismeretlen kulcs (a névsor szerinti első), hiányzó kulcs, majd paraméterenként típus/ábrázolás, végül tartomány.
    NEM garantálja, hogy a későbbi adatfüggő műveletek pontosak lesznek: ilyen hiba a futás közben még `decimal_precision` lehet."""
    if not isinstance(params, dict):
        raise SimulationError("param_type", None, "a paraméterek szótár kell legyenek")
    odd = sorted({type(k).__name__ for k in params if type(k) is not str})
    if odd:
        raise SimulationError("param_unknown", None, f"nem szöveg típusú kulcs: {odd[0]}")
    unknown = sorted(k for k in params if k not in PARAMS)
    if unknown:
        raise SimulationError("param_unknown", unknown[0])
    for key in PARAMS:
        if key not in params:
            raise SimulationError("param_missing", key)
    with decimal.localcontext(make_context()):
        out = {key: _parse_param(key, params[key]) for key in PARAMS}
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


def _aware_utc_text(value, field):
    if not isinstance(value, datetime.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SimulationError("input_contract", field, "nem időzónás időpont")
    try:
        return value.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    except (OverflowError, ValueError):
        raise SimulationError("input_contract", field, "érvénytelen időpont") from None


def check_series(series):
    """A teljes bemeneti adatszerződés kikényszerítése a belépési ponton, a közvetlenül létrehozott Series esetén is (az adatszerződés sáv-ellenőrzésével, `data.check_bar`).
    Hibás bemenetre egységes SimulationError jön: `input_contract` (mező: a hiba helye, részlet: az ok), `input_not_synthetic`, `input_symbol` vagy `input_overlap`."""
    if not isinstance(series, Series):
        raise SimulationError("input_contract", "series", "nem Series")
    if not isinstance(series.synthetic, bool):
        raise SimulationError("input_contract", "synthetic", "logikai érték kell legyen")
    if not isinstance(series.symbol, str) or _SYMBOL.fullmatch(series.symbol) is None:
        raise SimulationError("input_contract", "symbol", "érvénytelen szimbólum")
    if not isinstance(series.timeframe, str) or series.timeframe not in TIMEFRAMES:
        raise SimulationError("input_contract", "timeframe", "ismeretlen időkeret")
    if not isinstance(series.bars, (tuple, list)) or len(series.bars) == 0:
        raise SimulationError("input_contract", "bars", "üres vagy nem sorozat")
    previous = None
    for i, bar in enumerate(series.bars):
        where = f"bars[{i}]"
        if not isinstance(bar, Bar):
            raise SimulationError("input_contract", where, "nem Bar")
        raw = {name: getattr(bar, name) for name in ("open", "high", "low", "close", "volume")}
        raw["timestamp"] = _aware_utc_text(bar.timestamp, f"{where}.timestamp")
        raw["available_at"] = _aware_utc_text(bar.available_at, f"{where}.available_at")
        _clean, problems = check_bar(raw)
        for field, reason in problems:
            if reason not in NON_BLOCKING:
                raise SimulationError("input_contract", f"{where}.{field}", reason)
        if previous is not None and bar.timestamp <= previous:
            raise SimulationError("input_contract", f"{where}.timestamp", "duplicate_timestamp" if bar.timestamp == previous else "not_increasing")
        previous = bar.timestamp
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
            view = tuple(vbars[:m])
            try:
                with decimal.localcontext(make_strategy_context()):                                  # a stratégia a motorétól független kontextusban fut, a kilépéskor a motoré áll vissza
                    target = strategy(view)
            except Exception as exc:                                                                   # a stratégia bármely kivétele a stratégia hibája, nem a motor pontossági hibája
                raise SimulationError("strategy_error", None, type(exc).__name__) from exc
            if target is not None and not (type(target) is str and target in TARGETS):
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
