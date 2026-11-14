"""A Webis-Clickbait-17 betöltése: mezőleképezés, ellenőrzés, kizárások. Csak olvas; a fájlok tartalmát nem javítja.

Bemenet: instances.jsonl (a poszt) és truth.jsonl (az annotátorok ítéletei), azonosító szerint összekapcsolva.
A mezőnevek a config.json field_aliases szerint keresődnek (a hivatalos leírásból nem ellenőrizhető mezőneveket a betöltő
nem tételezi fel: hiányzó kötelező mező esetén megáll, és kiírja a ténylegesen talált mezőket)."""
import hashlib
import json
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .isolation import check_read, has_hungarian_chars


class LoadError(Exception):
    pass


@dataclass
class Record:
    id: str
    text: str                       # amit az AI látni fog (a poszt szövege)
    human_mean: float               # a judgments listából újraszámolva
    human_median: float
    judgments: tuple
    n_annotators: int
    file_mean: float | None = None  # a fájlban szereplő érték (összehasonlításhoz)
    file_median: float | None = None
    short_title: bool = False
    disagreement: float = 0.0       # az ítéletek szórása (populációs)
    flags: list = field(default_factory=list)
    truth_class: str | None = None      # a fájlbeli truthClass (többségi annotátori ítélet), az átlagküszöbtől függetlenül
    majority_class: str | None = None   # az ítéletekből újraszámolt többségi osztály (ellenőrzéshez)


def read_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise LoadError(f"{Path(path).name}:{n}: hibás JSON ({e.msg})") from None
    return rows


def _pick(row, names):
    for n in names:
        if n in row:
            return n
    return None


def resolve_fields(inst_row, truth_row, aliases):
    """Melyik tényleges mező felel meg a belső mezőnek; hiányzó kötelező mezőnél LoadError a talált kulcsokkal."""
    m = {"id_i": _pick(inst_row, aliases["id"]), "text": _pick(inst_row, aliases["text"]),
         "id_t": _pick(truth_row, aliases["id"]), "judgments": _pick(truth_row, aliases["judgments"]),
         "file_mean": _pick(truth_row, aliases["file_mean"]), "file_median": _pick(truth_row, aliases["file_median"]),
         "truth_class": _pick(truth_row, aliases.get("truth_class", []))}
    missing = [k for k in ("id_i", "text", "id_t", "judgments") if m[k] is None]
    if missing:
        raise LoadError(f"hiányzó kötelező mező: {', '.join(missing)}. instances mezői: {sorted(inst_row)}; truth mezői: {sorted(truth_row)}")
    return m


def _as_text(v):
    if isinstance(v, list):
        return " ".join(str(x) for x in v).strip()
    return str(v or "").strip()


def _norm(text):
    return re.sub(r"\s+", " ", text.lower()).strip()


def word_count(text):
    return len(re.findall(r"\w+", text, re.UNICODE))


def _valid_judgments(j, cfg):
    if not isinstance(j, (list, tuple)) or not j:
        return False
    tol = cfg["scale_tolerance"]
    return all(isinstance(x, (int, float)) and not isinstance(x, bool) and any(abs(x - s) <= tol for s in cfg["scale_values"]) for x in j)


def load(instances_path, truth_path, cfg, data_dir):
    """Visszaad: (rekordok azonosító szerint rendezve, jelentés). A jelentés minden kizárást és eltérést megszámol."""
    ip, tp = check_read(instances_path, data_dir), check_read(truth_path, data_dir)
    inst, truth = read_jsonl(ip), read_jsonl(tp)
    if not inst or not truth:
        raise LoadError("üres bemeneti fájl")
    f = resolve_fields(inst[0], truth[0], cfg["field_aliases"])
    for opt in ("file_mean", "file_median", "truth_class"):     # a nem kötelező mezőket akkor is megtaláljuk, ha az első sorból hiányoznak
        if f[opt] is None:
            f[opt] = next((n for r in truth for n in [_pick(r, cfg["field_aliases"].get(opt, []))] if n), None)
    by_truth = {}
    for r in truth:
        by_truth.setdefault(str(r.get(f["id_t"])), r)
    rep = {"n_instances": len(inst), "n_truth": len(truth), "fields": f, "instance_keys": sorted({k for r in inst for k in r}),
           "truth_keys": sorted({k for r in truth for k in r}), "missing_truth": 0, "excluded": Counter(), "annotator_counts": Counter(),
           "mean_mismatch": 0, "median_mismatch": 0, "max_mean_diff": 0.0, "max_median_diff": 0.0,
           "class_check_all_valid_rows": {"rows": 0, "mean_threshold_mismatch": 0, "majority_mismatch": 0, "unknown_label": 0}}
    kept, seen_text = [], {}
    for r in sorted(inst, key=lambda x: str(x.get(f["id_i"]))):
        rid = str(r.get(f["id_i"]))
        t = by_truth.get(rid)
        if t is None:
            rep["missing_truth"] += 1
            continue
        text = _as_text(r.get(f["text"]))
        j = t.get(f["judgments"])
        if not text:
            rep["excluded"]["üres szöveg"] += 1
            continue
        if has_hungarian_chars(text):
            rep["excluded"]["magyar-specifikus betű (nem Webis-adat)"] += 1
            continue
        if not _valid_judgments(j, cfg):
            rep["excluded"]["hibás vagy skálán kívüli ítélet"] += 1
            continue
        j = tuple(float(x) for x in j)
        tc = t.get(f["truth_class"]) if f["truth_class"] else None
        up = sum(1 for x in j if x > cfg["scale_upper_cut"])
        lab = cfg["class_labels"]
        majority = lab["positive"] if up > len(j) - up else lab["negative"] if up < len(j) - up else None
        by_mean = lab["positive"] if sum(j) / len(j) >= cfg["clickbait_threshold"] else lab["negative"]
        chk = rep["class_check_all_valid_rows"]          # az ismétlődő szövegű rekordok kizárása előtt: az egész érvényes korpuszra
        chk["rows"] += 1
        if tc is not None and tc not in (lab["positive"], lab["negative"]):
            chk["unknown_label"] += 1
        elif tc is not None:
            chk["mean_threshold_mismatch"] += tc != by_mean
            chk["majority_mismatch"] += majority is not None and tc != majority
        key = _norm(text)
        if key in seen_text:
            rep["excluded"]["ismétlődő szöveg"] += 1
            continue
        seen_text[key] = rid
        mean, median = sum(j) / len(j), statistics.median(j)
        fm = t.get(f["file_mean"]) if f["file_mean"] else None
        fmed = t.get(f["file_median"]) if f["file_median"] else None
        flags = []
        if len(j) != cfg["expected_annotators"]:
            flags.append("annotators_unexpected")
        if isinstance(fm, (int, float)):
            d = abs(fm - mean)
            rep["max_mean_diff"] = max(rep["max_mean_diff"], d)
            if d > cfg["stat_tolerance"]:
                rep["mean_mismatch"] += 1
                flags.append("mean_mismatch")
        if isinstance(fmed, (int, float)):
            d = abs(fmed - median)
            rep["max_median_diff"] = max(rep["max_median_diff"], d)
            if d > cfg["stat_tolerance"]:
                rep["median_mismatch"] += 1
                flags.append("median_mismatch")
        if tc is not None and tc in (lab["positive"], lab["negative"]):
            if tc != by_mean:
                flags.append("class_mean_threshold_mismatch")
            if majority is not None and tc != majority:
                flags.append("class_majority_mismatch")
        rep["annotator_counts"][len(j)] += 1
        short = word_count(text) < cfg["short_title_max_words"]
        kept.append(Record(id=rid, text=text, human_mean=mean, human_median=median, judgments=j, n_annotators=len(j),
                           file_mean=fm if isinstance(fm, (int, float)) else None, file_median=fmed if isinstance(fmed, (int, float)) else None,
                           short_title=short, disagreement=statistics.pstdev(j) if len(j) > 1 else 0.0, flags=flags,
                           truth_class=tc if isinstance(tc, str) else None, majority_class=majority))
    thr, lab = cfg["clickbait_threshold"], cfg["class_labels"]
    with_class = [r for r in kept if r.truth_class in (lab["positive"], lab["negative"])]
    rep.update({"n_kept": len(kept), "n_short_title": sum(r.short_title for r in kept),
                "n_clickbait_at_threshold": sum(r.human_mean >= thr for r in kept),
                "truth_class_available": bool(with_class),
                "truth_class_counts": dict(Counter(r.truth_class for r in kept)),
                "class_vs_mean_threshold": {
                    "mismatch": sum("class_mean_threshold_mismatch" in r.flags for r in kept),
                    "clickbait_below_threshold": sum(r.truth_class == lab["positive"] and r.human_mean < thr for r in with_class),
                    "no_clickbait_at_or_above_threshold": sum(r.truth_class == lab["negative"] and r.human_mean >= thr for r in with_class)},
                "class_vs_majority_mismatch": sum("class_majority_mismatch" in r.flags for r in kept),
                "excluded": dict(rep["excluded"]), "annotator_counts": dict(rep["annotator_counts"])})
    return kept, rep


def verify_archive(path, expected):
    """Egy letöltött archívum MD5-je és mérete az ismert (Zenodo-rekordbeli) értékekkel összevetve."""
    p = Path(path)
    if p.name not in expected:
        raise LoadError(f"ismeretlen archívum: {p.name}")
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    want = expected[p.name]
    return {"name": p.name, "md5_ok": h.hexdigest() == want["md5"], "size_ok": p.stat().st_size == want["size"], "md5": h.hexdigest()}
