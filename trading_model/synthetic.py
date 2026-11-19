"""Kereskedelmi modell, 1. alap: determinisztikus SZINTETIKUS árfolyam-idősor (capture JSON) az adatszerződés és a későbbi backtest-motor igazolásához.

Nem valódi piaci adat, és nem is akar annak látszani: minden kimenet `synthetic: true` jelölésű, a szimbólum `SYN-` előtagú. Fix magból (seed) azonos kimenet készül.
Csak a Python standard könyvtárát használja; hálózatot, szolgáltatót, kulcsot és környezeti beállítást nem. A modell (geometriai bolyongás) egyszerű és szándékosan nem realisztikus:
a célja az eszköz próbája, nem a piac utánzása; semmilyen stratégia eredményét nem szabad rajta "teljesítménynek" olvasni.
"""
import datetime
import json
import math
import random

from .data import SCHEMA, TIMEFRAMES

MAX_BARS = 10000
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _check_args(seed, n, symbol, timeframe, start_price, vol, lag_seconds):
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("a seed egész szám kell legyen")
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_BARS:
        raise ValueError(f"az n 1 és {MAX_BARS} közötti egész szám kell legyen")
    if not isinstance(symbol, str) or not symbol.startswith("SYN-"):
        raise ValueError("a szintetikus szimbólum SYN- előtagú kell legyen")
    if timeframe not in TIMEFRAMES:
        raise ValueError("ismeretlen időkeret")
    if isinstance(start_price, bool) or not isinstance(start_price, (int, float)) or not start_price > 0:
        raise ValueError("a kezdő ár pozitív szám kell legyen")
    if isinstance(vol, bool) or not isinstance(vol, (int, float)) or not 0 <= vol <= 0.2:
        raise ValueError("a volatilitás 0 és 0,2 közötti szám kell legyen")
    if isinstance(lag_seconds, bool) or not isinstance(lag_seconds, int) or lag_seconds < 0:
        raise ValueError("az elérhetőségi késés nem negatív egész szám kell legyen")


def make_capture(seed, n=60, symbol="SYN-A", timeframe="1d", start="2026-01-02T00:00:00Z", start_price=100.0, drift=0.0004, vol=0.01, lag_seconds=0):
    """Az idősor capture-szótára. A `timestamp` a sáv vége (a `start` + (i+1) időkeret), az `available_at` = `timestamp` + `lag_seconds`.
    A nyitó ár az előző zárás (nincs rés), a magas/alacsony a nyitó és záró köré épül, így az OHLC-szabályok minden sávra teljesülnek."""
    _check_args(seed, n, symbol, timeframe, start_price, vol, lag_seconds)
    rng = random.Random(seed)
    step = datetime.timedelta(seconds=TIMEFRAMES[timeframe])
    t0 = datetime.datetime.strptime(start, _TIME_FORMAT).replace(tzinfo=datetime.timezone.utc)
    lag = datetime.timedelta(seconds=lag_seconds)
    prev = round(float(start_price), 6)
    bars = []
    for i in range(n):
        close = round(prev * math.exp(drift - 0.5 * vol * vol + vol * rng.gauss(0, 1)), 6)
        up = min(abs(rng.gauss(0, 1)) * vol * 0.5, 0.4)
        down = min(abs(rng.gauss(0, 1)) * vol * 0.5, 0.4)
        high = round(max(prev, close) * (1 + up), 6)
        low = round(min(prev, close) * (1 - down), 6)
        if close <= 0 or low <= 0:
            raise ValueError("az ár a kerekítés után nem pozitív: csökkentsd az n-t vagy a volatilitást (érvénytelen sávot nem adunk ki)")
        volume = max(0, int(1_000_000 * (1 + 0.3 * rng.gauss(0, 1))))
        ts = t0 + step * (i + 1)
        bars.append({"timestamp": ts.strftime(_TIME_FORMAT), "open": prev, "high": high, "low": low, "close": close, "volume": volume,
                     "available_at": (ts + lag).strftime(_TIME_FORMAT)})
        prev = close
    return {"_note": "SZINTETIKUS minta: determinisztikus, kitalált idősor; nem valódi piaci adat.", "schema": SCHEMA, "synthetic": True, "capture_id": f"synthetic-{seed}-{n}",
            "symbol": symbol, "timeframe": timeframe, "bars": bars}


def dumps(capture):
    """A capture determinisztikus JSON-szövege (egy sáv egy sorban), záró sortöréssel."""
    head = {k: v for k, v in capture.items() if k != "bars"}
    lines = [json.dumps(b, ensure_ascii=False, separators=(", ", ": ")) for b in capture["bars"]]
    head_text = json.dumps(head, ensure_ascii=False, separators=(", ", ": "))[:-1]
    return head_text + ', "bars": [\n  ' + ",\n  ".join(lines) + "\n]}\n"
