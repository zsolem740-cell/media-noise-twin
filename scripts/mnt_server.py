#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Média-Zaj Twin v40 – M2 modul a 8x8 mátrix-rendszerben (csak Python standard library).

Használat:
  python3 scripts/mnt_server.py              gyűjtés + elemzés; csak érdemi változásnál ír fájlt
  python3 scripts/mnt_server.py --notify     a kimenő riasztások küldése (NTFY_TOPIC titokkal; hiányában csendben kihagyja)
  python3 scripts/mnt_server.py --make-icons PWA-ikonok előállítása
Környezeti változók (tesztelésre): MNT_FIXTURES=<könyvtár> (offline: <forrás-id>.xml, hungaromet_<n>.html),
  MNT_ROOT, MNT_OUTBOX, MNT_FORCE=1, MNT_NOW=<ISO idő>.

ATM = G · S · (1 − V)   (Anti-Noise Filter; az architekturális szerződés pontos definíciói)
  G  fizikai nyugalom (stationarity) 0..1. Az M1 (Solaris) data/metrics/environment_truth_matrix.json
     core_metrics.stationarity_G mezőjéből jön. 1,0 = nyugodt fizikai környezet, kis érték = fizikai anomália.
     NEM a hír érzelmi töltete. Mérés nélkül 1,0 (forrás: "default"); G nélküli, régi alakú mátrixnál a jelzőkből becsült ("derived").
  S  zaj (Signal/Noise score) 0..1: a hír nyelvi zaja: indulatszavak, felkiáltójel, NAGYBETŰ, csalogató szavak, listás cím, felsőfok.
  V  érvényesség (Validity) 0..1: a hír állításainak egyezése a fizikai méréssel és az ellenőrizhetőség
     (hivatalos forrás, bizalom, számok/idézet/hivatkozás, több független forrás).
Az ATM akkor nagy, ha a fizikai környezet nyugodt (G nagy), a hír hangos (S nagy) és az állításai nem érvényesek (V kicsi).
Kimenet a P8-buszra: data/metrics/media_noise_matrix.json (header / core_metrics / dynamic_payload / weights_vector).
"""
import hashlib
import asyncio
import html
import json
import math
import os
import random
import re
import struct
import sys
import unicodedata
import zlib
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(os.environ.get("MNT_ROOT") or Path(__file__).resolve().parent.parent)
DATA = ROOT / "data"
MET = DATA / "metrics"
UA = "Mozilla/5.0 (compatible; MediaNoiseTwin/40)"
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
def fetch_once(url, timeout=20):
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, text/html;q=0.8, */*;q=0.5"})
    with urlopen(req, timeout=timeout) as r:
        return r.read(3_000_000)


async def afetch(url, key, timeout=20, attempts=4, base=1.5):
    """Nem blokkoló lekérés. 408/425/429/5xx és hálózati hiba esetén exponenciális visszalépés véletlen jitterrel (Retry-After-t is tiszteli)."""
    fx = os.environ.get("MNT_FIXTURES")
    if fx:
        p = Path(fx) / key
        return p.read_bytes() if p.exists() else None
    last = None
    for i in range(attempts):
        wait = min(30.0, base * 2 ** i) * (0.5 + random.random())
        try:
            return await asyncio.to_thread(fetch_once, url, timeout)
        except HTTPError as e:
            last = e
            if e.code not in (408, 425, 429, 500, 502, 503, 504):
                break
            ra = e.headers.get("Retry-After") if e.headers else None
            if ra and str(ra).isdigit():
                wait = max(wait, min(60.0, float(ra)))
        except (URLError, TimeoutError, OSError) as e:
            last = e
        if i < attempts - 1:
            await asyncio.sleep(wait)
    raise RuntimeError(str(last)[:100] if last else "ismeretlen hiba")


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


def clean_source(s):
    """Kiadó-név rendbetétele: a Google News néha elválasztójellel kezdődő nevet ad (például „| hvg.hu”), ami külön „forrásnak” számítana."""
    t = re.sub(r"\s+", " ", str(s or "")).strip()
    t = re.sub(r"^[\s|·•:/\\\-–—]+", "", t)
    t = re.sub(r"[\s|·•:/\\\-–—]+$", "", t)
    return t.strip()


def entry_pub_title(it, f):
    """A kiadó és a cím egy feed-elemből: a kiadó neve rendbetéve, a cím végi kiadó-név levágása a nyers és a rendbetett névvel is működik."""
    raw = it.get("publisher")
    return clean_source(raw) or f["name"], clean_title(it["title"], raw)


def clean_title(title, publisher):
    t = title.strip()
    for sep in (" - ", " – ", " | "):
        if sep in t:
            head, tail = t.rsplit(sep, 1)
            if publisher and fold(clean_source(tail)) == fold(clean_source(publisher)):
                return head.strip()
            if not publisher and len(tail) <= 40 and len(head) > 20:
                return head.strip()
    return t


async def refresh_m1(cfg, errors):
    """Az M1 (Solaris) P8-csomagjának letöltése a konfigurált címekről (először a Pages, majd a raw). Érvénytelen vagy hiányzó csomagnál None."""
    m1 = cfg.get("m1") or {}
    if m1.get("enabled") is False:
        return None
    for i, u in enumerate(m1.get("urls", [])):
        try:
            raw = await afetch(u, "m1_%d.json" % i)
            if not raw:
                continue
            d = json.loads(raw.decode("utf-8", "ignore"))
            hdr = d.get("header") if isinstance(d, dict) else None
            if isinstance(hdr, dict) and str(hdr.get("module_id", "")).startswith("M1") and isinstance(d.get("core_metrics"), dict):
                errors.pop("m1", None)
                return d
            errors["m1"] = "érvénytelen M1-csomag"
        except Exception as e:
            errors["m1"] = str(e)[:100]
    errors.setdefault("m1", "nincs adat")
    return None


M5_URLS = ["https://zsolem740-cell.github.io/solaris/data/metrics/finance_matrix.json", "https://raw.githubusercontent.com/zsolem740-cell/solaris/main/data/metrics/finance_matrix.json"]


async def refresh_m5(cfg, errors):
    """Az M5 (Solaris, hivatalos MNB/EKB árfolyamok) P8-csomagjának letöltése: először a Pages, majd a raw. Érvénytelen vagy hiányzó csomagnál None (ilyenkor az árfolyam-ellenőrzés kimarad)."""
    m5 = cfg.get("m5") or {}
    if m5.get("enabled") is False:
        return None
    for i, u in enumerate(m5.get("urls") or M5_URLS):
        try:
            raw = await afetch(u, "m5_%d.json" % i)
            if not raw:
                continue
            d = json.loads(raw.decode("utf-8", "ignore"))
            hdr = d.get("header") if isinstance(d, dict) else None
            dp = d.get("dynamic_payload") if isinstance(d, dict) else None
            if isinstance(hdr, dict) and str(hdr.get("module_id", "")).startswith("M5") and isinstance(d.get("core_metrics"), dict) and isinstance(dp, dict) and isinstance(dp.get("channels"), dict):
                errors.pop("m5", None)
                return d
            errors["m5"] = "érvénytelen M5-csomag"
        except Exception as e:
            errors["m5"] = str(e)[:100]
    errors.setdefault("m5", "nincs adat")
    return None


def fin_rates(m, t):
    """Az M5 hivatalos forint-árfolyamai: {"EUR": {"value", "date"}, "USD": {...}} vagy None. 12 óránál régebbi fájlt és 5 napnál régebbi közzétételt nem használ."""
    if not isinstance(m, dict):
        return None
    hdr = m.get("header") if isinstance(m.get("header"), dict) else {}
    ts = hdr.get("timestamp")
    if not (isinstance(ts, (int, float)) and not isinstance(ts, bool) and ts > 1e9):
        return None
    if (t - datetime.fromtimestamp(ts, tz=timezone.utc)) > timedelta(hours=12):
        return None
    ch = (m.get("dynamic_payload") or {}).get("channels") or {}
    out = {}
    for cur, cid in (("EUR", "huf_eur"), ("USD", "huf_usd")):
        x = ch.get(cid) if isinstance(ch, dict) else None
        if (isinstance(x, dict) and isinstance(x.get("value"), (int, float)) and not isinstance(x.get("value"), bool) and x["value"] > 0
                and isinstance(x.get("age_days"), (int, float)) and not isinstance(x.get("age_days"), bool) and 0 <= x["age_days"] <= 5 and isinstance(x.get("date"), str)):
            out[cur] = {"value": float(x["value"]), "date": x["date"]}
    return out or None


async def collect(cfg, errors):
    feeds = [f for f in cfg["feeds"] if f.get("enabled") is not False and f["type"] == "rss"]

    async def one(f):
        try:
            raw = await afetch(f["url"], f["id"] + ".xml")
            if raw is None:
                raise RuntimeError("nincs adat")
            return f, parse_feed(raw), None
        except Exception as e:
            return f, [], str(e)[:120]

    out, mx = [], cfg["limits"].get("max_per_feed", 60)
    for f, items, err in await asyncio.gather(*[one(f) for f in feeds]):
        if err:
            errors[f["id"]] = err
            continue
        for it in items[:mx]:
            pub, title = entry_pub_title(it, f)
            summ = "" if f["id"].startswith("gn_") else strip_html(it.get("summary", ""))[:600]
            d = parse_date(it.get("date"))
            link = it.get("link", "")
            if not re.match(r"^https?://", link, re.I):
                link = ""          # nem megbízható forrás: csak http(s) hivatkozás kerülhet a lapra
            out.append({"title": title, "summary": summ, "link": link, "source": pub, "feed": f["id"], "scope": f["scope"],
                        "lang": f.get("lang", ""), "trust": f.get("trust", 0.5), "official": bool(f.get("official")),
                        "published": iso(d) if d else None})
    return out


async def collect_official(cfg, errors, t):
    """HungaroMet: nincs nyilvános RSS/CAP, ezért a szöveges figyelmeztető oldalak tartalmát értelmezi (heurisztika)."""
    state = {"calm": None, "excerpt": "", "checked": False}
    arts = []
    for f in cfg["feeds"]:
        if f["type"] != "official_text" or f.get("enabled") is False:
            continue

        async def page(i, u):
            try:
                raw = await afetch(u, f["id"] + "_%d.html" % i)
                return strip_html(raw.decode("utf-8", "ignore")) if raw else None
            except Exception as e:
                errors[f["id"]] = str(e)[:120]
                return None
        pages = [x for x in await asyncio.gather(*[page(i, u) for i, u in enumerate(f["urls"])]) if x]
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


def base_scores(a, L, prof, w):
    """S (nyelvi zaj) és V (érvényesség a fizikai keresztellenőrzés ELŐTT). A G nem itt készül: az az M1 fizikai nyugalmából jön.
    w = [w_indulat, w_csalogatás, w_bizonyíték, w_megerősítés] (az M8 Sentinel hangolhatja; alapérték 1,0)."""
    text = a["title"] + " . " + a.get("summary", "")
    ft = " " + fold(text) + " "
    arousal = min(1.0, hits(ft, L.ar) / 3)
    excl = min(1.0, text.count("!") / 2)
    caps = min(1.0, len(re.findall(r"\b[A-ZÁÉÍÓÖŐÚÜŰ]{4,}\b", a["title"])) / 3)
    cb, sp = hits(ft, L.cb), hits(ft, L.sup)
    listicle = 1 if re.match(r"^\s*\d{1,2}\s+[^\W\d]", a["title"]) else 0
    ell = 1 if ("..." in a["title"] or "…" in a["title"]) else 0
    s = clamp(0.08 + w[0] * 0.28 * arousal + w[1] * (0.24 * min(1, cb / 2) + 0.14 * listicle + 0.10 * ell + 0.12 * min(1, sp / 2))
              + 0.10 * excl + 0.06 * caps + (0.04 if "?" in a["title"] else 0))
    trust = a.get("trust", 0.5)
    if prof and prof.get("n", 0) >= 20:
        trust = 0.5 * trust + 0.5 * prof["v"]["mean"]
    v = 0.35 + (0.30 if a.get("official") else 0) + (trust - 0.5) * 0.30
    ev = len(L.evid.findall(ft)) + (1 if re.search(r"[\"“„”]", text) else 0)
    att = hits(ft, L.att)
    if ev + att >= 1:
        v += w[2] * 0.10
    if ev + att >= 3:
        v += w[2] * 0.05
    if hits(ft, L.rum):
        v -= 0.10
    return ft, s, clamp(v)


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


# ───────────────────────── leíró mezők (csak jelentés, szabályverzió d1) ─────────────────────────
# Ezek a mezők NEM módosítják az S-t, a V-t, a G-t és az ATM-et: a címkékkel való validálás után kerülhetnek be a számításba.
RULES_V = "d2"                                    # d2: az URL-alapú műfaj-jelölés (a d1 csak a címet nézte)
GENRE_STRONG = ("velemeny", "kommentar", "publicisztika", "elemzo", "elemzes", "szakerto", "politologus", "kozgazdasz", "opinion", "analysis", "analyst", "expert", "editorial", "op-ed", "commentary")
GENRE_WEAK = ("szerint", "szerinte", "says", "warns", "figyelmeztet")
KP_RE = re.compile(r"\bKp\b[^0-9\n]{0,24}?(\d{1,2}(?:[.,]\d)?)(?!\d)(?!\s*(?:nap|óra|ora|perc|%|cm|km|m/s|fok|°|millió|ezer|év))", re.I)


def s_part(text, L, is_title):
    """Az S (nyelvi zaj) képlete egyetlen szövegrészre (cím vagy törzs), egységes 1,0 súlyokkal; a fő S-t nem érinti."""
    ft = " " + fold(text) + " "
    ar = min(1.0, hits(ft, L.ar) / 3)
    excl = min(1.0, text.count("!") / 2)
    caps = min(1.0, len(re.findall(r"\b[A-ZÁÉÍÓÖŐÚÜŰ]{4,}\b", text)) / 3)
    cb, sp = hits(ft, L.cb), hits(ft, L.sup)
    v = 0.08 + 0.28 * ar + 0.24 * min(1, cb / 2) + 0.12 * min(1, sp / 2) + 0.10 * excl + 0.06 * caps
    if is_title:
        v += (0.14 if re.match(r"^\s*\d{1,2}\s+[^\W\d]", text) else 0) + (0.10 if ("..." in text or "…" in text) else 0) + (0.04 if "?" in text else 0)
    return clamp(v)


def body_text(a):
    """A használható törzs: elég hosszú, és nem a cím ismétlése (az RSS gyakran csak a címet vagy a forrás nevét adja)."""
    b = (a.get("summary") or "").strip()
    ti = (a.get("title") or "").strip()
    if len(b) < 60 or fold(b)[:40] == fold(ti)[:40]:
        return None
    return b


GENRE_URL = ("opinion", "opinions", "editorial", "editorials", "analysis", "commentary", "op-ed", "oped", "columnist", "columnists", "velemeny", "kommentar", "publicisztika", "szerkesztoi")


def url_genre(link):
    """Az URL útvonalának TELJES szakasza (nem szótöredék) vélemény-rovatot jelez: /opinion/, /velemeny/, /editorial/… A Google News átirányító linkjei átlátszatlanok: ott nincs jelzés."""
    try:
        path = fold(urlparse(str(link or "")).path)
    except ValueError:
        return []
    return sorted({"url:" + seg for seg in path.split("/") if seg in GENRE_URL})


def genre_of(title, link=None):
    toks = re.findall(r"[a-z0-9\-]+", fold(title))
    strong = sorted({x for x in GENRE_STRONG if any(tk.startswith(x) for tk in toks)}) + url_genre(link)
    weak = sorted({x for x in GENRE_WEAK if any(tk == x or tk.startswith(x) for tk in toks)})
    return ("v" if strong else "t"), strong, weak


def kp_conflict(a, m1):
    """Kemény adat (csak a Kp, az M1-ből): ha a cikk Kp-értéke sem a mostanival, sem a 24 órás csúccsal nem egyezik (±2), emberi ellenőrzést kér. Nem ítél, nem módosít."""
    if not isinstance(m1, dict) or not isinstance(m1.get("kp_index"), (int, float)):
        return None
    kp = float(m1["kp_index"])
    hi = max(kp, float(m1["kp_max_24h"])) if isinstance(m1.get("kp_max_24h"), (int, float)) else kp
    for m in KP_RE.finditer(a["title"] + " . " + (a.get("summary") or "")):
        try:
            v = float(m.group(1).replace(",", "."))
        except ValueError:
            continue
        if 0 <= v <= 9 and abs(v - kp) > 2 and abs(v - hi) > 2:
            return {"kind": "kp", "article": v, "measured": round(kp, 2), "max_24h": round(hi, 2), "human_check": True}
    return None


FX_THR_PCT = 3.0                                 # ideiglenes, NEM kalibrált küszöb (jelentés-jellegű; a címkék után igazítjuk)
FX_RANGE = {"EUR": (150.0, 900.0), "USD": (120.0, 800.0)}
_CUR = r"\b(eur[óo]\w*|euro\w*|eur\b|doll[áa]r\w*|dollar\w*|usd\b)"
_NUM = r"(?<![\d.,])(?<!\d\s)(\d{3}(?:[.,]\d{1,2})?)(?!\d)"
_HUF = r"\s*(?:forint\w*|ft\b|huf\b)"
FX_A = re.compile(_CUR + r"[^0-9\n]{0,30}?" + _NUM + _HUF, re.I)
FX_B = re.compile(_NUM + _HUF + r"[^0-9\n]{0,24}?" + _CUR, re.I)


def fx_conflict(a, rates):
    """Kemény adat (az M5-ből, MNB hivatalos árfolyam): ha a cikk euró- vagy dollár-árfolyamot állít forintban, és az több mint 3%-kal eltér a hivatalostól, emberi ellenőrzést kér.
    Nem ítél, nem módosít. Előrejelzésnél vagy képletes szövegnél téves jelzés lehet, ezért csak „ellenőrizd”."""
    if not rates:
        return None
    text = a["title"] + " . " + (a.get("summary") or "")
    for rx in (FX_A, FX_B):
        for m in rx.finditer(text):
            cur_s, num_s = (m.group(1), m.group(2)) if rx is FX_A else (m.group(2), m.group(1))
            cur = "EUR" if cur_s.lower().startswith("eur") else "USD"
            try:
                claim = float(num_s.replace(",", "."))
            except ValueError:
                continue
            lo, hi = FX_RANGE[cur]
            off = rates.get(cur)
            if not off or not (lo <= claim <= hi):
                continue
            diff = (claim / off["value"] - 1) * 100
            if abs(diff) > FX_THR_PCT:
                return {"kind": "fx", "pair": cur + "/HUF", "article": claim, "official": round(off["value"], 2), "date": off["date"], "diff_pct": round(diff, 1), "thr_pct": FX_THR_PCT, "human_check": True}
    return None


def _tp(a):
    for k in ("published", "first_seen"):
        x = a.get(k)
        if x:
            try:
                return datetime.fromisoformat(str(x).replace("Z", "+00:00"))
            except ValueError:
                continue
    return None


def describe_articles(arts, L, t, m1_dyn=None, rates=None):
    """Cikkenkénti leíró mezők (a["d"], a["pc"]) és modulszintű összegzés. Csak jelentés: az S, V, G, ATM értéke nem változik."""
    by_ev = {}
    for a in arts:
        by_ev.setdefault(a.get("event") or a["id"], []).append(a)
    amp_sizes = []
    for items in by_ev.values():
        timed = sorted(items, key=lambda x: (_tp(x) or t, x["id"]))
        t0 = _tp(timed[0]) or t
        amp_sizes.append(len({fold(x["source"]) for x in items}))
        for x in items:
            tx = _tp(x) or t0
            in60 = {fold(y["source"]) for y in items if (_tp(y) or t0) <= t0 + timedelta(minutes=60)}
            body = body_text(x)
            st = round(s_part(x["title"], L, True), 3)
            sb = round(s_part(body, L, False), 3) if body else None
            gen, ghits, _ = genre_of(x["title"], x.get("link"))
            d = {"rv": RULES_V, "gen": gen, "st": st, "sb": sb, "cbd": round(st - sb, 3) if sb is not None else None,
                 "lag": max(0, int((tx - t0).total_seconds() // 60)), "amp": len(in60), "nsrc": x.get("event_sources", 1), "first": 1 if x is timed[0] else 0}
            if any(h.startswith("url:") for h in ghits):
                d["gu"] = 1                                # a műfaj-jelölést az URL (rovat) adta
            if x is not timed[0] and len(items) > 1:
                d["osrc"] = timed[0]["source"][:40]
            x["d"] = d
            pc = kp_conflict(x, m1_dyn) or fx_conflict(x, rates)
            if pc:
                x["pc"] = pc
            else:
                x.pop("pc", None)
    last = [a for a in arts if (a.get("published") or "") >= iso(t - timedelta(hours=24))] or arts
    n = max(1, len(last))
    cbd = [a["d"]["cbd"] for a in last if a["d"]["cbd"] is not None]
    wsum = sum(0.5 ** (max(0.0, (t - (_tp(a) or t)).total_seconds() / 3600) / 48) for a in arts) or 1.0
    awa = sum(a["atm"] * 0.5 ** (max(0.0, (t - (_tp(a) or t)).total_seconds() / 3600) / 48) for a in arts) / wsum if arts else 0.0
    src = {}
    for a in last:
        src.setdefault(a["source"], []).append(a)
    stats = [{"source": k, "n": len(v), "s_mean": round(sum(x["s"] for x in v) / len(v), 3) if len(v) >= 10 else None, "v_mean": round(sum(x["v"] for x in v) / len(v), 3) if len(v) >= 10 else None}
             for k, v in sorted(src.items(), key=lambda kv: -len(kv[1]))[:12]]
    return {"rules_v": RULES_V, "genre_share": {"velemeny_elemzes": round(sum(1 for a in last if a["d"]["gen"] == "v") / n, 3), "tudositas": round(sum(1 for a in last if a["d"]["gen"] == "t") / n, 3)},
            "clickbait": {"n": len(cbd), "mean_delta": round(sum(cbd) / len(cbd), 3) if cbd else None, "p90_delta": round(pctl(cbd, 0.9), 3) if cbd else None},
            "amp": {"events": len(by_ev), "multi_source": sum(1 for z in amp_sizes if z > 1), "max_sources": max(amp_sizes) if amp_sizes else 0, "p90_sources": round(pctl([float(z) for z in amp_sizes], 0.9), 1) if amp_sizes else 0},
            "genre_url_hits_24h": sum(1 for a in last if a["d"].get("gu")), "physical_conflicts_24h": sum(1 for a in last if a.get("pc")),
            "fx_reference": ({"EUR/HUF": rates["EUR"]["value"] if "EUR" in rates else None, "USD/HUF": rates["USD"]["value"] if "USD" in rates else None, "date": max(v["date"] for v in rates.values()), "source": "M5 (MNB hivatalos árfolyam)"} if rates else None), "age_weighted_atm": round(awa, 4), "source_stats": stats,
            "basis": {"genre": "kulcsszó-jelölők a címben és vélemény-rovat az URL-ben (heurisztika, nem kalibrált)", "origin": "az első észlelt megjelenés a feed időbélyege alapján (nem bizonyított eredet)",
                      "clickbait": "S(cím) − S(törzs), nincs küszöb (a kalibráció a címkék után)", "age_weighted_atm": "0,5-ös hatvány, felezési idő 48 óra", "physical_conflict": "a Kp (M1) és az EUR/HUF, USD/HUF árfolyam (M5, MNB hivatalos); az árfolyam-küszöb (±3%) nem kalibrált; emberi ellenőrzéssel",
                      "source_stats": "az átlagok csak n ≥ 10 cikknél jelennek meg"}}


# ───────────────────────── fizikai keresztellenőrzés ─────────────────────────
PLANETARY = {"solar", "geomagnetic"}


RET_LIMITS = {"live_24h": 96, "daily_30d": 30, "monthly_12m": 12}


def _accumulate(item, e):
    """Folyamatos összesítés: egy új rekord beépítése a napi vagy a havi szintbe (a null G nem számít az átlagba)."""
    item["n"] = item.get("n", 0) + 1
    item["v_sum"] = round(item.get("v_sum", 0) + e["V"], 4)
    item["s_sum"] = round(item.get("s_sum", 0) + e["S"], 4)
    item["atm_sum"] = round(item.get("atm_sum", 0) + e["ATM"], 4)
    if e["G"] is not None:
        item["n_g"] = item.get("n_g", 0) + 1
        item["g_sum"] = round(item.get("g_sum", 0) + e["G"], 3)
        item["G_min"] = e["G"] if item.get("G_min") is None else min(item["G_min"], e["G"])
    item["G_avg"] = round(item["g_sum"] / item["n_g"], 3) if item.get("n_g") else None
    item["V_avg"] = round(item["v_sum"] / item["n"], 3)
    item["S_avg"] = round(item["s_sum"] / item["n"], 3)
    item["ATM_avg"] = round(item["atm_sum"] / item["n"], 4)
    return item


def fold_retention(prev_dp, entry):
    """P8 v1.1 gördülő tár: az előző P8-fájl tárából folytatja; ugyanabban az órában nem ad új rekordot."""
    prev_dp = prev_dp if isinstance(prev_dp, dict) else {}
    live, daily, monthly = (list(prev_dp.get(k) or []) for k in ("live_24h", "daily_30d", "monthly_12m"))
    if not (live and live[-1].get("hour") == entry["hour"]):
        live.append(entry)
        date, month = entry["t"][:10], entry["t"][:7]
        if daily and daily[-1].get("date") == date:
            _accumulate(daily[-1], entry)
        else:
            daily.append(_accumulate({"date": date}, entry))
        if monthly and monthly[-1].get("month") == month:
            _accumulate(monthly[-1], entry)
        else:
            monthly.append(_accumulate({"month": month}, entry))
    return {"live_24h": live[-RET_LIMITS["live_24h"]:], "daily_30d": daily[-RET_LIMITS["daily_30d"]:], "monthly_12m": monthly[-RET_LIMITS["monthly_12m"]:]}


def truth_flags(m, t):
    """Az M1 (Solaris) environment_truth_matrix.json értelmezése. Visszaad: (flags|None, részletek, G|None).
    Elsődleges alak a P8-szerződés: {"header":{...,"timestamp"}, "core_metrics":{"status","stationarity_G",...},
    "dynamic_payload":{"kp_index","bz_vector_nt","flare_level","solar_wind_speed_kms",...}}.
    A régebbi, laza alakokat is elfogadja: {"flags":[...]}, {"anomalies":{...}}, lapos kulcsok. 12 óránál régebbi mátrixot nem használ."""
    if not isinstance(m, dict):
        return None, {}, None
    hdr = m.get("header") if isinstance(m.get("header"), dict) else {}
    up = parse_date(str(m.get("updated") or m.get("generated_at") or ""))
    ts = hdr.get("timestamp")
    if up is None and isinstance(ts, (int, float)) and not isinstance(ts, bool) and ts > 1e9:
        up = datetime.fromtimestamp(ts, tz=timezone.utc)
    if up and (t - up) > timedelta(hours=12):
        return None, {"stale": True}, None
    core = m.get("core_metrics") if isinstance(m.get("core_metrics"), dict) else {}
    dyn = m.get("dynamic_payload") if isinstance(m.get("dynamic_payload"), dict) else {}
    m1_status = str(core.get("status") or m.get("status") or "").upper()
    if m1_status in ("INSUFFICIENT_DATA", "NO_DATA"):      # az M1 szerint nincs elég mérés: a hiány nem igazol nyugalmat, ezért nincs használható fizikai állapot
        return None, {"status": m1_status}, None
    an = m.get("anomalies") if isinstance(m.get("anomalies"), dict) else {}
    flags, det = set(), {}
    dflags = dyn.get("flags")
    if isinstance(dflags, list):
        flags |= {str(f).lower() for f in dflags}      # az M1 pontos jelzői (geomagnetic / solar / earthquake / storm)
        det["m1_flags"] = sorted(flags)
    elif str(core.get("status") or m.get("status") or "").upper() == "ANOMALY":
        flags |= {"solar", "geomagnetic"}              # jelzőlista nélküli csomagnál: az M1 saját megítélése, aktív bolygószintű (űr)anomália
        det["status"] = "ANOMALY"
    for f in m.get("flags") or []:
        flags.add(str(f).lower())
    for k in ("earthquake", "solar", "geomagnetic", "storm", "flood"):
        if m.get(k) is True:
            flags.add(k)
    for k, v in an.items():
        k = str(k).lower()
        if v is True or (isinstance(v, dict) and (v.get("active") or v.get("anomaly"))):
            flags.add(k)

    def num(*ks):
        for src in (dyn, an, m):
            for k in ks:
                x = src.get(k)
                if isinstance(x, dict):
                    x = x.get("value", x.get("magnitude", x.get("max")))
                if isinstance(x, (int, float)) and not isinstance(x, bool):
                    return float(x)
        return None
    mag = num("earthquake_max_mag", "eq_max_mag", "magnitude", "earthquake")
    kp = num("kp_index", "kp", "geomagnetic_kp")
    bz = num("bz_vector_nt", "bz_nt", "bz")
    wind = num("solar_wind_speed_kms", "solar_wind_kms")
    gust = num("wind_gust_kmh", "gust_kmh")
    drop = num("pressure_drop_3h", "pressure_drop")
    sol = an.get("solar") if isinstance(an.get("solar"), dict) else {}
    fc = str(dyn.get("flare_level") or m.get("flare_class") or sol.get("class") or "").upper()
    for key, val in (("earthquake_mag", mag), ("kp", kp), ("bz_nt", bz), ("solar_wind_kms", wind), ("gust_kmh", gust)):
        if val is not None:
            det[key] = val
    if mag is not None and mag >= 4.5:
        flags.add("earthquake")
    if (kp is not None and kp >= 5) or (bz is not None and bz <= -10):
        flags.add("geomagnetic")
    if fc[:1] in ("M", "X") or (wind is not None and wind >= 700):
        flags.add("solar")
        det["flare"] = fc
    if (gust is not None and gust >= 60) or (drop is not None and drop >= 6):
        flags.add("storm")
    alias = {"flare": "solar", "solar_flare": "solar", "kp": "geomagnetic", "geomagnetic_storm": "geomagnetic", "quake": "earthquake", "wind": "storm"}
    flags = {alias.get(f, f) for f in flags}
    g = core.get("stationarity_G", m.get("stationarity_G"))
    g = clamp(float(g)) if isinstance(g, (int, float)) and not isinstance(g, bool) else None
    return flags, det, g


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


PER_SOURCE_MAX = 60       # megőrzött cikkek forrásonként (a legfrissebbek): a hírfolyam-ontó források ne nyomják el a többit; a limits.per_source_max felülírja, 0 = kikapcsolva


def merge(old, fresh, t, keep_h, max_n, per_source=None):
    for a in old:
        cs = clean_source(a.get("source"))
        if cs and cs != a.get("source"):
            a["source"] = cs
            a["id"] = article_id(a)
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
    if per_source and per_source > 0:
        cnt, kept = {}, []
        for a in arts:                                   # a legfrissebbek maradnak; a hivatalos közlemények nem számítanak bele
            if a.get("official"):
                kept.append(a)
                continue
            k = fold(a.get("source") or "")
            cnt[k] = cnt.get(k, 0) + 1
            if cnt[k] <= per_source:
                kept.append(a)
        arts = kept
    return arts[:max_n]


def analyze(cfg, arts, profiles, flags, L, g, w):
    thr = cfg["limits"]["cluster_threshold"]
    trust = {f["id"]: f.get("trust", 0.5) for f in cfg["feeds"]}
    for a in arts:
        a["trust"] = trust.get(a.get("feed"), a.get("trust", 0.5))      # a mentett cikkekből a bizalom kimarad: a konfigurációból pótoljuk (stabil újrapontozás)
        ft, s, v = base_scores(a, L, profiles.get(a["source"]), w)
        a["topics"] = topics_of(ft, L)
        if not a.get("geo"):
            a["geo"] = locate(fold(a["title"]), ft, L)
        a["s"], a["v"] = s, v
    n_ev = cluster(arts, L, thr)
    for a in arts:
        a["v"] = clamp(a["v"] + 0.06 * w[3] * min(2, max(0, a.get("event_sources", 1) - 1)))
        apply_truth(a, flags, cfg, L)
        a["g"], a["s"], a["v"] = round(g, 3), round(a["s"], 3), round(a["v"], 3)
        a["atm"] = round(a["g"] * a["s"] * (1 - a["v"]), 4)
    return n_ev


def snapshot(arts, rising, flags, t, g):
    last = [a for a in arts if (a.get("published") or "") >= iso(t - timedelta(hours=24))] or arts
    vals = [a["atm"] for a in last]
    by = {}
    for sc in ("local", "national", "international", "official"):
        x = [a["atm"] for a in last if a["scope"] == sc]
        if x:
            by[sc] = round(sum(x) / len(x), 4)
    return {"t": iso(t), "n": len(last), "mean": round(sum(vals) / len(vals), 4) if vals else 0, "p90": round(pctl(vals, 0.9), 4) if vals else 0,
            "g": round(g, 3), "by_scope": by, "flags": sorted(flags) if flags is not None else None, "rising": [r["term"] for r in rising[:3]]}


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


class BaseMatrixModule(ABC):
    """Az 8x8 mátrix-rendszer modulok közös őse (architekturális szerződés, 1. szabály)."""

    def __init__(self, module_id, version="1.0.0"):
        self.module_id = module_id
        self.version = version

    @abstractmethod
    async def process_payload(self, raw_input):
        """Aszinkron adatfeldolgozás; a P8-busz alap JSON-sémáját adja vissza a dynamic_payload-ban."""

    @abstractmethod
    def update_weights(self, new_weights):
        """Sentinel AI (M8) felület a súlyvektor dinamikus újrahangolásához."""


class MediaZajTwin(BaseMatrixModule):
    """M2 – Media-Zaj Twin. weights_vector = [w_indulat, w_csalogatás, w_bizonyíték, w_megerősítés] (0..2, alap 1,0)."""
    DEFAULT_W = [1.0, 1.0, 1.0, 1.0]

    def __init__(self, cfg):
        super().__init__("M2_MEDIA_ZAJ", "1.3.0")
        self.cfg, self.L, self.w = cfg, Lex(cfg), list(self.DEFAULT_W)

    def update_weights(self, new_weights):
        try:
            v = [clamp(float(x), 0.0, 2.0) for x in new_weights][:4]
        except (TypeError, ValueError):
            return
        if len(v) == 4:
            self.w = v

    def p8(self, t, arts, snap, g_info, flags, rising, official, desc=None):
        """A P8-busz alap sémája; a modul-specifikus adatok kizárólag a dynamic_payload-ban (4. szabály)."""
        last = [a for a in arts if (a.get("published") or "") >= iso(t - timedelta(hours=24))] or arts
        mean = lambda k: round(sum(a[k] for a in last) / len(last), 4) if last else 0.0
        th = self.cfg["thresholds"]
        status = "NOISE_ALERT" if snap["p90"] >= th["high"] else "ELEVATED" if snap["mean"] >= th["mid"] else "NOMINAL"
        top = sorted(last, key=lambda a: -a["atm"])[:5]
        return {"header": {"module_id": self.module_id, "version": self.version, "timestamp": int(t.timestamp()), "p8_signature": "MEDIA_NOISE_TWIN"},
                "core_metrics": {"status": status, "stationarity_G": round(g_info["value"], 3), "noise_S": mean("s"), "validity_V": mean("v"), "atm_score": snap["mean"]},
                "dynamic_payload": {"articles_24h": len(last), "atm_p90": snap["p90"], "atm_by_scope": snap["by_scope"], "g_source": g_info["source"],
                                    "truth_flags": sorted(flags) if flags is not None else None, "official_calm": official.get("calm"),
                                    "rising_terms": [r["term"] for r in rising[:5]],
                                    "top_distorted": [{"id": a["id"], "title": a["title"][:120], "source": a["source"], "atm": a["atm"]} for a in top],
                                    "retention_policy": {"per_source_max": self.cfg["limits"].get("per_source_max", PER_SOURCE_MAX), "note": "forrásonként a legfrissebb N cikk marad; az ezt megelőző napi összesítők más mintából készültek"},
                                    **({"descriptive": desc} if desc else {})},
                "weights_vector": [round(x, 3) for x in self.w]}

    async def process_payload(self, raw):
        cfg, L, t = self.cfg, self.L, raw["now"]
        flags, fdet, g_m = truth_flags(raw.get("truth"), t)
        if flags is None:
            g_info = {"value": 1.0, "source": "default"}                      # nincs fizikai mérés: nyugodtnak tételezzük fel
        elif g_m is not None:
            g_info = {"value": g_m, "source": "M1"}
        else:
            g_info = {"value": 1.0 if not flags else max(0.1, 1 - 0.3 * len(flags)), "source": "derived"}
        known = {a["id"] for a in raw["old"]}
        arts = merge(raw["old"], raw["fresh"], t, cfg["limits"]["keep_hours"], cfg["limits"]["max_articles"], cfg["limits"].get("per_source_max", PER_SOURCE_MAX))
        new_ids = {a["id"] for a in arts if a["id"] not in known}
        n_ev = analyze(cfg, arts, raw["profiles"], flags, L, g_info["value"], self.w)
        m1_dyn = (raw.get("truth") or {}).get("dynamic_payload") if (flags is not None and isinstance(raw.get("truth"), dict)) else None
        desc = describe_articles(arts, L, t, m1_dyn if isinstance(m1_dyn, dict) else None, fin_rates(raw.get("fin"), t))
        update_profiles(raw["profiles"], [a for a in arts if not a.get("profiled")])
        rising, warming = update_trends(raw["trends"], [a for a in arts if a["id"] in new_ids], L, t)
        snap = snapshot(arts, rising, flags, t, g_info["value"])
        return {"articles": arts, "new_ids": new_ids, "events": n_ev, "g": g_info, "flags": flags, "flags_detail": fdet, "rising": rising,
                "warming": warming, "snapshot": snap, "p8": self.p8(t, arts, snap, g_info, flags, rising, raw["official"], desc)}


async def run_async(force=False):
    cfg = jload(ROOT / "config" / "sources.json")
    t = now()
    mod = MediaZajTwin(cfg)
    wv = jload(MET / "weights_M2.json")                    # M8 Sentinel: dinamikus súlyvektor (nem kötelező)
    mod.update_weights(wv.get("weights_vector") if isinstance(wv, dict) else wv)
    errors = {}
    state = jload(DATA / "state.json", {"signature": "", "cool": {}, "last_hist": ""})
    old = (jload(DATA / "articles.json", {}) or {}).get("articles", [])
    profiles = jload(MET / "source_profiles.json", {}) or {}
    trends = jload(MET / "trends.json", {}) or {}
    local_truth = jload(MET / "environment_truth_matrix.json")
    fin = await refresh_m5(cfg, errors)                     # az M5 hivatalos árfolyamai (csak jelentés-jellegű ellenőrzéshez); hiány esetén kimarad
    m1 = await refresh_m1(cfg, errors)                      # élő M1-csomag; ha nem érhető el, a helyi másolat (a 12 órás elavulási szabállyal)
    truth, origin = (m1, "fetched") if m1 is not None else (local_truth, "local" if local_truth else "none")
    schema_changed = state.get("schema") != "v39"
    if schema_changed:                       # a G/S/V jelentése megváltozott: a régi profilok nem hasonlíthatók, újratanulás a megőrzött cikkekből
        profiles = {}
        for a in old:
            a.pop("profiled", None)
            a.pop("z", None)
    fresh, (off_arts, official) = await asyncio.gather(collect(cfg, errors), collect_official(cfg, errors, t))
    fresh += off_arts
    if not fresh and errors and not old:
        print("Nincs elérhető forrás:", errors)
    res = await mod.process_payload({"now": t, "old": old, "fresh": fresh, "profiles": profiles, "trends": trends, "official": official, "truth": truth, "fin": fin})
    p8, c8 = res["p8"], res["p8"]["core_metrics"]
    prev_p8 = jload(MET / "media_noise_matrix.json")
    p8["dynamic_payload"].update(fold_retention((prev_p8 or {}).get("dynamic_payload") if isinstance(prev_p8, dict) else None,
                                                {"t": iso(t), "hour": iso(t)[:13], "G": c8["stationarity_G"], "S": c8["noise_S"], "V": c8["validity_V"], "ATM": c8["atm_score"]}))
    arts, new_ids, flags, g_info, rising, warming, snap = res["articles"], res["new_ids"], res["flags"], res["g"], res["rising"], res["warming"], res["snapshot"]
    sig_src = json.dumps([[a["id"], round(a["atm"], 2)] for a in arts if (a.get("published") or "") >= iso(t - timedelta(hours=24))]
                         + [snap["flags"], snap["rising"], official.get("calm"), round(g_info["value"], 2)], sort_keys=True)
    sig = hashlib.sha1(sig_src.encode()).hexdigest()
    changed = force or schema_changed or sig != state.get("signature") or not (DATA / "articles.json").exists()
    alerts = build_alerts(cfg, arts, rising, official, new_ids) if new_ids or official.get("calm") is False else []
    meta = {"version": cfg["version"], "generated_at": iso(t), "region": cfg["region"], "thresholds": cfg["thresholds"], "events": res["events"],
            "errors": errors, "g": g_info, "weights": [round(x, 3) for x in mod.w],
            "truth": {"available": flags is not None, "flags": sorted(flags) if flags is not None else None, "detail": res["flags_detail"], "origin": origin},
            "official": {"calm": official.get("calm"), "excerpt": official.get("excerpt", "")[:300]}, "rising": rising, "warming_up": warming}
    if changed:
        jsave(DATA / "articles.json", {"meta": meta, "articles": [{k: v for k, v in a.items() if k != "trust"} for a in arts]})
        jsave(MET / "source_profiles.json", profiles)
        jsave(MET / "trends.json", trends)
        jsave(MET / "media_noise_matrix.json", res["p8"], pretty=True)
        if m1 is not None:
            jsave(MET / "environment_truth_matrix.json", m1, pretty=True)      # a busz pillanatképe (a változással együtt commitolódik)
        hist = jload(MET / "atm_history.json", {"points": []})
        pts = hist.get("points", [])
        last_t = parse_date(state.get("last_hist")) or datetime(1970, 1, 1, tzinfo=timezone.utc)
        if pts == [] or sig != state.get("signature") or t - last_t >= timedelta(hours=cfg["limits"]["history_heartbeat_h"]):
            pts.append(snap)
            state["last_hist"] = iso(t)
        jsave(MET / "atm_history.json", {"points": pts[-cfg["limits"]["history_max"]:]})
        state["signature"] = sig
        state["schema"] = "v39"
        jsave(DATA / "state.json", state)
    outbox = os.environ.get("MNT_OUTBOX") or "/tmp/mnt_outbox.json"
    jsave(outbox, alerts)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write("changed=%s\n" % ("true" if changed else "false"))
    print("MNT v40: %d cikk (%d új), %d esemény, G %.2f (%s), ATM átlag %.3f, p90 %.3f, hibás forrás: %s, fizikai mérés: %s, riasztás: %d, változás: %s" % (
        len(arts), len(new_ids), res["events"], g_info["value"], g_info["source"], snap["mean"], snap["p90"], list(errors) or "nincs",
        "van" if flags is not None else "nincs", len(alerts), changed))
    return {"changed": changed, "alerts": alerts, "articles": arts, "snapshot": snap, "errors": errors, "p8": res["p8"], "g": g_info}


def run(force=False):
    return asyncio.run(run_async(force))


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
