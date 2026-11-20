"""SYN-BLIND-001 FÜGGETLEN adatellenőr. A generátor modult és segédfüggvényeit NEM importálja és nem hívja; a képleteket egész centekkel és `Fraction`-nel,
külön táblázatokból számolja újra. Csak olvas: a bemeneti fájlt nem módosítja és nem javítja, hálózatot nem használ.

Négy, egymástól SZÉTVÁLASZTOTT eredmény, mindegyik három állapotú: `rendben` / `hiba` / `nem értékelhető` (ha az ellenőrzés nem végezhető el, az NEM siker és NEM lefuttatott hiba):
  CONTRACT       az adatszerződés (trading_model.data.load_series) nem talál blokkoló hibát, a sorozat szintetikus és 120 sávos;
  FORMULA        a mezők (idő, ár, kötet, kulcsok) értéke megegyezik a KIVÁLASZTOTT forgatókönyv (base/alt) képleteiből újraszámolt értékkel;
  SERIALIZATION  a bájtok ASCII, kanonikus JSON (rendezett kulcsok, szóköz nélkül, ismétlődő kulcs és NaN nélkül), az ár `repr`-körbefordulása pontos;
  HASH           FÁJL–SIDECAR BÁJTAZONOSSÁG: a fájl SHA-256-a megegyezik a rögzített (sidecar-fájlbeli vagy megadott) értékkel.
A HASH NEM mond semmit arról, melyik forgatókönyvhöz tartozik a fájl (azt a FORMULA mondja meg: egy `alt` fájl a saját hash-ével `--variant base` mellett HASH-RENDBEN, de FORMULA-HIBA),
és nem azt, hogy a hash előre rögzített (pre-registered) érték. Egyik eredmény sem bizonyítja a másikat.

A sidecar formátuma (a `sha256sum -c` formátuma): `<64 kisbetűs hexa>␠␠<fájlnév>\n`; a fájlnévmezőnek az ellenőrzött fájl nevével egyeznie kell.
Diagnózis: változat, sávindex (EGYSÉGESEN 1-alapú: `N. sáv`, a fájl sorrendjétől független, a várt sáv sorszáma), mező, kapott és várt érték.
`expected_bytes` a különbségi teszt referencia-előállítása (a generátortól független újraszámolás); a futó ellenőrzés nem használja, és nincs belőle „várt hash” fogalom.

Parancssor: `python -m trading_model.scenarios.syn_blind_001_check --variant base|alt --file FÁJL [--sha256-file FÁJL | --sha256 HEX]`.
Kilépési kód: 0 = mind rendben; 1 = van hiba; 2 = nincs hiba, de van nem értékelhető eredmény. Kezeletlen kivétel (traceback) nincs: a hibás bemenet `nem értékelhető` vagy `hiba` állapot.
"""
import argparse
import datetime
import hashlib
import json
import math
import os
import re
import stat
import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from trading_model import data as _data

NOTE = "SYNTHETIC PRE-REGISTERED SCENARIO SYN-BLIND-001; NOT MARKET DATA."
IDS = {"base": "SYN-BLIND-001-v1", "alt": "SYN-BLIND-001-ALT-v1"}
# Egy periódus táblázatai (k mod periódus szerint): zaj 0,0004 egységben (11 sáv), kanóc 0,0005 egységben (7 sáv).
NOISE_UNITS = (-5, 2, -2, 5, 1, -3, 4, 0, -4, 3, -1)
UP_UNITS = (1, 4, 7, 3, 6, 2, 5)
DOWN_UNITS = (1, 6, 4, 2, 7, 5, 3)
# (első sáv, utolsó sáv, alap-elmozdulás, zaj-jelző); az S4 és S5 elmozdulása sávonként külön.
STAGE_TABLE = ((1, 20, "0", 1), (21, 45, "0.0030", 1), (46, 48, "0.0250", 0), (49, 55, "-0.0110", 0), (86, 105, "0.0050", 1), (106, 120, "0", 1))
S4_MOVES = {56: "-0.0100", 57: "-0.0100", 58: "-0.0050", 59: "-0.0050", 60: "-0.0050"}
S4_GAP_BAR = 56
S4_GAP = Fraction(-12, 100)
ALT_FROM = 51
ALT_MOVE = Fraction(40, 10000)
BARS = 120
PRICE_TEXT = re.compile(r"[0-9]+\.[0-9]{2}")
SIDECAR_LINE = re.compile(rb"([0-9a-f]{64})  ([^\s/\\]+)\n")
HEX64 = re.compile(r"[0-9a-f]{64}")
TOP_KEYS = {"_note", "bars", "capture_id", "schema", "symbol", "synthetic", "timeframe"}
BAR_KEYS = {"available_at", "close", "high", "low", "open", "timestamp", "volume"}
OK, BAD, NA = "rendben", "hiba", "nem értékelhető"
NAMES = ("contract", "formula", "serialization", "hash")
SHOWN = 20
MAX_BYTES = 1 << 20          # az ép fájl ~30 KB; ennél nagyobb bemenet nem értékelhető (a beolvasás is korlátos)
MAX_SIDECAR_BYTES = 4096


class Result(list):
    """Egy ellenőrzés eredménye: a lista a diagnózisok (vagy a nem értékelhetőség okai); `state`: rendben / hiba / nem értékelhető. Üres lista = rendben."""

    def __init__(self, state, items=()):
        super().__init__(items)
        self.state = state


def _ok():
    return Result(OK)


def _bad(items):
    return Result(BAD if items else OK, items)


def _na(reason):
    return Result(NA, [reason])


class _Num(str):
    """JSON-szám eredeti szövege (a lebegőpontos átalakítás elkerülésére)."""


def _no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("ismétlődő kulcs: " + key)
        out[key] = value
    return out


def _reject_constant(name):
    raise ValueError("nem JSON-konstans: " + name)


def round_cents(value):
    """Egész centre kerekítés, FÉL-PÁROS (a `Fraction` kerekítése): 2,5 -> 2; 3,5 -> 4."""
    return round(value)


def _spec(k, variant):
    """(alap-elmozdulás Fraction, rés Fraction, zaj-jelző) a k. sávra — a táblázatokból."""
    if variant == "alt" and k >= ALT_FROM:
        return ALT_MOVE, Fraction(0), 1
    for first, last, move, flag in STAGE_TABLE:
        if first <= k <= last:
            return Fraction(move), Fraction(0), flag
    if k in S4_MOVES:
        return Fraction(S4_MOVES[k]), (S4_GAP if k == S4_GAP_BAR else Fraction(0)), 0
    if 61 <= k <= 85:
        return (Fraction("0.0080") if k % 3 == 0 else Fraction("-0.0040")), Fraction(0), 1
    raise ValueError("sáv a tartományon kívül")


def expected_cents(variant):
    """A 120 sáv várt (open, high, low, close) értéke egész centben, a képletekből újraszámolva."""
    rows, prev = [], None
    for k in range(1, BARS + 1):
        base, gap, flag = _spec(k, variant)
        if k == 1:
            open_c = 10000
        elif gap != 0:
            open_c = round_cents(prev * (1 + gap))
        else:
            open_c = prev
        move = base + (Fraction(NOISE_UNITS[k % 11] * 4, 10000) if flag else 0)
        close_c = round_cents(open_c * (1 + move))
        high_c = math.ceil(max(open_c, close_c) * (1 + Fraction(UP_UNITS[k % 7] * 5, 10000)))
        low_c = math.floor(min(open_c, close_c) * (1 - Fraction(DOWN_UNITS[k % 7] * 5, 10000)))
        rows.append((open_c, high_c, low_c, close_c))
        prev = close_c
    return rows


def _price(cents):
    return f"{cents // 100}.{cents % 100:02d}"


def _time(k):
    return (datetime.datetime(2026, 1, 1) + datetime.timedelta(days=k)).strftime("%Y-%m-%dT%H:%M:%SZ")


def expected_bytes(variant):
    """A várt kanonikus bájtok a képletekből (a generátor kódja nélkül) — a különbségi teszt referenciája; a futó ellenőrzés nem használja."""
    parts = []
    for k, (o, h, l, c) in enumerate(expected_cents(variant), 1):
        t = _time(k)
        parts.append('{"available_at":"%s","close":%s,"high":%s,"low":%s,"open":%s,"timestamp":"%s","volume":1000000}' % (t, _price(c), _price(h), _price(l), _price(o), t))
    text = '{"_note":"%s","bars":[%s],"capture_id":"%s","schema":1,"symbol":"SYN-BLIND-001","synthetic":true,"timeframe":"1d"}' % (NOTE, ",".join(parts), IDS[variant])
    return text.encode("ascii")


def read_limited(path, limit):
    """(bájtok, None) vagy (None, ok): csak SZABÁLYOS fájlt olvas (FIFO, eszköz, könyvtár nem: nem blokkol), legfeljebb `limit` bájtot."""
    try:
        info = os.stat(path)
        if not stat.S_ISREG(info.st_mode):
            return None, "nem szabályos fájl (könyvtár, eszköz, FIFO vagy hasonló)"
        with open(path, "rb") as handle:
            raw = handle.read(limit + 1)
    except OSError as exc:
        return None, f"nem olvasható ({exc.strerror or type(exc).__name__})"
    if len(raw) > limit:
        return None, f"túl nagy (több mint {limit} bájt)"
    return raw, None


def _parse(raw):
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("a fájl nem ASCII")
    try:
        return json.loads(text, parse_float=_Num, parse_int=int, object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant)
    except RecursionError:
        raise ValueError("túl mély beágyazás")


def _diag(variant, k, field, got, want, pos=None):
    where = f"{k}. sáv" if k else ""
    if k and pos and pos != k:
        where += f" (a fájl {pos}. pozícióján)"
    where = f"{where}, {field}" if where else field
    return f"[{variant}] {where}: kapott {got!r}, várt {want!r}"


def _compare_bar(variant, k, bar, want, problems, pos=None):
    if not isinstance(bar, dict) or set(bar) != BAR_KEYS:
        problems.append(_diag(variant, k, "kulcsok", sorted(bar) if isinstance(bar, dict) else type(bar).__name__, sorted(BAR_KEYS), pos))
        return
    t = _time(k)
    for name in ("timestamp", "available_at"):
        if bar[name] != t:
            problems.append(_diag(variant, k, name, bar[name], t, pos))
    if type(bar["volume"]) is not int or bar["volume"] != 1000000:
        problems.append(_diag(variant, k, "volume", bar["volume"], 1000000, pos))
    for name, cents in zip(("open", "high", "low", "close"), want):
        value = bar[name]
        if not isinstance(value, _Num) or PRICE_TEXT.fullmatch(value) is None:
            problems.append(_diag(variant, k, name, value, _price(cents) + " (pontosan 2 tizedes)", pos))
        elif value != _price(cents):
            problems.append(_diag(variant, k, name, str(value), _price(cents), pos))


def _count_problems(variant, bars, expected):
    """Eltérő sávszámnál az időbélyeg szerint párosít: a hiányzó, a többlet és az ismétlődő sávot sávindexszel azonosítja, a párosítottakat mezőnként összeveti."""
    problems = [_diag(variant, 0, "sávok száma", len(bars), BARS)]
    index_of = {_time(k): k for k in range(1, BARS + 1)}
    first_pos = {}
    for pos, bar in enumerate(bars, 1):
        ts = bar.get("timestamp") if isinstance(bar, dict) else None
        k = index_of.get(ts) if isinstance(ts, str) else None
        if k is None:
            values = {n: bar.get(n) for n in ("open", "high", "low", "close")} if isinstance(bar, dict) else type(bar).__name__
            problems.append(f"[{variant}] többlet sáv: a fájl {pos}. pozíciója (timestamp {ts!r}, értékek {values}) nem tartozik a {BARS} várt sáv közé")
        elif k in first_pos:
            problems.append(f"[{variant}] ismétlődő sáv: a(z) {k}. sáv ({ts}) a fájl {first_pos[k]}. és {pos}. pozícióján is szerepel")
        else:
            first_pos[k] = pos
            _compare_bar(variant, k, bar, expected[k - 1], problems, pos)
    for k in range(1, BARS + 1):
        if k not in first_pos:
            problems.append(f"[{variant}] hiányzó sáv: a(z) {k}. sáv ({_time(k)}) nincs a fájlban")
    return problems


def check_formula(raw, variant):
    """FORMULA: a mezők értéke megegyezik-e a kiválasztott forgatókönyv képleteiből újraszámolt várt értékkel (a bájtalakot a SERIALIZATION nézi)."""
    try:
        obj = _parse(raw)
    except ValueError as exc:
        return _na(f"[{variant}] a fájl nem értelmezhető JSON-ként ({exc}), a képletek nem értékelhetők")
    if not isinstance(obj, dict):
        return _bad([_diag(variant, 0, "gyökér", type(obj).__name__, "objektum")])
    problems = []
    if set(obj) != TOP_KEYS:
        problems.append(_diag(variant, 0, "legfelső kulcsok", sorted(obj), sorted(TOP_KEYS)))
    for key, want in (("_note", NOTE), ("capture_id", IDS[variant]), ("symbol", "SYN-BLIND-001"), ("timeframe", "1d")):
        if obj.get(key) != want:
            problems.append(_diag(variant, 0, key, obj.get(key), want))
    if type(obj.get("schema")) is not int or obj.get("schema") != 1:
        problems.append(_diag(variant, 0, "schema", obj.get("schema"), 1))
    if obj.get("synthetic") is not True:
        problems.append(_diag(variant, 0, "synthetic", obj.get("synthetic"), True))
    bars = obj.get("bars")
    if not isinstance(bars, list):
        return _bad(problems + [_diag(variant, 0, "bars", type(bars).__name__, "list")])
    expected = expected_cents(variant)
    if len(bars) != BARS:
        problems += _count_problems(variant, bars, expected)
    else:
        for k, (want, bar) in enumerate(zip(expected, bars), 1):
            _compare_bar(variant, k, bar, want, problems)
    return _bad(problems)


def _encode(value):
    """Saját kanonikus kódoló az ellenőrzéshez (nem a generátoré): rendezett kulcsok, szóköz nélkül, a szám az eredeti szövegével."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, _Num):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, list):
        return "[" + ",".join(_encode(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k, ensure_ascii=True) + ":" + _encode(value[k]) for k in sorted(value)) + "}"
    raise ValueError("nem kódolható típus")


def check_serialization(raw, variant):
    """SERIALIZATION: ASCII; érvényes JSON ismétlődő kulcs és NaN/Infinity nélkül; a bájtok megegyeznek a saját kanonikus újrakódolással; az ár `repr`-körbefordulása pontos.
    Értelmezhetetlen bájtok = HIBA (nem kanonikus JSON)."""
    try:
        obj = _parse(raw)
        again = _encode(obj).encode("ascii")
    except (ValueError, RecursionError) as exc:
        return _bad([f"[{variant}] nem értelmezhető vagy nem újrakódolható kanonikus JSON-ként: {exc}"])
    problems = []
    if again != raw:
        first = next((i for i, (x, y) in enumerate(zip(raw, again)) if x != y), min(len(raw), len(again)))
        problems.append(f"[{variant}] a bájtok nem kanonikusak: első eltérés a(z) {first}. bájtnál (fájl {len(raw)} bájt, kanonikus {len(again)} bájt)")
    bars = obj.get("bars") if isinstance(obj, dict) else None
    for k, bar in enumerate(bars if isinstance(bars, list) else [], 1):
        for name in ("open", "high", "low", "close"):
            value = bar.get(name) if isinstance(bar, dict) else None
            if isinstance(value, _Num) and Decimal(repr(float(value))) != Decimal(value):
                problems.append(_diag(variant, k, name + " repr-körbefordulás", repr(float(value)), str(value)))
    return _bad(problems)


def check_contract(path, variant="?"):
    """CONTRACT: az adatszerződés szerinti betöltés blokkoló hiba nélkül sikerül-e, szintetikus-e és 120 sávos-e. Hibás bemenetnél (olvashatatlan, túl mély) nem értékelhető."""
    try:
        series, problems = _data.load_series(path)
    except (OSError, RecursionError) as exc:
        return _na(f"[{variant}] a fájl az adatszerződés szerint nem tölthető be ({type(exc).__name__}), a szerződés nem értékelhető")
    blocking = [p for p in problems if _data.has_blocking([p])]
    out = []
    for p in blocking:
        index = p["bar_index"]
        where = "fájlszint" if index is None else f"{index + 1}. sáv"
        out.append(f"[{variant}] {where}, {p['field'] or '-'}: {p['reason']}")
    if series is not None and not blocking:
        if not series.synthetic:
            out.append(_diag(variant, 0, "synthetic", series.synthetic, True))
        if len(series.bars) != BARS:
            out.append(_diag(variant, 0, "sávok száma", len(series.bars), BARS))
    return _bad(out)


def read_sidecar(path):
    """(hexa, fájlnév) a sidecarból, vagy (None, ok): a dokumentált formátum szerint, szigorúan."""
    raw, why = read_limited(path, MAX_SIDECAR_BYTES)
    if raw is None:
        return None, f"a sidecar {why}"
    match = SIDECAR_LINE.fullmatch(raw)
    if match is None:
        return None, "a sidecar nem a dokumentált formátumú (<64 kisbetűs hexa>, két szóköz, <fájlnév>, sorvég)"
    return match.group(1).decode("ascii"), match.group(2).decode("ascii")


def check_hash(raw, recorded, variant="?", file_name=None, sidecar_name=None):
    """HASH: FÁJL–SIDECAR BÁJTAZONOSSÁG — a fájl SHA-256-a egyezik-e a rögzített értékkel (és a sidecar fájlnévmezője az ellenőrzött fájl nevével). A forgatókönyvet nem vizsgálja."""
    if recorded is None:
        return _na(f"[{variant}] nincs rögzített hash (--sha256 vagy --sha256-file szükséges), a bájtazonosság nem értékelhető")
    if not isinstance(recorded, str) or HEX64.fullmatch(recorded) is None:
        return _na(f"[{variant}] a rögzített hash nem 64 kisbetűs hexa jegy, a bájtazonosság nem értékelhető")
    problems = []
    if sidecar_name is not None and file_name is not None and sidecar_name != file_name:
        problems.append(f"[{variant}] a sidecar másik fájlhoz tartozik: sidecar fájlnév {sidecar_name!r}, az ellenőrzött fájl neve {file_name!r}")
    actual = hashlib.sha256(raw).hexdigest()
    if actual != recorded:
        problems.append(f"[{variant}] a fájl SHA-256-a: kapott {actual}, várt (rögzített) {recorded}")
    return _bad(problems)


def check_file(path, variant, recorded_sha=None, sidecar_path=None):
    """Mind a négy ellenőrzés, külön: {'contract', 'formula', 'serialization', 'hash'} -> Result (lista + state). A fájlt csak olvassa, nem javítja. Kezeletlen kivétel nélkül."""
    if variant not in IDS:
        raise ValueError("ismeretlen változat")
    if recorded_sha is not None and sidecar_path is not None:
        raise ValueError("vagy a rögzített hash, vagy a sidecar adható meg")
    raw, why = read_limited(path, MAX_BYTES)
    if raw is None:
        reason = f"[{variant}] a fájl {why}: {path}"
        return {name: _na(reason) for name in NAMES}
    sidecar_name = None
    if sidecar_path is not None:
        recorded_sha, second = read_sidecar(sidecar_path)
        if recorded_sha is None:
            hash_result = _na(f"[{variant}] {second}, a bájtazonosság nem értékelhető")
        else:
            sidecar_name = second
            hash_result = None
    else:
        hash_result = None
    if hash_result is None:
        hash_result = check_hash(raw, recorded_sha, variant, Path(path).name, sidecar_name)
    return {"contract": check_contract(path, variant), "formula": check_formula(raw, variant), "serialization": check_serialization(raw, variant), "hash": hash_result}


def exit_code(results):
    if any(r.state == BAD for r in results.values()):
        return 1
    return 2 if any(r.state == NA for r in results.values()) else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="SYN-BLIND-001 független adatellenőr (csak olvas)")
    parser.add_argument("--variant", choices=sorted(IDS), required=True)
    parser.add_argument("--file", required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--sha256-file")
    group.add_argument("--sha256")
    args = parser.parse_args(argv)
    results = check_file(args.file, args.variant, recorded_sha=args.sha256, sidecar_path=args.sha256_file)
    for name in NAMES:
        result = results[name]
        suffix = f" ({len(result)} hiba)" if result.state == BAD else ""
        print(f"{name.upper():14s} {result.state.upper()}{suffix}")
        for problem in result[:SHOWN]:
            print("  - " + problem)
        if len(result) > SHOWN:
            print(f"  … és még {len(result) - SHOWN} további diagnózis kihagyva (összesen {len(result)}, megjelenítve {SHOWN})")
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
