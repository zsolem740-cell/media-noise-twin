"""Hírgyűjtés, offline feldolgozó: mentett bemeneti fájlokból (capture JSON) TSV, JSONL-hiánylista és eredetjegyzék.

Csak helyi fájlokat olvas. Hálózatot, szolgáltatót, kulcsot és környezeti beállítást nem használ, külső eszközhöz (Firecrawl, RSS, Perplexity, Composio) nem kapcsolódik.
Kizárólag a results/ mappába ír (git nem követi). Nem találgat: hiányzó adatot nem pótol, az URL-t nem írja át, hibás típust nem alakít szöveggé.
A szabályok, az értékkészletek és a kimeneti formátumok: docs/NEWSINGEST.md.

  python -m validation.hu_pilot.newsingest --input-dir MAPPA [--out-dir MAPPA]
"""
import argparse
import csv
import datetime
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

from .paths import IsolationError, check_write, inside, load_config, results_dir

SCHEMA = 1
OUT_SUBDIR = "newsingest"
FILES = {"tsv": "news.tsv", "problems": "problems.jsonl", "provenance": "provenance.jsonl", "manifest": "manifest.json"}
COLUMNS = ("url", "title", "published_at", "source", "title_source", "date_source", "fetched_at", "status")
PROBLEM_KEYS = ("url", "field", "reason", "source", "input_file", "record_index")
PROVENANCE_KEYS = ("url", "input_file", "record_index")

# Rögzített értékkészletek (docs/NEWSINGEST.md ugyanezeket sorolja fel; a teszt egyezésüket őrzi).
TITLE_SOURCES = ("rss", "page", "manual", "unknown", "missing")
DATE_SOURCES = ("rss", "page", "manual", "unknown", "missing")
STATUSES = ("ok", "incomplete")
REASONS = ("missing", "invalid_type", "invalid_url", "invalid_date", "missing_timezone", "control_character", "too_long", "unknown_value",
           "source_contradiction", "status_mismatch", "unknown_field", "duplicate_url", "invalid_record", "invalid_json", "invalid_structure", "invalid_file")
FILE_LEVEL_REASONS = ("invalid_json", "invalid_structure", "invalid_file")
TOP_KEYS = ("schema", "synthetic", "capture_id", "_note", "source", "fetched_at", "records", "links")

MAX_TITLE = 500
MAX_SOURCE = 200
MAX_URL = 2048
_FIELD_RANK = {name: i for i, name in enumerate(COLUMNS)}
_FIELD_PROBLEMS = {"title", "published_at", "source", "fetched_at", "title_source", "date_source"}       # ezek hibája `incomplete` státuszt ad
_TEXT_BREAKS = dict.fromkeys(map(ord, "\t\r\n\x0b\x0c\x1c\x1d\x1e\x85\N{LINE SEPARATOR}\N{PARAGRAPH SEPARATOR}"), " ")                 # tabulátor és minden sortörő karakter szóközzé
_BAD_CATEGORIES = {"Cc", "Cs", "Co", "Cn"}
_JSONL_ESCAPES = {"\N{LINE SEPARATOR}": "\\u2028", "\N{PARAGRAPH SEPARATOR}": "\\u2029", "\x85": "\\u0085", "\x7f": "\\u007f"}

_URL = re.compile(r"(https?)://([^/?#]*)([/?#].*)?", re.I | re.S)
_HOST = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", re.ASCII)
_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})", re.ASCII)
_INSTANT = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.[0-9]{1,9})?(Z|[+-][0-9]{2}:[0-9]{2})?", re.ASCII)


# ---------------------------------------------------------------- mezőellenőrzések (mind (érték, ok) párt ad; ok=None: rendben)

def check_text(value, max_len):
    """Cím vagy forrásnév. None, "" és a csak szóközökből álló érték: `missing`. Nem szöveg: `invalid_type` (nincs str() átalakítás).
    A tabulátor és a sortörő karakterek szóközzé válnak, a szélek levágva; egyéb vezérlőkarakter `control_character`, a hosszhatár túllépése `too_long`.
    Unicode-normalizálás nincs: az ékezetek és idézőjelek változatlanok."""
    if value is None:
        return "", "missing"
    if not isinstance(value, str):
        return "", "invalid_type"
    s = value.translate(_TEXT_BREAKS)
    if any(unicodedata.category(ch) in _BAD_CATEGORIES for ch in s):
        return "", "control_character"
    s = s.strip()
    if not s:
        return "", "missing"
    if len(s) > max_len:
        return "", "too_long"
    return s, None


def check_url(value):
    """None, ha az URL elfogadható; különben az ok. Az URL-t soha nem javítjuk és nem vágjuk meg: a szélén álló szóköz is hiba.
    Elfogadási szabály: szöveg, legfeljebb MAX_URL karakter; nincs benne szóköz-jellegű vagy vezérlő karakter; `http://` vagy `https://` séma (kis- és nagybetű mindegy);
    nem üres hoszt (betű, szám, pont, kötőjel; nem kezdődhet és nem végződhet ponttal vagy kötőjellel; nincs `..`); nincs felhasználónév (`@`); a port, ha van, 1-65535."""
    if value is None or value == "":
        return "missing"
    if not isinstance(value, str):
        return "invalid_type"
    if len(value) > MAX_URL or any(ch.isspace() or unicodedata.category(ch) in _BAD_CATEGORIES for ch in value):
        return "invalid_url"
    m = _URL.fullmatch(value)
    if not m or "@" in m.group(2):
        return "invalid_url"
    host, colon, port = m.group(2).partition(":")
    if not _HOST.fullmatch(host) or ".." in host:
        return "invalid_url"
    if colon and not (port.isascii() and port.isdigit() and 1 <= int(port) <= 65535):
        return "invalid_url"
    return None


def check_date(value, instant_only=False):
    """(érték, ok). Elfogadott alakok (az érték változatlanul marad, szóköz-levágás és átírás nincs):
    `ÉÉÉÉ-HH-NN` (instant_only esetén nem) és `ÉÉÉÉ-HH-NNTÓÓ:PP:MM[.tört]` kötelező időzónával: `Z` vagy `±ÓÓ:PP` (nagy T és Z). Létező naptári nap és időpont kell.
    Zóna nélküli időpont: `missing_timezone`. None és a csak szóközökből álló érték: `missing`; nem szöveg: `invalid_type`; minden más hiba: `invalid_date`."""
    if value is None:
        return "", "missing"
    if not isinstance(value, str):
        return "", "invalid_type"
    if not value.strip():
        return "", "missing"
    m = _DATE.fullmatch(value)
    if m and not instant_only:
        try:
            datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return "", "invalid_date"
        return value, None
    m = _INSTANT.fullmatch(value)
    if not m:
        return "", "invalid_date"
    y, mo, d, h, mi, s, tz = m.groups()
    try:
        datetime.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))
        if tz and tz != "Z" and (int(tz[1:3]) > 23 or int(tz[4:6]) > 59):
            return "", "invalid_date"
    except ValueError:
        return "", "invalid_date"
    if tz is None:
        return "", "missing_timezone"
    return value, None


def check_claim(value, allowed):
    """A bemenet eredet-állítása (title_source, date_source). None: nincs állítás. Nem szöveg: `invalid_type`; a készleten kívüli érték: `unknown_value` (nem cseréljük le csendben)."""
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, "invalid_type"
    if value not in allowed:
        return None, "unknown_value"
    return value, None


# ---------------------------------------------------------------- beolvasás

def _no_duplicate_keys(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("ismétlődő kulcs: " + k)
        out[k] = v
    return out


def _reject_constant(name):
    raise ValueError("nem JSON-konstans: " + name)


def _problem(url, field, reason, source, input_file, record_index):
    return {"url": url, "field": field, "reason": reason, "source": source, "input_file": input_file, "record_index": record_index}


def read_input(path, rel):
    """Egy fájl beolvasása. A `rel` a bemeneti könyvtárhoz képesti relatív út (ez lesz az input_file). Sérült vagy hibás szerkezetű fájlból fájlszintű problémát készít, adatot nem ad.
    Szerkezet: JSON objektum; `schema` pontosan az egész 1; `synthetic` logikai; `records` és/vagy `links` lista (legalább az egyik). Ismeretlen felső szintű kulcs: `unknown_field`, de a fájl feldolgozódik."""
    raw = Path(path).read_bytes()
    out = {"input_file": rel, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "data": None, "synthetic": None, "problems": []}
    fail = lambda reason: out["problems"].append(_problem(None, None, reason, None, rel, None))
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError):
        fail("invalid_json")
        return out
    if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != SCHEMA or not isinstance(data.get("synthetic"), bool):
        fail("invalid_structure")
        return out
    if ("records" not in data and "links" not in data) or not isinstance(data.get("records", []), list) or not isinstance(data.get("links", []), list):
        fail("invalid_structure")
        return out
    out["data"], out["synthetic"] = data, data["synthetic"]
    out["problems"] += [_problem(None, k, "unknown_field", None, rel, None) for k in sorted(k for k in data if k not in TOP_KEYS)]
    return out


def discover(input_dir):
    """A bemeneti könyvtár összes `*.json` fájlja (rekurzívan), a relatív POSIX-út kódpont szerinti sorrendjében: [(rel, Path, kívül_van)].
    A könyvtáron kívülre mutató szimbolikus hivatkozást nem olvassuk (kívül_van=True, fájlszintű `invalid_file`)."""
    root = Path(input_dir)
    if not root.is_dir():
        raise NotADirectoryError(f"nem könyvtár: {input_dir}")
    items = [(p.relative_to(root).as_posix(), p, not inside(p, root)) for p in root.rglob("*.json") if p.is_file()]
    return sorted(items, key=lambda x: x[0])


# ---------------------------------------------------------------- feldolgozás

def _resolve_origin(origin_field, has_value, value_reason, claim, claim_reason, add):
    """A mező eredete (rss/page/manual/unknown/missing). Amit a bemenet nem állít, annak az eredete `unknown` (nem adunk igazolt eredetet); hiányzó mezőé `missing`.
    Ellentmondás (érték van, de az állítás `missing`; vagy érték nincs, de az állítás nem `missing`): `source_contradiction`, a kimenet az érték tényleges állapotához igazodik."""
    if claim_reason:
        add(origin_field, claim_reason)
        claim = None
    if has_value:
        if claim == "missing":
            add(origin_field, "source_contradiction")
            return "unknown"
        return claim or "unknown"
    if claim not in (None, "missing") and value_reason == "missing":
        add(origin_field, "source_contradiction")
    return "missing"


def build(inputs):
    """(sorok, eredet, problémák). `inputs`: a read_input eredményei. Feldolgozási sorrend: fájlok az input_file kódpont szerinti sorrendjében, egy fájlban a `records` majd a `links`
    elemei sorszám szerint; a record_index a `records + links` összefűzés indexe (a `links` indexei a `records` után folytatódnak). Azonos URL: az első találat nyer, a többi `duplicate_url`."""
    rows, origin, problems, seen = [], [], [], {}
    for f in sorted(inputs, key=lambda x: x["input_file"]):
        rel = f["input_file"]
        problems += f["problems"]
        data = f["data"]
        if data is None:
            continue
        defaults = {}
        for key, check in (("source", lambda v: check_text(v, MAX_SOURCE)), ("fetched_at", lambda v: check_date(v, True))):
            val, reason = check(data.get(key))
            if reason == "missing":
                val = ""
            elif reason:
                problems.append(_problem(None, key, reason, None, rel, None))
                val = ""
            defaults[key] = val
        records, links = data.get("records", []), data.get("links", [])
        for idx, (kind, item) in enumerate([("record", r) for r in records] + [("link", x) for x in links]):
            note = lambda url, field, reason, source: problems.append(_problem(url, field, reason, source or None, rel, idx))
            if not isinstance(item, dict if kind == "record" else str):
                note(None, None, "invalid_record", defaults["source"])
                continue
            rec = item if kind == "record" else {"url": item}
            local = []
            add = lambda field, reason: local.append((field, reason))

            def optional(key, check, default):
                val, reason = check(rec.get(key))
                if reason == "missing":
                    return default
                if reason:
                    add(key, reason)
                    return ""
                return val

            source = optional("source", lambda v: check_text(v, MAX_SOURCE), defaults["source"])
            src_local, local = local, []
            raw_url = rec.get("url")
            url_reason = check_url(raw_url)
            if url_reason:
                note(raw_url if url_reason == "invalid_url" else None, "url", url_reason, source)
                continue
            if raw_url in seen:
                note(raw_url, "url", "duplicate_url", source)
                continue
            seen[raw_url] = (rel, idx)
            local += src_local
            title, title_reason = check_text(rec.get("title"), MAX_TITLE)
            if title_reason:
                add("title", title_reason)
            published, date_reason = check_date(rec.get("published_at"))
            if date_reason:
                add("published_at", date_reason)
            fetched = optional("fetched_at", lambda v: check_date(v, True), defaults["fetched_at"])
            tclaim, tcr = check_claim(rec.get("title_source"), TITLE_SOURCES)
            dclaim, dcr = check_claim(rec.get("date_source"), DATE_SOURCES)
            title_source = _resolve_origin("title_source", bool(title), title_reason, tclaim, tcr, add)
            date_source = _resolve_origin("date_source", bool(published), date_reason, dclaim, dcr, add)
            status = "ok" if title and published and not any(f_ in _FIELD_PROBLEMS for f_, _r in local) else "incomplete"
            claimed, status_reason = rec.get("status"), None
            if claimed is not None:
                if not isinstance(claimed, str):
                    status_reason = "invalid_type"
                elif claimed not in STATUSES:
                    status_reason = "unknown_value"
                elif claimed != status:
                    status_reason = "status_mismatch"
            if status_reason:
                add("status", status_reason)
            for key in sorted(k for k in rec if k not in COLUMNS):
                add(key, "unknown_field")
            for field, reason in local:
                note(raw_url, field, reason, source)
            rows.append({"url": raw_url, "title": title, "published_at": published, "source": source, "title_source": title_source, "date_source": date_source,
                         "fetched_at": fetched, "status": status})
            origin.append({"url": raw_url, "input_file": rel, "record_index": idx})
    problems.sort(key=lambda p: (p["input_file"], -1 if p["record_index"] is None else p["record_index"], _FIELD_RANK.get(p["field"], 100) if p["field"] else -1,
                                 p["field"] or "", p["reason"]))
    return rows, origin, problems


# ---------------------------------------------------------------- kimenet

def write_tsv(path, rows):
    """Tabulátoros szöveg: csv.DictWriter, UTF-8, newline="", elválasztó tabulátor, sorvég "\\n", idézés a csv modulra bízva (QUOTE_MINIMAL). Csak szöveg kerülhet bele."""
    for r in rows:
        for k, v in r.items():
            if not isinstance(v, str):
                raise TypeError(f"a TSV-be csak szöveg kerülhet ({k})")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter="\t", quotechar='"', quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def dumps_line(obj):
    """Egysoros JSON: a kulcsok sorrendje a beszúrásé, az ékezetek megmaradnak; a sortörőként kezelt karakterek (U+2028, U+2029, U+0085) \\u-escape-pel."""
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    for ch, esc in _JSONL_ESCAPES.items():
        s = s.replace(ch, esc)
    return s


def write_jsonl(path, items):
    """Soronként egy JSON objektum, "\\n" sorvéggel. Üres lista: nulla bájtos fájl (a korábbi tartalmat mindig felülírja)."""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        for it in items:
            fh.write(dumps_line(it) + "\n")


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(input_dir, out_dir, rdir):
    """A teljes feldolgozás: beolvasás, építés, írás a results/ alá (check_write). A négy kimeneti fájlt minden futás felülírja. Visszaadja az összegzést."""
    out_dir = check_write(out_dir, rdir)
    root = Path(input_dir).resolve()
    if inside(out_dir, root) or inside(root, out_dir):
        raise ValueError("a bemeneti és a kimeneti könyvtár nem lehet egymásban")
    inputs = []
    for rel, p, outside in discover(root):
        if outside:
            inputs.append({"input_file": rel, "sha256": None, "bytes": None, "data": None, "synthetic": None, "problems": [_problem(None, None, "invalid_file", None, rel, None)]})
        else:
            inputs.append(read_input(p, rel))
    rows, origin, problems = build(inputs)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {k: check_write(out_dir / v, rdir) for k, v in FILES.items()}
    write_tsv(paths["tsv"], rows)
    write_jsonl(paths["problems"], [{k: p[k] for k in PROBLEM_KEYS} for p in problems])
    write_jsonl(paths["provenance"], [{k: o[k] for k in PROVENANCE_KEYS} for o in origin])
    file_errors = sorted({p["input_file"] for p in problems if p["reason"] in FILE_LEVEL_REASONS})
    by_reason = {r: sum(1 for p in problems if p["reason"] == r) for r in REASONS}
    manifest = {
        "schema": SCHEMA, "module": "newsingest",
        "inputs": [{"input_file": i["input_file"], "sha256": i["sha256"], "bytes": i["bytes"], "synthetic": i["synthetic"],
                    "status": "error" if i["input_file"] in file_errors else "ok"} for i in sorted(inputs, key=lambda x: x["input_file"])],
        "contains_synthetic": any(i["synthetic"] is True for i in inputs),
        "outputs": {FILES[k]: _sha(paths[k]) for k in ("tsv", "problems", "provenance")},
        "counts": {"rows": len(rows), "problems": len(problems), "by_reason": by_reason, "file_errors": len(file_errors)},
    }
    paths["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8", newline="")
    return {"out_dir": out_dir.as_posix(), "rows": len(rows), "problems": len(problems), "file_errors": file_errors, "contains_synthetic": manifest["contains_synthetic"],
            "status": "completed_with_file_errors" if file_errors else "completed", "network_used": False}


def main(argv, base=None):
    """Kilépési kód: 0 lefutott, nincs fájlszintű hiba (a rekordszintű problémák a problems.jsonl-ben vannak); 1 legalább egy bemeneti fájl sérült vagy hibás szerkezetű volt
    (a futás nem teljes siker); 2 hibás használat, nem létező bemeneti könyvtár, az eredménymappán kívüli kimenet vagy egymásba ágyazott könyvtárak."""
    ap = argparse.ArgumentParser(prog="newsingest", description=__doc__.splitlines()[0])
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--out-dir", default=None)
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2
    cfg = load_config()
    rdir = results_dir(cfg, base)
    out_dir = Path(args.out_dir) if args.out_dir else rdir / OUT_SUBDIR
    try:
        summary = run(args.input_dir, out_dir, rdir)
    except (IsolationError, NotADirectoryError, ValueError) as e:
        print(f"HIBA: {e}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 1 if summary["file_errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
