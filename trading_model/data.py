"""Kereskedelmi modell, 1. alap: az árfolyam-adatszerződés. Mentett idősorok (capture JSON) szigorú ellenőrzése.

Csak helyi fájlt olvas. Hálózatot, szolgáltatót, kulcsot és környezeti beállítást nem használ, a bemenetet nem módosítja.
Nem javít és nem találgat: egyetlen blokkoló hiba esetén az idősor nem használható (nincs csendes kizárás, kerekítés vagy típusátalakítás).
A "jövőbe látás" elleni alapvédelem: minden sávnak van `available_at` ideje (mikor vált ténylegesen ismertté), ami nem lehet korábbi a sáv végénél (`timestamp`).
A szabályok és az értékkészletek: docs/ADATSZERZODES.md.
"""
import dataclasses
import datetime
import json
import math
import re
from pathlib import Path

SCHEMA = 1
TIMEFRAMES = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
TOP_KEYS = ("schema", "synthetic", "symbol", "timeframe", "bars", "capture_id", "_note")
BAR_FIELDS = ("timestamp", "open", "high", "low", "close", "volume", "available_at")
PROBLEM_KEYS = ("field", "reason", "symbol", "input_file", "bar_index")
# Rögzített értékkészlet (a dokumentáció és a teszt egyezésüket őrzi).
REASONS = ("missing", "invalid_type", "invalid_value", "invalid_time", "missing_timezone", "ohlc_inconsistent", "lookahead", "duplicate_timestamp",
           "not_increasing", "unknown_field", "invalid_record", "invalid_json", "invalid_structure")
NON_BLOCKING = ("unknown_field",)
FILE_LEVEL = ("invalid_json", "invalid_structure")

_RANK = {name: i for i, name in enumerate(BAR_FIELDS)}
_SYMBOL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}", re.ASCII)
_TIME = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]{1,6}))?(Z|[+-][0-9]{2}:[0-9]{2})?", re.ASCII)


@dataclasses.dataclass(frozen=True)
class Bar:
    timestamp: datetime.datetime      # a sáv VÉGE (UTC)
    open: float
    high: float
    low: float
    close: float
    volume: float
    available_at: datetime.datetime   # mikor vált a sáv adata ténylegesen ismertté (UTC), >= timestamp


@dataclasses.dataclass(frozen=True)
class Series:
    symbol: str
    timeframe: str
    synthetic: bool
    capture_id: str
    bars: tuple


def parse_time(value):
    """(időpont UTC-ben, ok). Csak `ÉÉÉÉ-HH-NNTÓÓ:PP:MM[.tört]` kötelező időzónával (`Z` vagy `±ÓÓ:PP`), nagy T és Z; a szélén szóköz hiba. Zóna nélküli időpont: `missing_timezone`."""
    if value is None:
        return None, "missing"
    if not isinstance(value, str):
        return None, "invalid_type"
    m = _TIME.fullmatch(value)
    if not m:
        return None, "invalid_time"
    y, mo, d, h, mi, s, frac, tz = m.groups()
    if tz is None:
        return None, "missing_timezone"
    try:
        if tz == "Z":
            off = datetime.timezone.utc
        else:
            if int(tz[4:6]) > 59:
                return None, "invalid_time"
            off = datetime.timezone((1 if tz[0] == "+" else -1) * datetime.timedelta(hours=int(tz[1:3]), minutes=int(tz[4:6])))
        dt = datetime.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), int((frac or "0").ljust(6, "0")), tzinfo=off)
        return dt.astimezone(datetime.timezone.utc), None
    except (ValueError, OverflowError):
        return None, "invalid_time"


def check_number(value, field):
    """(érték, ok). Szám (egész vagy lebegőpontos, nem logikai), véges; ár (`open`, `high`, `low`, `close`) > 0, `volume` >= 0. Szöveg nem alakul számmá."""
    if value is None:
        return None, "missing"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, "invalid_type"
    try:
        finite = math.isfinite(float(value))
    except OverflowError:
        finite = False
    if not finite:
        return None, "invalid_value"
    if field == "volume":
        return (value, None) if value >= 0 else (None, "invalid_value")
    return (value, None) if value > 0 else (None, "invalid_value")


def check_bar(raw):
    """(Bar vagy None, [(mező, ok)]). Egy sáv ellenőrzése a sorozaton belüli sorrend nélkül. Bármely blokkoló hiba esetén a sáv None."""
    if not isinstance(raw, dict):
        return None, [(None, "invalid_record")]
    probs = [(k, "unknown_field") for k in sorted(k for k in raw if k not in BAR_FIELDS)]
    vals, blocking = {}, False
    for key in BAR_FIELDS:
        if key not in raw:
            probs.append((key, "missing"))
            blocking = True
            continue
        if key in ("timestamp", "available_at"):
            val, reason = parse_time(raw[key])
        else:
            val, reason = check_number(raw[key], key)
        if reason:
            probs.append((key, reason))
            blocking = True
        else:
            vals[key] = val
    if all(k in vals for k in ("open", "high", "low", "close")):
        o, h, l, c = vals["open"], vals["high"], vals["low"], vals["close"]
        if h < max(o, c, l):
            probs.append(("high", "ohlc_inconsistent"))
            blocking = True
        if l > min(o, c, h):
            probs.append(("low", "ohlc_inconsistent"))
            blocking = True
    if "timestamp" in vals and "available_at" in vals and vals["available_at"] < vals["timestamp"]:
        probs.append(("available_at", "lookahead"))
        blocking = True
    probs.sort(key=lambda p: (_RANK.get(p[0], 100), p[0] or "", p[1]))
    return (None if blocking else Bar(**vals)), probs


def _no_duplicate_keys(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("ismétlődő kulcs: " + k)
        out[k] = v
    return out


def _reject_constant(name):
    raise ValueError("nem JSON-konstans: " + name)


def _problem(field, reason, symbol, input_file, bar_index):
    return {"field": field, "reason": reason, "symbol": symbol, "input_file": input_file, "bar_index": bar_index}


def has_blocking(problems):
    return any(p["reason"] not in NON_BLOCKING for p in problems)


def load_series(path, input_file=None):
    """(Series vagy None, problémák). Szerkezet: JSON objektum; `schema` pontosan az egész 1; `synthetic` logikai; `symbol` (betű, szám, `.`, `_`, `-`, legfeljebb 32 karakter);
    `timeframe` a TIMEFRAMES egyike; `bars` nem üres lista. Sáv: lásd check_bar. Sorrend: az időbélyegek szigorúan növekednek (azonos pillanat: `duplicate_timestamp`, visszalépés: `not_increasing`).
    Bármely blokkoló hiba esetén az idősor None: nincs csendes kizárás vagy javítás. A bemeneti fájlt nem módosítja."""
    p = Path(path)
    name = input_file if input_file is not None else p.name
    fail = lambda reason, symbol=None: [_problem(None, reason, symbol, name, None)]
    try:
        data = json.loads(p.read_bytes().decode("utf-8"), object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError):
        return None, fail("invalid_json")
    ok = (isinstance(data, dict) and type(data.get("schema")) is int and data["schema"] == SCHEMA and isinstance(data.get("synthetic"), bool)
          and isinstance(data.get("symbol"), str) and _SYMBOL.fullmatch(data["symbol"]) is not None
          and isinstance(data.get("timeframe"), str) and data["timeframe"] in TIMEFRAMES
          and isinstance(data.get("bars"), list) and len(data["bars"]) > 0)
    if not ok:
        return None, fail("invalid_structure", data.get("symbol") if isinstance(data, dict) and isinstance(data.get("symbol"), str) else None)
    symbol = data["symbol"]
    problems = [_problem(k, "unknown_field", symbol, name, None) for k in sorted(k for k in data if k not in TOP_KEYS)]
    bars, prev = [], None
    for i, raw in enumerate(data["bars"]):
        bar, probs = check_bar(raw)
        problems += [_problem(f, r, symbol, name, i) for f, r in probs]
        ts, _reason = parse_time(raw.get("timestamp")) if isinstance(raw, dict) else (None, "invalid_record")
        if ts is not None:
            if prev is not None and ts == prev:
                problems.append(_problem("timestamp", "duplicate_timestamp", symbol, name, i))
            elif prev is not None and ts < prev:
                problems.append(_problem("timestamp", "not_increasing", symbol, name, i))
            prev = ts if prev is None or ts > prev else prev
        if bar is not None:
            bars.append(bar)
    if has_blocking(problems):
        return None, problems
    cid = data.get("capture_id")
    return Series(symbol, data["timeframe"], data["synthetic"], cid if isinstance(cid, str) else "", tuple(bars)), problems
