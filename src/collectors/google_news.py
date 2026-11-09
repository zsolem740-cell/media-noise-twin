"""Hírgyűjtő: Google News RSS + közvetlen RSS + hivatalos oldalak (HungaroMet).

Futtatás:  python -m src.collectors.google_news
Kimenet:   data/raw/latest.json (minden futásnál felülíródik; a történetet az ATM motor építi).
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse
from zoneinfo import ZoneInfo

import feedparser
from bs4 import BeautifulSoup

from src.utils.domains import canon_domain
from src.utils.config import load_config
from src.utils.network import make_session
from src.utils.text_cleaner import norm_title, strip_html, strip_source_suffix
from src.utils.time_helper import now_utc, to_iso_utc

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "sources.json"
OUT = ROOT / "data" / "raw" / "latest.json"
FEED = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"
TOP = "https://news.google.com/rss?hl={hl}&gl={gl}&ceid={ceid}"
STAMP = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})\.\s*(\d{1,2}):(\d{2})")
NEGATIVE = ("nem várható", "nincs érvényben")


def item_id(link: str, title: str, source: str) -> str:
    return hashlib.sha1((link or f"{title}|{source}").encode("utf-8")).hexdigest()[:16]


def domain_of(url: str | None) -> str:
    return canon_domain(urlparse(url or "").netloc.lower())


def in_geofence(text: str, keywords: list[str]) -> bool:
    low = text.lower()
    return any(k in low for k in keywords)


def feed_urls(region: dict) -> list[dict]:
    """[{'url', 'name'}] – a 'name' csak a közvetlen RSS-nél van megadva."""
    out = []
    if region.get("top"):
        out.append({"url": TOP.format(**region["lang"]), "name": None})
    for q in region["queries"]:
        out.append({"url": FEED.format(q=quote_plus(q), **region["lang"]), "name": None})
    for f in region.get("feeds", []):
        out.append({"url": f["url"], "name": f.get("name") or domain_of(f["url"])})
    return out


def parse_feed(content: bytes, region: dict, name: str | None = None) -> list[dict]:
    parsed = feedparser.parse(content)
    items = []
    for e in parsed.entries:
        src = e.get("source") or {}
        link = e.get("link", "")
        if name:  # közvetlen RSS: a link a valódi cikk
            source_name, domain = name, domain_of(link)
            title = strip_html(e.get("title"))
        else:     # Google News: a forrás a <source> elemből jön
            source_name, domain = src.get("title", ""), domain_of(src.get("href"))
            title = strip_source_suffix(strip_html(e.get("title")), source_name)
        summary = strip_html(e.get("summary"))
        if region.get("geofence") and not in_geofence(f"{title} {summary}", region["geofence"]):
            continue
        items.append({
            "id": item_id(link, title, source_name),
            "region": region["code"],
            "title": title,
            "summary": summary,
            "link": link,
            "source": source_name,
            "source_domain": domain,
            "published": to_iso_utc(e.get("published_parsed")),
        })
    return items


def parse_official(html: bytes | str, page: dict, now: datetime | None = None) -> dict | None:
    """HungaroMet szöveges figyelmeztetés → egy hír. Hibás/ismeretlen oldalnál None."""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    lines = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]
    k = next((i for i, l in enumerate(lines) if l.lower().startswith("szöveges figyelmeztető előrejelzés")), None)
    if k is None or k + 1 >= len(lines):
        return None
    header = lines[k + 1]
    content, stamp = [], None
    for l in lines[k + 2:k + 8]:
        m = STAMP.search(l)
        if m:
            stamp = m
            break
        content.append(l)
    county = None
    if page.get("county"):
        for l in reversed(lines[max(0, k - 4):k]):
            if re.search(r"nincs érvényben|figyelmeztetés|riasztás", l, re.I):
                county = l
                break
    body = county or " ".join(content)
    if not body:
        return None
    if stamp:
        y, mo, d, h, mi = map(int, stamp.groups())
        dt = datetime(y, mo, d, h, mi, tzinfo=ZoneInfo("Europe/Budapest")).astimezone(timezone.utc)
    else:
        dt = now or now_utc()
    iso = to_iso_utc(dt)
    title = f"{page['name']} – {page['scope']}: {body}"[:240]
    alert = len(body) >= 20 and not any(n in body.lower() for n in NEGATIVE)
    return {
        "id": item_id(page["url"], title, iso),
        "region": page["region"],
        "title": title,
        "summary": header,
        "link": page["url"],
        "source": page["name"],
        "source_domain": domain_of(page["url"]),
        "published": iso,
        "alert": alert,
        "official": True,
    }


def dedupe(items: list[dict]) -> list[dict]:
    """Ugyanaz a cím ugyanattól a forrástól: a közvetlen link nyer a Google-átirányító fölött."""
    best: dict = {}
    for it in items:
        key = (it["source_domain"], norm_title(it["title"]))
        cur = best.get(key)
        if cur is None or ("news.google.com" in cur["link"] and "news.google.com" not in it["link"]):
            best[key] = it
    return list(best.values())


def collect(cfg: dict, session) -> list[dict]:
    seen: dict[str, dict] = {}
    for region in cfg["regions"]:
        before = len(seen)
        for f in feed_urls(region):
            try:
                resp = session.get(f["url"])
                resp.raise_for_status()
            except Exception as exc:  # egy hibás lekérés ne állítsa le az egészet
                print(f"[WARN] {region['code']} {f['url'][:90]}: {exc}", file=sys.stderr)
                continue
            for it in parse_feed(resp.content, region, f["name"]):
                seen.setdefault(it["id"], it)
        print(f"{region['code']}: {len(seen) - before} új elem")
    items = dedupe(list(seen.values()))
    for page in cfg.get("official_pages", []):
        try:
            resp = session.get(page["url"])
            resp.raise_for_status()
            it = parse_official(resp.content, page)
            if it:
                items.append(it)
                print(f"hivatalos: {it['title'][:90]} (riasztás: {it['alert']})")
            else:
                print(f"[WARN] hivatalos oldal nem értelmezhető: {page['url']}", file=sys.stderr)
        except Exception as exc:
            print(f"[WARN] hivatalos oldal {page['url'][:70]}: {exc}", file=sys.stderr)
    return items


def main() -> int:
    cfg, status = load_config()
    if status["warning"]:
        print(f"[WARN] config/user.json hibás, az alapbeállítás érvényes: {status['warning']}", file=sys.stderr)
    elif status["user"]:
        print(f"saját beállítás betöltve: {', '.join(status['applied'])}")
    items = collect(cfg, make_session())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fetched_at": to_iso_utc(now_utc()), "count": len(items), "items": items}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(items)} elem mentve -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
