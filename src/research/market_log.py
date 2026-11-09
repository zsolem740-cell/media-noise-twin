"""Passzív piaci napló és önértékelés (kutatási eszköz, nem befektetési tanács).

Mit csinál (a felületet és a pontozást NEM érinti):
 1) naponta cégenként összegzi a cégekről szóló híreket (darab, átlagos ATM/S, a cím által állított irány),
 2) legfeljebb néhány óránként letölti a napi záróárakat (forráslánc: Yahoo grafikon-végpont kulcs nélkül,
    majd Stooq, ha van hozzá kulcs; a Stooq 2026 márciusától kulcs nélkül nem ad adatot),
 3) kiértékeli, hogy az árfolyam igazolja-e a határozott piaci állításokat (lásd evaluate.py).
Az eredmény az atm_history.json "research" kulcsában van; az állapot a Diagnosztika másolása gombbal olvasható.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

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


def _bench_syms(rc: dict, bench: str) -> dict:
    b = (rc.get("benchmarks") or {}).get(bench, {})
    return {"stooq": b} if isinstance(b, str) else dict(b)


def build_companies(rc: dict) -> list[dict]:
    out = []
    for c in rc.get("companies", []):
        out.append({"id": c["id"], "key": c["id"], "bench": c.get("bench"), "bench_key": f"bench_{c.get('bench')}",
                    "syms": {"yahoo": c.get("yahoo"), "stooq": c.get("symbol")}, "rx": _rx(c.get("names", []))})
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


YAHOO_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def fetch_yahoo(session, symbol: str, d1, d2) -> dict:
    p1 = int(datetime(d1.year, d1.month, d1.day, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(d2.year, d2.month, d2.day, tzinfo=timezone.utc).timestamp()) + 86400
    r = session.get("https://query1.finance.yahoo.com/v8/finance/chart/" + quote(symbol, safe=""),
                    params={"period1": p1, "period2": p2, "interval": "1d"},
                    headers={"User-Agent": YAHOO_UA, "Accept": "application/json"})
    if r.status_code != 200:
        raise ValueError(f"HTTP {r.status_code}")
    chart = r.json().get("chart") or {}
    result = chart.get("result")
    if not result:
        raise ValueError(str((chart.get("error") or {}).get("code") or "üres")[:18])
    r0 = result[0]
    ts = r0.get("timestamp") or []
    closes = (((r0.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
    off = int((r0.get("meta") or {}).get("gmtoffset") or 0)  # a tőzsde helyi napja szerint
    out = {}
    for t, c in zip(ts, closes):
        if c is not None:
            out[datetime.fromtimestamp(t + off, timezone.utc).date().isoformat()] = float(c)
    if not out:
        raise ValueError("üres válasz")
    return out


def fetch_stooq(session, symbol: str, d1, d2, apikey: str = "") -> dict:
    if not apikey:
        raise ValueError("nincs kulcs")
    r = session.get("https://stooq.com/q/d/l/", params={"s": symbol, "d1": f"{d1:%Y%m%d}", "d2": f"{d2:%Y%m%d}", "i": "d", "apikey": apikey})
    r.raise_for_status()
    txt = r.text.strip()
    if not txt.lower().startswith("date,"):
        low = txt.lower()
        raise ValueError("kulcs hibás" if "apikey" in low else "napi limit" if "limit" in low else "nincs adat")
    out = {}
    for row in csv.DictReader(io.StringIO(txt)):
        try:
            out[row["Date"]] = float(row["Close"])
        except (KeyError, ValueError, TypeError):
            continue
    if not out:
        raise ValueError("üres válasz")
    return out


def _short(exc: Exception) -> str:
    m = str(exc)
    if "429" in m:
        return "429"
    if "timed out" in m.lower() or "timeout" in m.lower():
        return "időtúllépés"
    return m.replace("HTTP ", "")[:14]


def _default_fetch(rc: dict):
    session = make_session(retries=1, backoff=1.0, timeout=12)
    apikey = rc.get("stooq_apikey") or os.environ.get("STOOQ_APIKEY", "")

    def f(provider, sym, d1, d2):
        if provider == "yahoo":
            return fetch_yahoo(session, sym, d1, d2)
        if provider == "stooq":
            return fetch_stooq(session, sym, d1, d2, apikey)
        raise ValueError("ismeretlen forrás")
    return f


def update(prev: dict | None, items: list[dict], cfg: dict, now=None, fetch=None, pause: float = 0.8) -> dict | None:
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

    # 2) árfolyam: legfeljebb fetch_hours óránként (hiba esetén óránként), a beállítás változásakor azonnal
    providers = rc.get("providers") or ["yahoo", "stooq"]
    targets = {c["key"]: c["syms"] for c in comps}
    for bname in sorted({c["bench"] for c in comps if c["bench"]}):
        targets[f"bench_{bname}"] = _bench_syms(rc, bname)
    has_key = bool(rc.get("stooq_apikey") or os.environ.get("STOOQ_APIKEY"))
    sig = hashlib.sha1(json.dumps([providers, sorted((k, sorted(v.items())) for k, v in targets.items()), has_key], default=str).encode()).hexdigest()[:10]
    last = parse_iso(st["price_attempt"]) if st.get("price_attempt") else None
    wait = timedelta(hours=min(rc.get("fetch_hours", 6), 1)) if st.get("failed") else timedelta(hours=rc.get("fetch_hours", 6))
    if last is None or st.get("fetch_sig") != sig or now - last >= wait:
        fetch = fetch or _default_fetch(rc)
        d2 = now.date()
        d1 = d2 - timedelta(days=rc.get("lookback_days", 150))
        ok, failed, via = [], {}, {}
        for key, syms in sorted(targets.items()):
            errs = []
            for prov in providers:
                sym = syms.get(prov)
                if not sym:
                    errs.append(f"{prov[0]}:–")
                    continue
                try:
                    res["prices"].setdefault(key, {}).update(fetch(prov, sym, d1, d2))
                except Exception as exc:  # egy cég hibája nem állítja meg a többit
                    errs.append(f"{prov[0]}:{_short(exc)}")
                else:
                    ok.append(key)
                    via[prov] = via.get(prov, 0) + 1
                    break
            else:
                failed[key] = "|".join(errs)[:40]
            if pause:
                time.sleep(pause)
        st.update({"price_attempt": to_iso_utc(now), "fetch_sig": sig, "ok": ok, "failed": failed, "via": via})

    # 3) karbantartás + értékelés
    keep = (now.date() - timedelta(days=rc.get("retain_days", 400))).isoformat()
    for sym in res["prices"]:
        res["prices"][sym] = {d: v for d, v in res["prices"][sym].items() if d >= keep}
    res["news_daily"] = {d: v for d, v in res["news_daily"].items() if d >= keep}
    st["news_days"] = len(res["news_daily"])
    st["price_last"] = max((max(p) for p in res["prices"].values() if p), default=None)
    st["eval"] = evaluate(res, comps, rc)
    return res
