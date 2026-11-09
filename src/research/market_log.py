"""Passzív piaci napló és önértékelés (kutatási eszköz, nem befektetési tanács).

Mit csinál (a felületet és a pontozást NEM érinti):
 1) naponta cégenként összegzi a cégekről szóló híreket (darab, átlagos ATM/S, a cím által állított irány),
 2) legfeljebb néhány óránként letölti a napi záróárakat (stooq.com, kulcs nélkül),
 3) kiértékeli, hogy az árfolyam igazolja-e a határozott piaci állításokat (lásd evaluate.py).
Az eredmény az atm_history.json "research" kulcsában van; az állapot a Diagnosztika másolása gombbal olvasható.
"""
from __future__ import annotations

import copy
import csv
import io
import re
from datetime import timedelta

from src.research.evaluate import evaluate
from src.utils.network import make_session
from src.utils.time_helper import now_utc, parse_iso, to_iso_utc


def _rx(words: list[str]):
    if not words:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(w) for w in words) + r")(?!\w)", re.IGNORECASE | re.UNICODE)


def _direction(title: str, up, down) -> int:
    u = bool(up and up.search(title))
    d = bool(down and down.search(title))
    return 1 if u and not d else -1 if d and not u else 0


def build_companies(rc: dict) -> list[dict]:
    bench = rc.get("benchmarks", {})
    out = []
    for c in rc.get("companies", []):
        out.append({"id": c["id"], "symbol": c["symbol"], "bench_symbol": bench.get(c.get("bench"), c.get("bench")),
                    "rx": _rx(c.get("names", []))})
    return out


def news_daily(items: list[dict], comps: list[dict], rc: dict, now) -> tuple[dict, dict]:
    """(napi összegzés a TELJESEN lefedett napokra, a mostani egyezések összesítője)."""
    up, down = _rx(rc.get("up_words", [])), _rx(rc.get("down_words", []))
    pubs = [parse_iso(i["published"]) for i in items if i.get("published")]
    if not pubs:
        return {}, {"n": 0, "top": {}}
    oldest_day = min(pubs).date()
    today = now.date()
    agg: dict = {}
    now_hits: dict = {}
    for it in items:
        if not it.get("published"):
            continue
        day = parse_iso(it["published"]).date()
        title = it.get("title", "")
        for c in comps:
            if c["rx"] is None or not c["rx"].search(title):
                continue
            now_hits[c["id"]] = now_hits.get(c["id"], 0) + 1
            if not (oldest_day < day < today):  # az első (részleges) és a mai (még tartó) nap kimarad
                continue
            a = agg.setdefault(day.isoformat(), {}).setdefault(c["id"], {"n": 0, "atm": 0.0, "s": 0.0, "claim_n": 0, "claim_sum": 0})
            a["n"] += 1
            a["atm"] += float(it.get("ATM", 0))
            a["s"] += float(it.get("S", 0))
            dirn = _direction(title, up, down)
            if dirn:
                a["claim_n"] += 1
                a["claim_sum"] += dirn
    out = {}
    for day, per in agg.items():
        out[day] = {}
        for cid, a in per.items():
            out[day][cid] = {"n": a["n"], "mean_atm": round(a["atm"] / a["n"], 1), "mean_s": round(a["s"] / a["n"], 3),
                             "claim_n": a["claim_n"], "claim_net": round(a["claim_sum"] / a["claim_n"], 2) if a["claim_n"] else 0}
    top = dict(sorted(now_hits.items(), key=lambda x: x[1], reverse=True)[:4])
    return out, {"n": sum(now_hits.values()), "top": top}


def fetch_stooq(session, symbol: str, d1, d2) -> dict:
    url = f"https://stooq.com/q/d/l/?s={symbol}&d1={d1:%Y%m%d}&d2={d2:%Y%m%d}&i=d"
    r = session.get(url)
    r.raise_for_status()
    txt = r.text.strip()
    if not txt.lower().startswith("date,"):
        raise ValueError("nincs adat")
    out = {}
    for row in csv.DictReader(io.StringIO(txt)):
        try:
            out[row["Date"]] = float(row["Close"])
        except (KeyError, ValueError, TypeError):
            continue
    if not out:
        raise ValueError("üres válasz")
    return out


def update(prev: dict | None, items: list[dict], cfg: dict, now=None, fetch=None) -> dict | None:
    rc = cfg.get("research") or {}
    if not rc.get("enabled"):
        return prev
    now = now or now_utc()
    res = copy.deepcopy(prev) if prev else {}
    res.setdefault("version", 1)
    res.setdefault("news_daily", {})
    res.setdefault("prices", {})
    st = res.setdefault("status", {})
    comps = build_companies(rc)

    # 1) hírnapló: nagyobb mintájú változat felülírja a kisebbet (az elöregedő napok részlegesek)
    nd, now_hits = news_daily(items, comps, rc, now)
    for day, per in nd.items():
        for cid, rec in per.items():
            old = res["news_daily"].setdefault(day, {}).get(cid)
            if old is None or rec["n"] >= old["n"]:
                res["news_daily"][day][cid] = rec
    st["match_now"] = now_hits

    # 2) árfolyam: legfeljebb fetch_hours óránként
    last = parse_iso(st["price_attempt"]) if st.get("price_attempt") else None
    if last is None or now - last >= timedelta(hours=rc.get("fetch_hours", 6)):
        fetch = fetch or (lambda sym, d1, d2: fetch_stooq(make_session(retries=2, backoff=1.0, timeout=12), sym, d1, d2))
        d2 = now.date()
        d1 = d2 - timedelta(days=rc.get("lookback_days", 150))
        symbols = sorted({c["symbol"] for c in comps} | {c["bench_symbol"] for c in comps if c["bench_symbol"]})
        ok, failed = [], {}
        for sym in symbols:
            try:
                res["prices"].setdefault(sym, {}).update(fetch(sym, d1, d2))
                ok.append(sym)
            except Exception as exc:  # egy cég hibája nem állítja meg a többit
                failed[sym] = str(exc)[:40]
        st["price_attempt"] = to_iso_utc(now)
        st["ok"], st["failed"] = ok, failed

    # 3) karbantartás + értékelés
    keep = (now.date() - timedelta(days=rc.get("retain_days", 400))).isoformat()
    for sym in res["prices"]:
        res["prices"][sym] = {d: v for d, v in res["prices"][sym].items() if d >= keep}
    res["news_daily"] = {d: v for d, v in res["news_daily"].items() if d >= keep}
    st["news_days"] = len(res["news_daily"])
    st["price_last"] = max((max(p) for p in res["prices"].values() if p), default=None)
    st["eval"] = evaluate(res, comps, rc)
    return res
