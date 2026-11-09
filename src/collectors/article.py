"""Cikkszöveg-elemzés: az új hírek bevezetőjét letölti, jeleket nyer ki belőle (a szöveget nem tároljuk).

Futtatás:  python -m src.collectors.article   (a gyűjtő után, az ATM motor előtt)
A Google News átirányító linkjei gyakran nem oldódnak fel; ilyenkor a hír változatlanul marad.
Soha nem állítja meg a folyamatot: hiba esetén kilép 0-val.
"""
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from src.utils.config import load_config
from src.utils.network import make_session
from src.utils.text_cleaner import clickbait_hits, exclamation_count

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "sources.json"
RAW = ROOT / "data" / "raw" / "latest.json"
HISTORY = ROOT / "data" / "metrics" / "atm_history.json"
WORD = re.compile(r"[^\W\d_]{4,}", re.UNICODE)


def stems(text: str) -> set[str]:
    return {w[:6] for w in WORD.findall(text.lower())}


def lead_text(html: bytes | str, max_chars: int = 1200) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript"]):
        t.decompose()
    node = soup.find("article") or soup.find("main") or soup.body or soup
    paras = [p.get_text(" ", strip=True) for p in node.find_all("p")]
    return " ".join(p for p in paras if len(p) >= 60)[:max_chars]


def analyze(title: str, lead: str) -> dict:
    t, b = stems(title), stems(lead)
    ov = round(len(t & b) / len(t), 3) if len(t) >= 3 else None
    return {"ok": True, "len": len(lead), "kw": clickbait_hits(lead), "ex": exclamation_count(lead), "ov": ov}


def fetch_one(session, item: dict, cfg: dict) -> dict:
    try:
        r = session.get(item["link"], timeout=cfg["timeout_s"], allow_redirects=True)
        host = urlparse(r.url).netloc.lower()
        if r.status_code != 200 or host.endswith("google.com") or "html" not in r.headers.get("content-type", ""):
            return {"ok": False}
        lead = lead_text(r.content[:400_000], cfg["lead_chars"])
        return analyze(item["title"], lead) if len(lead) >= 200 else {"ok": False}
    except Exception:
        return {"ok": False}


def enrich(items: list[dict], known_ids: set[str], cfg: dict) -> int:
    cands = [i for i in items if i["id"] not in known_ids and "body" not in i
             and not i.get("official") and str(i.get("link", "")).startswith("http")]
    cands.sort(key=lambda i: i.get("published") or "", reverse=True)
    cands = cands[: cfg["max_per_run"]]
    if not cands:
        return 0
    session = make_session(retries=1, backoff=0.5, timeout=cfg["timeout_s"])
    deadline = time.time() + cfg["deadline_s"]
    ex = ThreadPoolExecutor(max_workers=cfg["workers"])
    futs = {ex.submit(fetch_one, session, it, cfg): it for it in cands}
    done = 0
    try:
        for f in as_completed(futs, timeout=max(1, deadline - time.time())):
            futs[f]["body"] = f.result()
            done += 1
    except Exception:
        pass
    ex.shutdown(wait=False, cancel_futures=True)
    return done


def main() -> int:
    try:
        cfg = load_config()[0]["article"]
        raw = json.loads(RAW.read_text(encoding="utf-8"))
        known = {i["id"] for i in json.loads(HISTORY.read_text(encoding="utf-8"))["items"]} if HISTORY.exists() else set()
        n = enrich(raw["items"], known, cfg)
        RAW.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
        ok = sum(1 for i in raw["items"] if (i.get("body") or {}).get("ok"))
        print(f"Cikkszöveg: {n} kísérlet, {ok} sikeres")
    except Exception as exc:
        print(f"[WARN] cikkszöveg-elemzés kihagyva: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
