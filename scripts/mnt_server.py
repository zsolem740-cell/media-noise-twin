#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Média-Zaj Twin v38 – szerveroldali gyűjtő és elemző (csak Python standard library).

Használat:
  python3 scripts/mnt_server.py              gyűjtés + elemzés; csak érdemi változásnál ír fájlt
  python3 scripts/mnt_server.py --notify     a kimenő riasztások küldése (NTFY_TOPIC titokkal; hiányában csendben kihagyja)
  python3 scripts/mnt_server.py --make-icons PWA-ikonok előállítása
Környezeti változók (tesztelésre): MNT_FIXTURES=<könyvtár> (offline: <forrás-id>.xml, hungaromet_<n>.html),
  MNT_ROOT, MNT_OUTBOX, MNT_FORCE=1, MNT_NOW=<ISO idő>.

ATM = G · S · (1 − V)
  G  gerjesztés: érzelmi töltet (indulatszavak, felkiáltójel, NAGYBETŰ, kérdés-horog)           0..1
  S  szenzáció: kattintásvadász jelleg (csalogató szavak, listás cím, három pont, felsőfok)    0..1
  V  valóságtartalom: ellenőrizhetőség (hivatalos forrás, bizalom, számok/idézet/hivatkozás,
     több független forrás, fizikai mérésekkel való keresztellenőrzés)                          0..1
"""
import hashlib
import html
import json
import math
import os
import re
import struct
import sys
import unicodedata
import zlib
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(os.environ.get("MNT_ROOT") or Path(__file__).resolve().parent.parent)
DATA = ROOT / "data"
MET = DATA / "metrics"
UA = "Mozilla/5.0 (compatible; MediaNoiseTwin/38)"
SCOPE_RANK = {"official": 0, "local": 1, "national": 2, "international": 3}


# ───────────────────────── általános segédek ─────────────────────────
def now():
    v = os.environ.get("MNT_NOW")
    return datetime.fromisoformat(v.replace("Z", "+00:00")) if v else datetime.now(timezone.utc)


def iso(d):
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def jload(p, default=None):
    try:
        return json.loads(Path(p).read_text("utf-8"))
    except Exception:
        return default


def jsave(p, obj, pretty=False):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1 if pretty else None, separators=None if pretty else (",", ":")), "utf-8")
    tmp.replace(p)


def fold(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c)).replace("ß", "ss")


TAG = re.compile(r"<[^>]+>")
WORD = re.compile(r"[a-z0-9]{3,}")


def strip_html(s):
    s = re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", s))).strip()


def parse_date(s):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def hav_km(a, b, c, d):
    p = math.pi / 180
    x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(x))


def pctl(vals, p):
    v = sorted(vals)
    if not v:
        return 0.0
    k = (len(v) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


# ───────────────────────── hírforrások beolvasása ─────────────────────────
def fetch(url, key, timeout=20):
    fx = os.environ.get("MNT_FIXTURES")
    if fx:
        p = Path(fx) / key
        return p.read_bytes() if p.exists() else None
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, text/html;q=0.8, */*;q=0.5"})
    with urlopen(req, timeout=timeout) as r:
        return r.read(3_000_000)


def lname(t):
    return t.rsplit("}", 1)[-1]


def parse_feed(data):
    root = ET.fromstring(data)
    items = []
    for el in root.iter():
        if lname(el.tag) not in ("item", "entry"):
            continue
        d = {}
        for ch in el:
            k = lname(ch.tag)
            if k == "title":
                d["title"] = (ch.text or "").strip()
            elif k == "link":
                if ch.get("href") and ch.get("rel", "alternate") == "alternate":
                    d.setdefault("link", ch.get("href").strip())
                elif ch.text and ch.text.strip():
                    d.setdefault("link", ch.text.strip())
            elif k in ("description", "summary", "content", "encoded"):
                d.setdefault("summary", ch.text or "")
            elif k in ("pubDate", "published", "updated", "date"):
                d.setdefault("date", (ch.text or "").strip())
            elif k == "source":
                d["publisher"] = (ch.text or "").strip()
            elif k in ("guid", "id"):
                d.setdefault("guid", (ch.text or "").strip())
        if d.get("title"):
            items.append(d)
    return items


def clean_title(title, publisher):
    t = title.strip()
    for sep in (" - ", " – ", " | "):
        if sep in t:
            head, tail = t.rsplit(sep, 1)
            if publisher and fold(tail).strip() == fold(publisher).strip():
                return head.strip()
            if not publisher and len(tail) <= 40 and len(head) > 20:
                return head.strip()
    return t


def collect(cfg, errors):
    out = []
    mx = cfg["limits"].get("max_per_feed", 60)
    for f in cfg["feeds"]:
        if f.get("enabled") is False or f["type"] != "rss":
            continue
        try:
            raw = fetch(f["url"], f["id"] + ".xml")
            if raw is None:
                raise RuntimeError("nincs adat")
            items = parse_feed(raw)
        except Exception as e:
            errors[f["id"]] = str(e)[:120]
            continue
        for it in items[:mx]:
            pub = it.get("publisher") or f["name"]
            title = clean_title(it["title"], it.get("publisher"))
            summ = "" if f["id"].startswith("gn_") else strip_html(it.get("summary", ""))[:600]
            d = parse_date(it.get("date"))
            link = it.get("link", "")
            if not re.match(r"^https?://", link, re.I):
                link = ""          # nem megbízható forrás: csak http(s) hivatkozás kerülhet a lapra
            out.append({"title": title, "summary": summ, "link": link, "source": pub, "feed": f["id"], "scope": f["scope"],
                        "lang": f.get("lang", ""), "trust": f.get("trust", 0.5), "official": bool(f.get("official")),
                        "published": iso(d) if d else None})
    return out


def collect_official(cfg, errors, t):
    """HungaroMet: nincs nyilvános RSS/CAP, ezért a szöveges figyelmeztető oldalak tartalmát értelmezi (heurisztika)."""
    state = {"calm": None, "excerpt": "", "checked": False}
    arts = []
    for f in cfg["feeds"]:
        if f["type"] != "official_text" or f.get("enabled") is False:
            continue
        pages = []
        for i, u in enumerate(f["urls"]):
            try:
                raw = fetch(u, f["id"] + "_%d.html" % i)
                if raw:
                    pages.append(strip_html(raw.decode("utf-8", "ignore")))
            except Exception as e:
                errors[f["id"]] = str(e)[:120]
        if not pages:
            errors.setdefault(f["id"], "nincs adat")
            continue
        alert_pages, calm_pages = [], 0
        for text in pages:
            ft = fold(text)
            if any(m in ft for m in f["calm_markers"]):
                calm_pages += 1
            elif re.search(r"(sarga|narancs|piros)\s+(figyelmeztet|riaszt)|veszely", ft):
                alert_pages.append(text)
        src = alert_pages[0] if alert_pages else pages[0]
        i = fold(src).find("figyelmezteto elorejelzes magyarorszag")
        excerpt = re.sub(r"\s+", " ", src[i:i + 500] if i >= 0 else src[:400]).strip()
        if alert_pages:
            state.update({"calm": False, "excerpt": excerpt, "checked": True})
            if len(excerpt) > 60:
                arts.append({"title": "HungaroMet: érvényes figyelmeztetés – " + excerpt[:140], "summary": excerpt[:500],
                             "link": f["urls"][0], "source": f["name"], "feed": f["id"], "scope": "official", "lang": "hu", "trust": f.get("trust", 0.95),
                             "official": True, "published": iso(t), "geo": None if not f.get("geo") else {"name": f["geo"][2], "lat": f["geo"][0], "lon": f["geo"][1], "tier": "national"}})
        elif calm_pages == len(pages):
            state.update({"calm": True, "excerpt": excerpt, "checked": True})
        else:
            state.update({"calm": None, "excerpt": excerpt, "checked": True})
    return arts, state


# ───────────────────────── szövegelemzés ─────────────────────────
class Lex:
    def __init__(self, cfg):
        L = cfg["lexicon"]
        self.ar, self.cb, self.sup, self.rum = L["arousal"], L["clickbait"], L["superlative"], L["rumor"]
        self.att, self.sev, self.topics = L["attribution"], L["severity"], L["topics"]
        self.stop = set(L["stopwords"])
        self.evid = re.compile(r"\d[\d.,]*\s?(%|km|mm|cm|fok|°c|c-ot|ft|eur|euro|forint|millio|milliard|fo\b|ember|people|dead|killed|million|billion)")
        self.gaz = []
        for name, al, la, lo, tier in cfg["places"]:
            for a in set([fold(name)] + [fold(x) for x in al]):
                pat = r"(?<![a-z0-9])" + re.escape(a) + ("" if len(a) > 4 else r"(?![a-z0-9])")
                self.gaz.append((len(a), re.compile(pat), name, la, lo, tier))
        self.gaz.sort(key=lambda x: -x[0])
        self.broad = set(cfg.get("broad_places", []))


def hits(ft, lex):
    return sum(1 for k in lex if k in ft)


def locate(ft_title, ft_all, L):
    """A címben keres előbb; több találatból a konkrét hely (város) előzi meg a tágat (ország, régió), egyenlőnél a korábbi említés."""
    for text in (ft_title, ft_all):
        found = []
        for _, rx, name, la, lo, tier in L.gaz:
            m = rx.search(text)
            if m:
                found.append((name in L.broad, m.start(), name, la, lo, tier))
        if found:
            _, _, name, la, lo, tier = sorted(found)[0]
            return {"name": name, "lat": la, "lon": lo, "tier": tier}
    return None


def topics_of(ft, L):
    return sorted(k for k, stems in L.topics.items() if hits(ft, stems))


def base_scores(a, L, prof):
    text = a["title"] + " . " + a.get("summary", "")
    ft = " " + fold(text) + " "
    ar = hits(ft, L.ar)
    excl = min(1.0, text.count("!") / 2)
    caps = min(1.0, len(re.findall(r"\b[A-ZÁÉÍÓÖŐÚÜŰ]{4,}\b", a["title"])) / 3)
    g = clamp(0.15 + 0.45 * min(1, ar / 3) + 0.15 * excl + 0.10 * caps + (0.05 if "?" in a["title"] else 0))
    cb, sp = hits(ft, L.cb), hits(ft, L.sup)
    listicle = 1 if re.match(r"^\s*\d{1,2}\s+[^\W\d]", a["title"]) else 0
    ell = 1 if ("..." in a["title"] or "…" in a["title"]) else 0
    s = clamp(0.10 + 0.30 * min(1, cb / 2) + 0.20 * listicle + 0.12 * ell + 0.18 * min(1, sp / 2) + 0.10 * excl)
    trust = a.get("trust", 0.5)
    if prof and prof.get("n", 0) >= 20:
        trust = 0.5 * trust + 0.5 * prof["v"]["mean"]
    v = 0.35 + (0.30 if a.get("official") else 0) + (trust - 0.5) * 0.30
    ev = len(L.evid.findall(ft)) + (1 if re.search(r"[\"“„”]", text) else 0)
    att = hits(ft, L.att)
    if ev + att >= 1:
        v += 0.10
    if ev + att >= 3:
        v += 0.05
    if hits(ft, L.rum):
        v -= 0.10
    return ft, g, s, clamp(v)


def vec_of(a, L):
    toks = [w for w in WORD.findall(fold(a["title"] + " " + a.get("summary", "")[:200])) if w not in L.stop and not w.isdigit()]
    tf = {}
    for w in toks:
        tf[w] = tf.get(w, 0) + 1
    return {w: 1 + math.log(c) for w, c in tf.items()}


def cosine(u, v):
    if len(u) > len(v):
        u, v = v, u
    dot = sum(x * v.get(w, 0) for w, x in u.items())
    nu = math.sqrt(sum(x * x for x in u.values()))
    nv = math.sqrt(sum(x * x for x in v.values()))
    return dot / (nu * nv) if nu and nv else 0.0


def cluster(arts, L, thr):
    """Eseménycsoportosítás: mohó, koszinusz-hasonlóság alapján (a legkorábbi cikk adja az esemény azonosítóját)."""
    cl = []
    for a in sorted(arts, key=lambda x: x.get("published") or ""):
        va = vec_of(a, L)
        best, bs = None, thr
        for c in cl:
            sim = cosine(va, c["vec"])
            if sim >= bs:
                best, bs = c, sim
        if best is None:
            best = {"id": "ev-" + hashlib.sha1(a["id"].encode()).hexdigest()[:8], "vec": {}, "items": []}
            cl.append(best)
        best["items"].append(a)
        for w, x in va.items():
            best["vec"][w] = best["vec"].get(w, 0) + x
    for c in cl:
        pubs = {fold(x["source"]) for x in c["items"]}
        for x in c["items"]:
            x["event"] = c["id"]
            x["event_size"] = len(c["items"])
            x["event_sources"] = len(pubs)
    return len(cl)


# ───────────────────────── fizikai keresztellenőrzés ─────────────────────────
PLANETARY = {"solar", "geomagnetic"}


def truth_flags(m, t):
    """A data/metrics/environment_truth_matrix.json tolerálás-alapú értelmezése. Visszaad: (flags|None, részletek).
    Elfogadott alakok: {"flags":[...]}, {"anomalies":{"earthquake":{"active":true,"magnitude":5.1}, ...}}, lapos kulcsok (kp, flare_class, ...)."""
    if not isinstance(m, dict):
        return None, {}
    up = parse_date(str(m.get("updated") or m.get("generated_at") or ""))
    if up and (t - up) > timedelta(hours=12):
        return None, {"stale": True}
    flags, det = set(), {}
    for f in m.get("flags") or []:
        flags.add(str(f).lower())
    an = m.get("anomalies") if isinstance(m.get("anomalies"), dict) else m
    for k, v in (an or {}).items():
        k = str(k).lower()
        if isinstance(v, bool):
            if v:
                flags.add(k)
        elif isinstance(v, dict) and (v.get("active") or v.get("anomaly")):
            flags.add(k)
    def num(*ks):
        for src in (an, m):
            for k in ks:
                x = src.get(k) if isinstance(src, dict) else None
                if isinstance(x, dict):
                    x = x.get("value", x.get("magnitude", x.get("max")))
                if isinstance(x, (int, float)):
                    return float(x)
        return None
    mag = num("earthquake_max_mag", "eq_max_mag", "magnitude", "earthquake")
    kp = num("kp", "kp_index", "geomagnetic_kp")
    gust = num("wind_gust_kmh", "gust_kmh")
    drop = num("pressure_drop_3h", "pressure_drop")
    sol = an.get("solar") if isinstance(an, dict) else None
    fc = str(m.get("flare_class") or (sol.get("class", "") if isinstance(sol, dict) else "") or "").upper()
    if mag is not None:
        det["earthquake_mag"] = mag
        if mag >= 4.5:
            flags.add("earthquake")
    if kp is not None:
        det["kp"] = kp
        if kp >= 5:
            flags.add("geomagnetic")
    if fc[:1] in ("M", "X"):
        det["flare"] = fc
        flags.add("solar")
    if gust is not None:
        det["gust_kmh"] = gust
        if gust >= 60:
            flags.add("storm")
    if drop is not None and drop >= 6:
        flags.add("storm")
    alias = {"flare": "solar", "solar_flare": "solar", "kp": "geomagnetic", "geomagnetic_storm": "geomagnetic", "quake": "earthquake", "wind": "storm", "flood": "flood"}
    flags = {alias.get(f, f) for f in flags}
    return flags, det


def apply_truth(a, flags, cfg, L):
    """Ha a hír fizikai anomáliáról szól és a mérés igazolja: V +0.15. Ha katasztrófáról szól, de a mérések nyugodtak: V −0.20 és S +0.15."""
    a["truth"] = {"verdict": "n/a"}
    tp = [x for x in a["topics"] if x in L.topics]
    if flags is None or not tp:
        return
    reg = cfg["region"]
    in_region = bool(a.get("geo")) and hav_km(reg["lat"], reg["lon"], a["geo"]["lat"], a["geo"]["lon"]) <= reg["truth_radius_km"]
    unlocated_local = not a.get("geo") and a["scope"] in ("local", "national", "official")
    confirm = [x for x in tp if x in flags]
    if confirm:
        a["v"] = clamp(a["v"] + 0.15)
        a["truth"] = {"verdict": "igazolt", "flags": confirm, "dv": 0.15}
        return
    checkable = [x for x in tp if x in PLANETARY or in_region or unlocated_local]
    if checkable and not (flags & set(tp)):
        a["v"] = clamp(a["v"] - 0.20)
        a["s"] = clamp(a["s"] + 0.15)
        a["truth"] = {"verdict": "nem igazolt", "topics": checkable, "dv": -0.20, "ds": 0.15}


# ───────────────────────── tanuló rész: Welford, trendek ─────────────────────────
def welford(st, x):
    st["n"] += 1
    d = x - st["mean"]
    st["mean"] += d / st["n"]
    st["m2"] += d * (x - st["mean"])


def wstd(st):
    return math.sqrt(st["m2"] / (st["n"] - 1)) if st["n"] > 1 else 0.0


def new_prof():
    return {"n": 0, **{k: {"n": 0, "mean": 0.0, "m2": 0.0} for k in ("atm", "g", "s", "v")}}


def update_profiles(profiles, arts):
    for a in arts:
        if a.get("profiled"):
            continue
        p = profiles.setdefault(a["source"], new_prof())
        prof_atm = p["atm"]
        a["z"] = round((a["atm"] - prof_atm["mean"]) / wstd(prof_atm), 2) if prof_atm["n"] >= 15 and wstd(prof_atm) > 1e-6 else None
        for k in ("atm", "g", "s", "v"):
            welford(p[k], a[k])
        p["n"] += 1
        a["profiled"] = True
    if len(profiles) > 400:
        for k in sorted(profiles, key=lambda k: profiles[k]["n"])[: len(profiles) - 400]:
            del profiles[k]


def term_set(a, L):
    toks = [w for w in WORD.findall(fold(a["title"])) if w not in L.stop and not w.isdigit() and len(w) >= 4]
    terms = set(toks)
    seq = [w for w in WORD.findall(fold(a["title"])) if w not in L.stop and not w.isdigit()]
    for x, y in zip(seq, seq[1:]):
        terms.add(x + " " + y)
    return terms


def update_trends(trends, new_arts, L, t):
    hrs = trends.setdefault("hours", {})
    for a in new_arts:
        d = parse_date(a.get("published")) or t
        h = d.strftime("%Y-%m-%dT%H")
        bucket = hrs.setdefault(h, {})
        for w in term_set(a, L):
            bucket[w] = bucket.get(w, 0) + 1
    cutoff = (t - timedelta(hours=72)).strftime("%Y-%m-%dT%H")
    for h in [h for h in hrs if h < cutoff]:
        del hrs[h]
    for h, b in hrs.items():
        if len(b) > 400:
            hrs[h] = dict(sorted(b.items(), key=lambda kv: -kv[1])[:400])
    h_now = t.strftime("%Y-%m-%dT%H")
    recent, base = {}, {}
    for h, b in hrs.items():
        age = (t - datetime.strptime(h, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)).total_seconds() / 3600
        tgt = recent if age < 6 else base if age < 48 else None
        if tgt is not None:
            for w, c in b.items():
                tgt[w] = tgt.get(w, 0) + c
    span = len(hrs)
    rising = []
    if span >= 24:
        for w, c in recent.items():
            if c >= 5:
                b6 = base.get(w, 0) / 7
                ratio = (c + 1) / (b6 + 1)
                if ratio >= 2:
                    rising.append({"term": w, "recent": c, "base6h": round(b6, 1), "ratio": round(ratio, 1)})
        rising.sort(key=lambda r: -r["ratio"] * math.log(1 + r["recent"]))
    return rising[:12], span < 24


# ───────────────────────── fő folyamat ─────────────────────────
def article_id(a):
    return hashlib.sha1((fold(a["title"]) + "|" + fold(a["source"])).encode()).hexdigest()[:12]


def merge(old, fresh, t, keep_h, max_n):
    by = {a["id"]: a for a in old}
    for a in fresh:
        a["id"] = article_id(a)
        cur = by.get(a["id"])
        if cur is None:
            a["first_seen"] = iso(t)
            by[a["id"]] = a
        elif SCOPE_RANK.get(a["scope"], 9) < SCOPE_RANK.get(cur["scope"], 9):
            cur["scope"] = a["scope"]
    lim = iso(t - timedelta(hours=keep_h))
    arts = [a for a in by.values() if (a.get("published") or a.get("first_seen") or "") >= lim]
    arts.sort(key=lambda a: a.get("published") or a.get("first_seen") or "", reverse=True)
    return arts[:max_n]


def analyze(cfg, arts, profiles, flags, L):
    thr = cfg["limits"]["cluster_threshold"]
    for a in arts:
        ft, g, s, v = base_scores(a, L, profiles.get(a["source"]))
        a["topics"] = topics_of(ft, L)
        if not a.get("geo"):
            a["geo"] = locate(fold(a["title"]), ft, L)
        a["g"], a["s"], a["v"] = g, s, v
    n_ev = cluster(arts, L, thr)
    for a in arts:
        a["v"] = clamp(a["v"] + 0.06 * min(2, max(0, a.get("event_sources", 1) - 1)))
        apply_truth(a, flags, cfg, L)
        a["g"], a["s"], a["v"] = round(a["g"], 3), round(a["s"], 3), round(a["v"], 3)
        a["atm"] = round(a["g"] * a["s"] * (1 - a["v"]), 4)
    return n_ev


def snapshot(arts, rising, flags, t):
    last = [a for a in arts if (a.get("published") or "") >= iso(t - timedelta(hours=24))] or arts
    vals = [a["atm"] for a in last]
    by = {}
    for sc in ("local", "national", "international", "official"):
        x = [a["atm"] for a in last if a["scope"] == sc]
        if x:
            by[sc] = round(sum(x) / len(x), 4)
    return {"t": iso(t), "n": len(last), "mean": round(sum(vals) / len(vals), 4) if vals else 0, "p90": round(pctl(vals, 0.9), 4) if vals else 0,
            "by_scope": by, "flags": sorted(flags) if flags is not None else None, "rising": [r["term"] for r in rising[:3]]}


def build_alerts(cfg, arts, rising, official, new_ids):
    n = cfg["notify"]
    out = []
    if official.get("calm") is False and official.get("excerpt"):
        out.append({"key": "official:" + hashlib.sha1(official["excerpt"].encode()).hexdigest()[:8], "title": "🚨 Hivatalos figyelmeztetés (HungaroMet)",
                    "message": re.sub(r"\s+", " ", official["excerpt"])[:400], "priority": 4, "tags": ["rotating_light"]})
    th = n["outlier_min_atm"]
    outl = [a for a in arts if a["id"] in new_ids and a["scope"] in ("local", "national") and ((a.get("z") or 0) >= n["outlier_z"] or a["atm"] >= th) and a["atm"] >= th * 0.8]
    for a in sorted(outl, key=lambda a: -a["atm"])[:2]:
        out.append({"key": "noise:" + a.get("event", a["id"]), "title": "📢 Kiugró zaj (ATM %.2f)" % a["atm"], "priority": 3, "tags": ["loudspeaker"],
                    "message": "%s – %s\nG %.2f · S %.2f · V %.2f" % (a["title"][:160], a["source"], a["g"], a["s"], a["v"])})
    for r in rising[:1]:
        if r["ratio"] >= n["rising_ratio"] and r["recent"] >= n["rising_min"]:
            out.append({"key": "rising:" + r["term"], "title": "📈 Felszálló téma: " + r["term"], "priority": 3, "tags": ["chart_with_upwards_trend"],
                        "message": "Az elmúlt 6 órában %d említés (a megszokott %.1f-szerese)." % (r["recent"], r["ratio"])})
    return out[: n["max_per_run"]]


def run(force=False):
    cfg = jload(ROOT / "config" / "sources.json")
    t = now()
    L = Lex(cfg)
    errors = {}
    state = jload(DATA / "state.json", {"signature": "", "cool": {}, "last_hist": ""})
    old = (jload(DATA / "articles.json", {}) or {}).get("articles", [])
    profiles = jload(MET / "source_profiles.json", {}) or {}
    trends = jload(MET / "trends.json", {}) or {}
    flags, fdet = truth_flags(jload(MET / "environment_truth_matrix.json"), t)
    fresh = collect(cfg, errors)
    off_arts, official = collect_official(cfg, errors, t)
    fresh += off_arts
    if not fresh and errors and not old:
        print("Nincs elérhető forrás:", errors)
    known = {a["id"] for a in old}
    arts = merge(old, fresh, t, cfg["limits"]["keep_hours"], cfg["limits"]["max_articles"])
    new_ids = {a["id"] for a in arts if a["id"] not in known}
    n_ev = analyze(cfg, arts, profiles, flags, L)
    new_arts = [a for a in arts if a["id"] in new_ids]
    update_profiles(profiles, [a for a in arts if not a.get("profiled")])
    rising, warming = update_trends(trends, new_arts, L, t)
    snap = snapshot(arts, rising, flags, t)
    sig_src = json.dumps([[a["id"], round(a["atm"], 2)] for a in arts if (a.get("published") or "") >= iso(t - timedelta(hours=24))] + [snap["flags"], snap["rising"], official.get("calm")], sort_keys=True)
    sig = hashlib.sha1(sig_src.encode()).hexdigest()
    changed = force or sig != state.get("signature") or not (DATA / "articles.json").exists()
    alerts = build_alerts(cfg, arts, rising, official, new_ids) if new_ids or official.get("calm") is False else []
    meta = {"version": cfg["version"], "generated_at": iso(t), "region": cfg["region"], "thresholds": cfg["thresholds"], "events": n_ev,
            "errors": errors, "truth": {"available": flags is not None, "flags": sorted(flags) if flags is not None else None, "detail": fdet},
            "official": {"calm": official.get("calm"), "excerpt": official.get("excerpt", "")[:300]}, "rising": rising, "warming_up": warming}
    if changed:
        jsave(DATA / "articles.json", {"meta": meta, "articles": [{k: v for k, v in a.items() if k != "trust"} for a in arts]})
        jsave(MET / "source_profiles.json", profiles)
        jsave(MET / "trends.json", trends)
        hist = jload(MET / "atm_history.json", {"points": []})
        pts = hist.get("points", [])
        last_t = parse_date(state.get("last_hist")) or datetime(1970, 1, 1, tzinfo=timezone.utc)
        if pts == [] or sig != state.get("signature") or t - last_t >= timedelta(hours=cfg["limits"]["history_heartbeat_h"]):
            pts.append(snap)
            state["last_hist"] = iso(t)
        jsave(MET / "atm_history.json", {"points": pts[-cfg["limits"]["history_max"]:]})
        state["signature"] = sig
        jsave(DATA / "state.json", state)
    outbox = os.environ.get("MNT_OUTBOX") or "/tmp/mnt_outbox.json"
    jsave(outbox, alerts)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write("changed=%s\n" % ("true" if changed else "false"))
    print("MNT v38: %d cikk (%d új), %d esemény, ATM átlag %.3f, p90 %.3f, hibás forrás: %s, fizikai mérés: %s, riasztás: %d, változás: %s" % (
        len(arts), len(new_ids), n_ev, snap["mean"], snap["p90"], list(errors) or "nincs", "van" if flags is not None else "nincs", len(alerts), changed))
    return {"changed": changed, "alerts": alerts, "articles": arts, "snapshot": snap, "errors": errors}


# ───────────────────────── ntfy ─────────────────────────
def notify():
    topic = (os.environ.get("NTFY_TOPIC") or "").strip()
    if not topic:
        return 0
    cfg = jload(ROOT / "config" / "sources.json")
    outbox = jload(os.environ.get("MNT_OUTBOX") or "/tmp/mnt_outbox.json", []) or []
    state = jload(DATA / "state.json", {"signature": "", "cool": {}, "last_hist": ""})
    t, cool, sent = now(), state.setdefault("cool", {}), 0
    ch = timedelta(hours=cfg["notify"]["cooldown_h"])
    repo = (os.environ.get("GITHUB_REPOSITORY") or "").split("/")
    site = "https://%s.github.io/%s/" % (repo[0].lower(), repo[1]) if len(repo) == 2 else None
    for a in outbox:
        last = parse_date(cool.get(a["key"]))
        if last and t - last < ch:
            continue
        body = {"topic": topic, "title": a["title"], "message": a["message"], "priority": a.get("priority", 3), "tags": a.get("tags", [])}
        if site:
            body["click"] = site
        try:
            req = Request("https://ntfy.sh", data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json", "User-Agent": UA})
            urlopen(req, timeout=15).read()
            cool[a["key"]] = iso(t)
            sent += 1
        except Exception as e:
            print("ntfy hiba:", str(e)[:100])
    for k in [k for k, v in cool.items() if (parse_date(v) or t) < t - timedelta(days=3)]:
        del cool[k]
    if sent:
        jsave(DATA / "state.json", state)
    print("ntfy: %d értesítés elküldve" % sent)
    return sent


# ───────────────────────── PWA-ikonok ─────────────────────────
def make_png(size):
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    cx = cy = (size - 1) / 2
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            dx, dy = (x - cx) / cx, (y - cy) / cy
            d = math.hypot(dx, dy)
            r, g, b = 3, 4, 8
            if d < 0.78:
                k = 1 - d / 0.78
                r, g, b = int(8 + 40 * k), int(12 + 60 * k), int(30 + 150 * k)
            ring = abs(d - 0.60)
            if ring < 0.025:
                r, g, b = 139, 92, 246
            if abs(dy) < 0.012 and d < 0.78 or abs(dx) < 0.012 and d < 0.78:
                r, g, b = max(r, 30), max(g, 70), max(b, 160)
            if hypot_pt(dx, dy, 0.18, -0.22) < 0.07:
                r, g, b = 245, 158, 11
            if d > 0.96 and d < 1.0:
                r, g, b = 10, 14, 28
            row += bytes((r, g, b, 255))
        rows.append(bytes(row))
    raw = b"".join(rows)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def hypot_pt(x, y, px, py):
    return math.hypot(x - px, y - py)


def make_icons():
    (ROOT / "icons").mkdir(exist_ok=True)
    for s in (192, 512):
        (ROOT / "icons" / ("icon-%d.png" % s)).write_bytes(make_png(s))
    print("ikonok kész")


if __name__ == "__main__":
    if "--make-icons" in sys.argv:
        make_icons()
    elif "--notify" in sys.argv:
        notify()
    else:
        run(force=os.environ.get("MNT_FORCE") == "1")
