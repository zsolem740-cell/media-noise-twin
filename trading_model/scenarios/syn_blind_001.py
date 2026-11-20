"""SYN-BLIND-001: teljesen szintetikus, előre rögzített történet generátora (az 1. lépés, a rekord előtt). Nem piaci adat.

Csak a Python standard könyvtárát használja; hálózatot, szolgáltatót, kulcsot és a szimulátort nem. A történet 120 napi sáv, hat szakasz; a képletek a
docs/SYN_BLIND_001_TERV.md-ben vannak. Nincs véletlenszám: a zaj és a kanócok egész számos képletek, így a kimenet bájtra azonos minden Python-verzión.

Kerekítés: a generátor SAJÁT, rögzített Decimal-kontextust használ (prec=34, ROUND_HALF_EVEN, Inexact csapda). Az egyetlen kerekítés az explicit
`quantize(0.01)` egy külön, csapdamentes helyi kontextusban: ez ADAT-ELŐÁLLÍTÁSI kerekítés (az ár 2 tizedes), és el van különítve a szimulátor kerekítés nélküli
elszámolási szerződésétől.

Parancssor: `--variant base|alt --out KÖNYVTÁR` (kimenet csak a tároló MUNKAFÁJÁN KÍVÜLI könyvtárba, meglévő fájlt nem ír felül), `--hash-check` (H1: azonos bájtok),
`--check-file FÁJL` (H2: szerializálás).
Kilépési kódok a `--out` esetén: 0 teljes, ellenőrzött kimenet és sikeres takarítás (CSAK ez jogosult későbbi rekord-jóváhagyásra); 2 sikertelen, ennek a hívásnak nem tulajdonítható kimenet vagy maradék
(a már korábban létező ütköző fájlok érintetlenek, és jelentve vannak; kivétel: a doc 8. szakaszában nevesített, `os.open` és nyilvántartás közti szűk ablak); 3 hiányos közzététel, idegen csere a VÉGLEGES néven vagy bizonytalan végleges állapot (felsorolva); 4 a végleges fájlpár teljes és ellenőrzött, de ideiglenes maradék van (idegen ideiglenes név a sikeres közzététel után is ide tartozik). A hash-sor csak a 0-s kódnál kerül a standard kimenetre.
"""
import argparse
import datetime
import decimal
import hashlib
import json
import os
import secrets
import stat
import sys
from decimal import Decimal
from pathlib import Path

SYMBOL = "SYN-BLIND-001"
TIMEFRAME = "1d"
SCHEMA = 1
VARIANTS = ("base", "alt")
CAPTURE_IDS = {"base": "SYN-BLIND-001-v1", "alt": "SYN-BLIND-001-ALT-v1"}
FILE_NAMES = {"base": "syn_blind_001_v1.json", "alt": "syn_blind_001_v1_alt.json"}
BARS = 120
FIRST_ALT_BAR = 51                     # az alternatív folytatás első sávja (az 1-50. sáv azonos)
T0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
START_PRICE = Decimal("100.00")
VOLUME = 1000000
CENT = Decimal("0.01")
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
NOTE = "SYNTHETIC PRE-REGISTERED SCENARIO SYN-BLIND-001; NOT MARKET DATA."
REPO_ROOT = Path(__file__).resolve().parents[2]

# A szakaszok (csak az értékelő számára: ez NEM kerül a capture-be, a stratégia nem látja).
STAGES = (
    ("S1_nyugodt_indulas", 1, 20),
    ("S2_lassu_emelkedes", 21, 45),
    ("S3_hamis_kitores", 46, 55),
    ("S4_hirtelen_eses", 56, 60),
    ("S5_oldalazas", 61, 85),
    ("S6_felepules", 86, 120),
)
_STAGE4_MOVES = {56: "-0.0100", 57: "-0.0100", 58: "-0.0050", 59: "-0.0050", 60: "-0.0050"}


class OutputError(Exception):
    """A kiírás sikertelen. Mezők (mind (útvonal, ok) párok listája):
      leftovers   — a hívásnak tulajdonítható, el nem távolított maradék (ideiglenes fájl, amelyet nem sikerült törölni, vagy amelynek az állapota bizonytalan);
      published   — a hívás KÖZZÉTETT végleges fájljai: soha nem görgetjük vissza őket; a kimenet hiányos, NEM befagyasztott;
      foreign     — idegen vagy lecserélt fájl (végleges vagy ideiglenes néven), érintetlenül hagyva, vagy bizonytalan állapot;
      preexisting — a hívás előtt vagy közben már létező, ütköző végleges fájl, érintetlenül hagyva."""

    def __init__(self, message, leftovers=(), published=(), foreign=(), preexisting=()):
        super().__init__(message)
        self.leftovers = list(leftovers)
        self.published = list(published)
        self.foreign = list(foreign)
        self.preexisting = list(preexisting)


class OutputPathError(OutputError):
    """A kimeneti útvonal nem engedélyezett (munkafán belüli, vagy meglévő fájlt írna felül)."""


def exact_context():
    """A generátor rögzített, kerekítés nélküli kontextusa: ha egy művelet nem pontos, hiba (Inexact csapda)."""
    return decimal.Context(prec=34, rounding=decimal.ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                           traps=[decimal.InvalidOperation, decimal.DivisionByZero, decimal.Overflow, decimal.Inexact])


def rounding_context():
    """Csak az explicit quantize-hoz: ugyanaz, de az Inexact csapda nélkül (a kerekítés itt szándékos)."""
    return decimal.Context(prec=34, rounding=decimal.ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                           traps=[decimal.InvalidOperation, decimal.DivisionByZero, decimal.Overflow])


def _round(value, mode):
    with decimal.localcontext(rounding_context()):
        return value.quantize(CENT, rounding=mode)


def noise(k):
    """Egész számos zaj: ((7k mod 11) - 5) * 0,0004. Egy 11 sávos periódus összege 0."""
    with decimal.localcontext(exact_context()):
        return Decimal(((7 * k) % 11) - 5) * Decimal("0.0004")


def wick_up(k):
    with decimal.localcontext(exact_context()):
        return Decimal(((3 * k) % 7) + 1) * Decimal("0.0005")


def wick_down(k):
    with decimal.localcontext(exact_context()):
        return Decimal(((5 * k) % 7) + 1) * Decimal("0.0005")


def bar_spec(k, variant):
    """(alap-elmozdulás `base`, nyitási rés `gap`, zaj-jelző) a k. sávra. `base` a sávon belüli (open -> close) elmozdulás alapja, `gap` a nyitás eltérése az előző zárástól."""
    if variant not in VARIANTS:
        raise ValueError("ismeretlen változat")
    if not 1 <= k <= BARS:
        raise ValueError("a sáv sorszáma 1 és 120 közötti")
    zero = Decimal("0")
    if variant == "alt" and k >= FIRST_ALT_BAR:
        return Decimal("0.0040"), zero, 1
    if k <= 20:
        return zero, zero, 1
    if k <= 45:
        return Decimal("0.0030"), zero, 1
    if k <= 48:
        return Decimal("0.0250"), zero, 0
    if k <= 55:
        return Decimal("-0.0110"), zero, 0
    if k <= 60:
        return Decimal(_STAGE4_MOVES[k]), (Decimal("-0.1200") if k == 56 else zero), 0
    if k <= 85:
        return (Decimal("0.0080") if k % 3 == 0 else Decimal("-0.0040")), zero, 1
    if k <= 105:
        return Decimal("0.0050"), zero, 1
    return zero, zero, 1


def timestamp(k):
    return (T0 + datetime.timedelta(days=k)).strftime(TIME_FORMAT)


def build_bars(variant):
    """A 120 sáv (szótárak, az árak Decimal-ok, 2 tizedessel)."""
    if variant not in VARIANTS:
        raise ValueError("ismeretlen változat")
    rows = []
    prev_close = None
    with decimal.localcontext(exact_context()):
        for k in range(1, BARS + 1):
            base, gap, use_noise = bar_spec(k, variant)
            if k == 1:
                open_ = START_PRICE
            elif gap != 0:
                open_ = _round(prev_close * (1 + gap), decimal.ROUND_HALF_EVEN)
            else:
                open_ = prev_close
            move = base + (noise(k) if use_noise else Decimal(0))
            close = _round(open_ * (1 + move), decimal.ROUND_HALF_EVEN)
            high = _round(max(open_, close) * (1 + wick_up(k)), decimal.ROUND_CEILING)
            low = _round(min(open_, close) * (1 - wick_down(k)), decimal.ROUND_FLOOR)
            rows.append({"timestamp": timestamp(k), "open": open_, "high": high, "low": low, "close": close, "volume": VOLUME, "available_at": timestamp(k)})
            prev_close = close
    return rows


def build_capture(variant):
    return {"_note": NOTE, "bars": build_bars(variant), "capture_id": CAPTURE_IDS[variant], "schema": SCHEMA, "symbol": SYMBOL, "synthetic": True, "timeframe": TIMEFRAME}


def _enc(value):
    """Kanonikus JSON-szöveg: rendezett kulcsok, nincs felesleges szóköz, a Decimal pontos tizedes szövege, ASCII."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("nem véges szám")
        return format(value, "f")
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_enc(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(str(key), ensure_ascii=True) + ":" + _enc(value[key]) for key in sorted(value)) + "}"
    raise TypeError("nem szerializálható típus")


def canonical_bytes(capture):
    return _enc(capture).encode("ascii")


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def reproducibility_check(variant):
    """H1: két egymás utáni generálás bájtra azonos-e. (egyezik, az első hash, a második hash)"""
    first, second = canonical_bytes(build_capture(variant)), canonical_bytes(build_capture(variant))
    return first == second, sha256_hex(first), sha256_hex(second)


def _no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("ismétlődő kulcs: " + key)
        out[key] = value
    return out


def _reject_constant(name):
    raise ValueError("nem JSON-konstans: " + name)


def check_serialization(path):
    """H2 egy fájlra: lásd serialization_problems."""
    return serialization_problems(Path(path).read_bytes())


def serialization_problems(raw):
    """H2: a bájtok újrabetöltése és kanonikus újraszerializálása bájtra azonos-e, és az ár `repr`-körbefordulása pontos-e. Hibák listája (üres = rendben)."""
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return ["a fájl nem ASCII"]
    try:
        obj = json.loads(text, parse_float=Decimal, parse_int=int, object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant)
    except ValueError as exc:
        return [f"nem érvényes JSON: {exc}"]
    problems = []
    try:
        again = _enc(obj).encode("ascii")
    except (TypeError, ValueError) as exc:
        return [f"nem újraszerializálható: {exc}"]
    if again != raw:
        problems.append("a kanonikus újraszerializálás eltér a fájltól")
    if sha256_hex(again) != sha256_hex(raw):
        problems.append("a hash eltér az újraszerializálás után")
    bars = obj.get("bars") if isinstance(obj, dict) else None
    if not isinstance(bars, list):
        return problems + ["hiányzó vagy érvénytelen bars"]
    for index, bar in enumerate(bars, 1):
        for field in ("open", "high", "low", "close"):
            value = bar.get(field) if isinstance(bar, dict) else None
            if not isinstance(value, Decimal):
                problems.append(f"{index}. sáv, {field}: nem tizedes szám")
            elif Decimal(repr(float(value))) != value:
                problems.append(f"{index}. sáv, {field}: a repr-körbefordulás nem pontos")
    return problems


def resolve_out_dir(out):
    """A kimeneti könyvtár FELOLDOTT (szimbolikus linkeken át feloldott) útvonala; a tároló munkafáján belülit megtagadja."""
    resolved = Path(os.path.realpath(os.fspath(out)))
    root = REPO_ROOT.resolve()
    if resolved == root or root in resolved.parents:
        raise OutputPathError(f"a kimenet a tároló munkafáján belülre esne: {resolved}")
    return resolved


class GenerationError(OutputError):
    """A generálás, a kiírás vagy a kiírás utáni ellenőrzés hibás: nem számít sikeresnek."""


class Written(tuple):
    """(data_path, sha_path, digest) — plusz `leftovers`: a SIKERES, teljes kiírás után megmaradt ideiglenes maradék (útvonal, ok); üres = teljes siker (0), nem üres = 4."""
    leftovers = ()


def _tmp_token():
    return secrets.token_hex(8)


class _Tmp:
    """Ideiglenes fájl. A nyitott fájlleíró a takarítás végéig megmarad: amíg nyitva van, az inode nem osztható ki újra, így az `fstat(fd)` és az `lstat(út)` összevetése pontos azonosságot ad."""

    def __init__(self, path, fd):
        self.path, self.fd = path, fd


def _close_quietly(tmp):
    fd, tmp.fd = tmp.fd, None
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass


def _write_all(fd, content):
    view = memoryview(content)
    while view:
        view = view[os.write(fd, view):]


def _fd_holds(tmp, content):
    """A leíró inode-jának teljes tartalma pontosan `content`-e (útvonal nélkül, a saját inode-ból olvasva)."""
    return os.pread(tmp.fd, len(content) + 1, 0) == content


def _create_exclusive(directory, name, content, tmps):
    """Egyedi nevű ideiglenes fájl KIZÁRÓ létrehozása (O_CREAT|O_EXCL), a leíró nyitva marad és azonnal nyilvántartásba kerül. Létező névnél újra próbál, idegen fájlt soha nem érint."""
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    for _ in range(16):
        path = directory / f".{name}.{_tmp_token()}.tmp"
        try:
            fd = os.open(path, flags, 0o666)
        except FileExistsError:
            continue
        tmp = _Tmp(path, fd)
        tmps.append(tmp)
        _write_all(fd, content)
        return tmp
    raise GenerationError("nem sikerült egyedi ideiglenes fájlnevet találni")


def _classify(tmp, path):
    """A `path` állapota az ideiglenes fájl inode-jához képest: "ours" (ugyanaz az inode), "foreign" (más fájl van ott), "absent", "unknown" (nem állapítható meg). Csak olvas."""
    try:
        theirs = os.lstat(path)
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "unknown"
    try:
        mine = os.fstat(tmp.fd)
    except (OSError, TypeError):
        return "unknown"
    return "ours" if stat.S_ISREG(theirs.st_mode) and os.path.samestat(mine, theirs) else "foreign"


def _remove_tmp(tmp, leftovers, foreign):
    """Az ideiglenes NEVET csak akkor törli, ha a fájlleíróval összevetve még a mi inode-unk; idegen fájlt SOHA (jelenti). Maradék rés: az `lstat` és az `unlink` között egy másik folyamat
    cserélhet (POSIX-on nincs feltételes törlés); ezt dokumentáltuk, nem védjük. A törlési hiba nem dobódik tovább."""
    state = _classify(tmp, tmp.path)
    if state == "absent":
        return
    if state == "foreign":
        foreign.append((str(tmp.path), "idegen vagy lecserélt fájl az ideiglenes néven, érintetlenül hagytam"))
    elif state == "unknown":
        leftovers.append((str(tmp.path), "az állapot nem állapítható meg; nem töröltem"))
    else:
        try:
            os.unlink(tmp.path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            leftovers.append((str(tmp.path), f"nem törölhető: {exc.strerror or exc}"))


def _failure_report(attempted, tmps, preexisting, linked=()):
    """Hibaági jelentés és takarítás (soha nem dob): a közzétett végleges fájlok KÖZZÉTETTKÉNT jelentve (nem töröljük), az idegenek érintetlenül; csak az ideiglenes neveket takarítjuk."""
    published, foreign, leftovers = [], [], []
    already = {path for path, _why in preexisting}
    for final, tmp in attempted:
        state = _classify(tmp, final)
        if state == "ours":
            published.append((str(final), "közzétett végleges fájl, NEM görgetve vissza; a kimenet hiányos, nem befagyasztott"))
        elif state == "foreign" and str(final) not in already:
            foreign.append((str(final), "idegen vagy lecserélt fájl a végleges néven, érintetlenül hagytam"))
        elif state == "unknown":
            foreign.append((str(final), "az állapot nem állapítható meg (bizonytalan végleges állapot)"))
        elif state == "absent" and str(final) in linked:
            foreign.append((str(final), "a közzétett név a link után eltűnt (valaki eltávolította?): bizonytalan végleges állapot"))
    for tmp in tmps:
        _remove_tmp(tmp, leftovers, foreign)
    return published, foreign, leftovers


def write_outputs(variant, out):
    """A generált adat és a .sha256 fájl kiírása a tárolón kívüli könyvtárba. Támogatott határ: PRIVÁT, nem ellenséges kimeneti könyvtár; védelmet azonos felhasználó kódjának
    egyidejű útvonalcseréje ellen nem állítunk.
    Protokoll: (1) előzetes létezés-ellenőrzés (ütköző, már létező végleges fájl: érintetlenül hagyva, jelentve); (2) EGYEDI nevű ideiglenes fájlok kizáró létrehozása, a fájlleírók a takarítás végéig nyitva;
    (3) ellenőrzés a SAJÁT inode-ból (H2, bájt, hash); (4) KÖZZÉTÉTELI SORREND (nem atomi páros közzététel): ELŐBB a sidecar, UTOLJÁRA az adatfájl, `os.link`-kel (létező célra FileExistsError: nem ír felül),
    mindegyik után azonosság-ellenőrzés (`fstat(fd)` = `lstat(végleges)`); (5) az ideiglenes nevek törlése, csak ha a fájlleíróval összevetve a miénk.
    A közzétett végleges fájlt SOHA nem töröljük, nem írjuk felül, nem csonkítjuk és nem nevezzük át; hibánál hiányos kimenet maradhat, amelyet jelentünk (published), és nem befagyasztott.
    Hibánál OutputError (leftovers, published, foreign, preexisting). Sikernél Written (leftovers = megmaradt ideiglenes maradék). Az eredeti kivétel megmarad; a takarítás hibája nem fedi el.
    KeyboardInterrupt/SystemExit takarítás után újradobódik, az ismert közzétett kimenet a kivétel jegyzetében."""
    out_dir = resolve_out_dir(out)
    name = FILE_NAMES[variant]
    data_path, sha_path = out_dir / name, out_dir / (name + ".sha256")
    existing = [(str(path), "a hívás előtt már létezett, nem írtam felül, érintetlen") for path in (sha_path, data_path) if os.path.lexists(path)]
    if existing:
        raise OutputPathError("a kimenet már létezik, nem írom felül: " + ", ".join(path for path, _why in existing), preexisting=existing)
    data = canonical_bytes(build_capture(variant))
    digest = sha256_hex(data)
    sha_text = f"{digest}  {name}\n".encode("ascii")
    out_dir.mkdir(parents=True, exist_ok=True)
    tmps, attempted, preexisting, linked = [], [], [], set()
    try:
        try:
            tmp_data = _create_exclusive(out_dir, name, data, tmps)
            tmp_sha = _create_exclusive(out_dir, name + ".sha256", sha_text, tmps)
            back = os.pread(tmp_data.fd, len(data) + 1, 0)
            problems = serialization_problems(back)
            if problems or back != data or sha256_hex(back) != digest or not _fd_holds(tmp_sha, sha_text):
                raise GenerationError("a kiírt állomány ellenőrzése sikertelen: " + "; ".join(problems or ["a visszaolvasott bájtok eltérnek"]))
            order = ((tmp_sha, sha_path, sha_text), (tmp_data, data_path, data))
            for tmp, final, content in order:
                attempted.append((final, tmp))           # a link ELŐTT: megszakításnál is pontosan osztályozható
                try:
                    os.link(tmp.path, final)
                except FileExistsError:
                    preexisting.append((str(final), "közben létrejött vagy már létező fájl, nem írtam felül, érintetlen"))
                    raise OutputPathError(f"a kimenet közben létrejött, nem írom felül: {final}")
                except OSError as exc:
                    raise GenerationError(f"a végleges név létrehozása sikertelen (az os.link-nek, azaz hard-link támogatásnak kell lennie a célfájlrendszeren): {exc}") from exc
                linked.add(str(final))
                state = _classify(tmp, final)
                if state != "ours":
                    raise GenerationError(f"a közzétett végleges név utólagos azonosság-ellenőrzése sikertelen ({state}): {final}")
                if not _fd_holds(tmp, content):
                    raise GenerationError(f"a közzétett fájl tartalma a link után eltér a kiírttól: {final}")
            for tmp, final, content in order:                    # a pár vége: MINDKÉT végleges név újraellenőrzése, mielőtt teljesnek (0) minősülne
                state = _classify(tmp, final)
                if state != "ours" or not _fd_holds(tmp, content):
                    raise GenerationError(f"a végleges pár végső ellenőrzése sikertelen ({state if state != 'ours' else 'tartalom eltér'}): {final}")
            leftovers, foreign = [], []                          # sikerági takarítás: ugyanazon a kivételkezelésen belül (megszakításnál is jelent)
            for tmp in tmps:
                _remove_tmp(tmp, leftovers, foreign)
        except BaseException as exc:
            published, foreign, leftovers = _failure_report(attempted, tmps, preexisting, linked)
            if isinstance(exc, OutputError):
                known = {path for path, _why in exc.preexisting}
                exc.leftovers, exc.published, exc.foreign = leftovers, published, foreign
                exc.preexisting = list(exc.preexisting) + [item for item in preexisting if item[0] not in known]
                raise
            if isinstance(exc, Exception):
                raise GenerationError(f"a kiírás sikertelen: {exc}", leftovers, published, foreign, preexisting) from exc
            parts = [f"{path} ({why})" for path, why in published + foreign + leftovers]
            if parts and hasattr(exc, "add_note"):
                exc.add_note("ismert kimeneti állapot (hiányos, nem befagyasztott): " + "; ".join(parts))
            raise
    finally:
        for tmp in tmps:
            _close_quietly(tmp)
    written = Written((data_path, sha_path, digest))
    written.leftovers = leftovers + foreign
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description="SYN-BLIND-001 generátor (szintetikus; kimenet csak a tárolón kívülre)")
    parser.add_argument("--variant", choices=VARIANTS, required=True)
    parser.add_argument("--out", help="tárolón kívüli kimeneti könyvtár")
    parser.add_argument("--hash-check", action="store_true", help="H1: kétszeri generálás bájtazonossága")
    parser.add_argument("--check-file", help="H2: egy kiírt fájl szerializálási ellenőrzése")
    args = parser.parse_args(argv)
    status = 0
    if args.hash_check:
        same, first, second = reproducibility_check(args.variant)
        print(f"H1 változat={args.variant} bájtazonos={'igen' if same else 'NEM'} sha256={first}")
        status = status or (0 if same and first == second else 1)
    if args.check_file:
        problems = check_serialization(args.check_file)
        print(f"H2 fájl={args.check_file} {'RENDBEN' if not problems else 'HIBA'}")
        for problem in problems:
            print("  - " + problem)
        status = status or (1 if problems else 0)
    if args.out:
        try:
            written = write_outputs(args.variant, args.out)
        except (KeyboardInterrupt, SystemExit) as exc:
            for note in getattr(exc, "__notes__", []):
                print("FIGYELEM: " + note, file=sys.stderr)
            raise
        except (OutputError, OSError) as exc:
            attrs = {name: list(getattr(exc, name, [])) for name in ("published", "foreign", "leftovers", "preexisting")}
            print(f"HIBA: sikertelen kiírás, NEM sikeres, NEM befagyasztott: {exc}", file=sys.stderr)
            titles = (("published", "közzétett, NEM visszagörgetett végleges fájl (a kimenet hiányos)"), ("foreign", "idegen, lecserélt vagy bizonytalan állapotú fájl (érintetlen)"),
                      ("leftovers", "megmaradt ideiglenes vagy azonosíthatatlan fájl"))
            if attrs["published"] or attrs["foreign"] or attrs["leftovers"]:
                print("FIGYELEM: hiányos, idegen vagy bizonytalan kimeneti állapot, kézzel ellenőrizendő (kilépési kód 3):", file=sys.stderr)
                for key, title in titles:
                    for path, why in attrs[key]:
                        print(f"  - {title}: {path}: {why}", file=sys.stderr)
                for path, why in attrs["preexisting"]:
                    print(f"  - már létező, érintetlenül hagyott fájl: {path}: {why}", file=sys.stderr)
                return 3
            print("Ez a hívás nem hagyott maga után fájlt.", file=sys.stderr)
            for path, why in attrs["preexisting"]:
                print(f"  - már létező, érintetlenül hagyott fájl: {path}: {why}", file=sys.stderr)
            return 2
        data_path, _sha_path, digest = written
        if written.leftovers:
            print("FIGYELEM: a végleges fájlpár teljes és ellenőrzött, de ideiglenes maradék van; NEM jogosult rekord-jóváhagyásra (csak a 0-s kilépési kód az), kilépési kód 4.", file=sys.stderr)
            print(f"  (tájékoztató, nem rekord: {digest}  {data_path})", file=sys.stderr)
            for path, why in written.leftovers:
                print(f"  - {path}: {why}", file=sys.stderr)
            return 4
        if status == 0:
            print(f"{digest}  {data_path}")
        else:
            print("FIGYELEM: a kiírás teljes és ellenőrzött, de a --hash-check/--check-file hibás (kilépési kód 1); a hash-sor nem kerül a standard kimenetre; NEM jogosult rekord-jóváhagyásra (csak a 0-s kilépési kód az).", file=sys.stderr)
            print(f"  (tájékoztató, nem rekord: {digest}  {data_path})", file=sys.stderr)
    if not (args.hash_check or args.check_file or args.out):
        parser.error("legalább egy művelet kell: --out, --hash-check vagy --check-file")
    return status


if __name__ == "__main__":
    sys.exit(main())
