"""P8 ATM motor.

  scoring.mode = "sqrt_int" (alapértelmezett):  ATM = round( sqrt( G% · S% · (100 − V%) ) )   – egész százalékokkal, egész eredmény
  scoring.mode = "classic":                      ATM = G · S · (1 − V)                          – a régi, tizedes képlet

V_i  valóságindex: forrás-típus (előzetes) + a forrás tanult profilja
S_i  szenzációszint: cím/kivonat szabályai + a cikk szövegéből kinyert jelek
G_k  geo-kulturális súly (régió)

Futtatás:  python -m src.core.atm_engine
Bemenet:   data/raw/latest.json    Kimenet: data/metrics/atm_history.json
"""
import json
import math
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np

from src.core import insights
from src.utils.domains import canon_domain
from src.utils.config import load_config
from src.utils import geo
from src.utils.text_cleaner import CLICKBAIT, caps_ratio, clickbait_hits, exclamation_count, norm_title
from src.utils.time_helper import now_utc, parse_iso, to_iso_utc

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "sources.json"
RAW = ROOT / "data" / "raw" / "latest.json"
HISTORY = ROOT / "data" / "metrics" / "atm_history.json"


def clamp(x: float, a: float, b: float) -> float:
    return max(a, min(b, x))


def tier_of(domain: str, trust: dict) -> str:
    """Az első egyező szint neve (sorrend a sources.json-ban), egyébként 'default'."""
    for name, tier in trust.items():
        if name == "default" or not isinstance(tier, dict):
            continue
        for d in tier["domains"]:
            if domain == d or domain.endswith("." + d):
                return name
    return "default"


def reality_index(domain: str, trust: dict) -> float:
    name = tier_of(domain, trust)
    return trust["default"] if name == "default" else trust[name]["value"]


def learned_v(v0: float, tier: str, profile: dict | None, gmean: float) -> float:
    """A V tanul: a megszokottnál zajosabb forrás hitelessége csökken (Bayes-féle zsugorítással)."""
    if tier == "official" or not profile or profile["n"] < 20:
        return v0
    shrink = profile["n"] / (profile["n"] + 30)
    delta = clamp(-0.8 * (profile["mS"] - gmean) * shrink, -0.15, 0.15)
    return clamp(v0 + delta, 0.2, 0.97)


def sensation_level(title: str, summary: str = "") -> float:
    """S0 in [0,1]: kulcsszavak (50%), felkiáltójelek (25%), csupa nagybetűs szavak (25%)."""
    text = f"{title} {summary}".strip()
    kw = min(clickbait_hits(text) / 3.0, 1.0)
    ex = min(exclamation_count(text) / 2.0, 1.0)
    caps = min(caps_ratio(text) / 0.3, 1.0)
    return float(np.clip(0.5 * kw + 0.25 * ex + 0.25 * caps, 0.0, 1.0))


def body_evidence(body: dict | None) -> float:
    """Extra bizonyíték a cikk szövegéből (csak növelhet): kulcsszavak, felkiáltójelek, cím–szöveg eltérés."""
    if not body or not body.get("ok"):
        return 0.0
    s_body = 0.7 * min(body.get("kw", 0) / 4, 1) + 0.3 * min(body.get("ex", 0) / 3, 1)
    ov = body.get("ov")
    mismatch = 0.0 if ov is None else clamp((0.5 - ov) / 0.5, 0.0, 1.0)
    return 0.15 * s_body + 0.15 * mismatch


def half_up(x: float) -> int:
    """Kerekítés .5-nél felfelé – a JS Math.floor(x + 0.5) párja (a Python round() páros szám felé kerekítene)."""
    return int(math.floor(x + 0.5))


SCALE = {"classic": {"ref": 0.55, "cap": 0.6, "margin": 0.05}, "sqrt_int": {"ref": 742, "cap": 1000, "margin": 20}}


def scoring_mode(cfg: dict) -> str:
    mode = cfg.get("scoring", {}).get("mode", "sqrt_int")
    return mode if mode in SCALE else "sqrt_int"


def atm_value(g: float, s: float, v: float, mode: str = "sqrt_int"):
    if mode == "sqrt_int":
        return half_up(math.sqrt(half_up(g * 100) * half_up(s * 100) * (100 - half_up(v * 100))))
    return round(float(g * s * (1.0 - v)), 4)


def scale_floor(x: float, mode: str):
    """A küszöbök alsó korlátját a klasszikus egységben adjuk meg (0,05 / 0,15); egész módban átszámoljuk."""
    return half_up(math.sqrt(x * 1_000_000)) if mode == "sqrt_int" else x


def score_item(item: dict, cfg: dict, weights: dict, profiles: dict, gmean: float) -> dict:
    mode = scoring_mode(cfg)
    domain = item.get("source_domain", "")
    tier = tier_of(domain, cfg["trust"])
    v0 = reality_index(domain, cfg["trust"])
    v = learned_v(v0, tier, profiles.get(domain or "?"), gmean)
    s0 = sensation_level(item["title"], item.get("summary", ""))
    s = float(clamp(s0 + body_evidence(item.get("body")), 0.0, 1.0))
    g = weights.get(item["region"], 0.5)
    return {**item, "V0": round(v0, 3), "V": round(v, 3), "S0": round(s0, 3), "S": round(s, 3), "G": g,
            "ATM": atm_value(g, round(s, 3), round(v, 3), mode)}


def dedupe_items(items: list[dict]) -> list[dict]:
    """Ugyanaz a cím ugyanattól a forrástól egyszer szerepeljen; a közvetlen link és a szöveges elemzés nyer."""
    def rank(x):
        return (0 if "news.google.com" in x.get("link", "") else 1, 1 if (x.get("body") or {}).get("ok") else 0)
    best: dict = {}
    for it in items:
        key = (it["id"],) if it.get("official") else (it.get("source_domain", ""), norm_title(it["title"]))
        cur = best.get(key)
        if cur is None or rank(it) > rank(cur):
            best[key] = it
    return list(best.values())


def thresholds(items: list[dict], cfg: dict) -> dict:
    """Színküszöbök az adatból (percentilis), alsó korláttal, hogy a nyugodt nap ne legyen piros."""
    t = cfg.get("thresholds", {})
    mode = scoring_mode(cfg)
    atms = [i["ATM"] for i in items]
    if not atms:
        return {"low": scale_floor(0.10, mode), "high": scale_floor(0.25, mode)}
    low = max(scale_floor(t.get("low_floor", 0.05), mode), float(np.percentile(atms, t.get("low_pct", 0.70) * 100)))
    high = max(scale_floor(t.get("high_floor", 0.15), mode), float(np.percentile(atms, t.get("high_pct", 0.95) * 100)))
    high = max(high, low + SCALE[mode]["margin"])
    if mode == "sqrt_int":
        return {"low": half_up(low), "high": half_up(high)}
    return {"low": round(low, 3), "high": round(high, 3)}


def summarize(items: list[dict]) -> dict:
    if not items:
        return {"n_items": 0, "atm_mean": 0.0, "atm_p90": 0.0, "by_region": {}, "top_noise": []}
    a = np.array([i["ATM"] for i in items])
    by_region = {}
    for code in sorted({i["region"] for i in items}):
        sub = [i for i in items if i["region"] == code]
        by_region[code] = {
            "n": len(sub),
            "atm_mean": round(float(np.mean([i["ATM"] for i in sub])), 4),
            "v_mean": round(float(np.mean([i["V"] for i in sub])), 3),
            "s_mean": round(float(np.mean([i["S"] for i in sub])), 3),
        }
    top = sorted(items, key=lambda i: i["ATM"], reverse=True)[:10]
    return {"n_items": len(items), "atm_mean": round(float(a.mean()), 4), "atm_p90": round(float(np.percentile(a, 90)), 4),
            "by_region": by_region, "top_noise": [i["id"] for i in top]}


def is_excluded(domain: str | None, ex: list[str]) -> bool:
    d = (domain or "").lower()
    return any(d == x or d.endswith("." + x) for x in ex)


def build_history(raw_items: list[dict], old_items: list[dict], cfg: dict, old_profiles: dict | None = None) -> dict:
    aliases = {str(k).lower(): str(v).lower() for k, v in (cfg.get("domain_aliases") or {}).items()}
    for it in list(raw_items) + list(old_items):  # egységes forrásnév (edition.cnn.com → cnn.com), a régi hírekben is
        if it.get("source_domain"):
            it["source_domain"] = canon_domain(it["source_domain"], aliases)
    profs: dict = {}
    for d, p in (old_profiles or {}).items():
        c = canon_domain(d, aliases)
        if c not in profs or p.get("n", 0) > profs[c].get("n", 0):
            profs[c] = p
    old_profiles = profs
    ex = [str(x).lower() for x in cfg.get("exclude_domains", [])]
    if ex:  # a kizárt források hírei és statisztikái sem kerülnek az adatba (a régiek is kiesnek)
        raw_items = [i for i in raw_items if not is_excluded(i.get("source_domain"), ex)]
        old_items = [i for i in old_items if not is_excluded(i.get("source_domain"), ex)]
        old_profiles = {d: p for d, p in (old_profiles or {}).items() if not is_excluded(d, ex)}
    weights = {r["code"]: r["weight"] for r in cfg["regions"]}
    centers = {r["code"]: r["center"] for r in cfg["regions"] if "center" in r}
    fallback = {r["code"] for r in cfg["regions"] if r.get("geo_fallback", True)}
    profiles0 = dict(old_profiles or {})
    gmean = insights.global_mean(profiles0)

    merged = {i["id"]: i for i in old_items}
    old_ids = set(merged)
    for it in raw_items:
        prev = merged.get(it["id"])
        if prev and "body" in prev and "body" not in it:
            it["body"] = prev["body"]  # a már elemzett cikkszöveg jelei megmaradnak
        merged[it["id"]] = score_item(it, cfg, weights, profiles0, gmean)
    for i in merged.values():
        geo.attach(i, centers, fallback)

    ret = cfg["retention"]
    cutoff = now_utc() - timedelta(days=ret["days"])
    mode = scoring_mode(cfg)
    for i in merged.values():  # a régi hírek pontját is az érvényes képlettel számoljuk újra (móduváltáskor egységes skála)
        i["ATM"] = atm_value(i["G"], i["S"], i["V"], mode)
    items = [i for i in merged.values() if i.get("published") and parse_iso(i["published"]) >= cutoff]
    items = dedupe_items(items)
    items.sort(key=lambda i: i["published"], reverse=True)
    cap = ret.get("max_per_region", 600)
    counts: dict[str, int] = {}
    kept = []
    for i in items:
        n = counts.get(i["region"], 0)
        if n < cap:
            kept.append(i)
            counts[i["region"]] = n + 1
    items = kept

    new_items = [i for i in items if i["id"] not in old_ids]
    profiles = insights.update_profiles(profiles0, new_items)
    return {
        "schema": 1,
        "generated_at": to_iso_utc(now_utc()),
        "model": {
            "formula": "ATM = round(sqrt(G% * S% * (100 - V%)))" if mode == "sqrt_int" else "ATM = G * S * (1 - V)",
            "scoring": mode,
            "atm_ref": SCALE[mode]["ref"],
            "atm_cap": SCALE[mode]["cap"],
            "trust": cfg["trust"],
            "domain_aliases": aliases,
            "clickbait": list(CLICKBAIT),
            "weights": weights,
            "regions": [{"code": r["code"], "name": r["name"], "short": r.get("short", r["code"]), "center": r.get("center")}
                        for r in cfg["regions"]],
            "thresholds": thresholds(items, cfg),
        },
        "summary": summarize(items),
        "insights": insights.compute(items, profiles),
        "profiles": profiles,
        "items": items,
    }


def load_prev() -> dict | None:
    """A korábbi adatfájl; ha sérült vagy idegen formátumú (nincs benne "items"), nem állítja meg a futást, hanem újraépítjük."""
    if not HISTORY.exists():
        return None
    try:
        prev = json.loads(HISTORY.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[FIGYELEM] az atm_history.json nem olvasható ({exc}); újraépítem.", file=sys.stderr)
        return None
    if not isinstance(prev, dict) or not isinstance(prev.get("items"), list):
        kulcsok = sorted(prev) if isinstance(prev, dict) else type(prev).__name__
        print(f"[FIGYELEM] az atm_history.json nem a várt formátumú (kulcsok: {kulcsok}); újraépítem.", file=sys.stderr)
        return None
    return prev


def main() -> int:
    cfg, cfg_status = load_config()
    raw = json.loads(RAW.read_text(encoding="utf-8")) if RAW.exists() else {"items": []}
    prev = load_prev()
    out = build_history(raw["items"], prev["items"] if prev else [], cfg, prev.get("profiles") if prev else None)
    out["notified"] = prev.get("notified", {}) if prev else {}
    out["config"] = cfg_status
    try:  # passzív piaci napló: egy hiba sosem állíthatja meg a fő futást
        from src.research import market_log
        research = market_log.update(prev.get("research") if prev else None, out["items"], cfg)
    except Exception as exc:
        print(f"[FIGYELEM] piaci napló kihagyva: {exc}", file=sys.stderr)
        research = prev.get("research") if prev else None
    if research is not None:
        out["research"] = research
    out["summary"]["bytes"] = len(json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8"))
    try:  # rendszer-egészség (az app megmutatja, a notify telefonra küldi)
        from src.core import health
        out["health"] = health.check(out, raw.get("count", len(raw.get("items", []))), cfg)
    except Exception as exc:
        print(f"[FIGYELEM] egészség-ellenőrzés kihagyva: {exc}", file=sys.stderr)
        out["health"] = []
    if prev and prev.get("items") == out["items"] and prev.get("model") == out["model"] and prev.get("config") == cfg_status and prev.get("research") == out.get("research") and prev.get("health") == out.get("health"):
        print("Nincs változás, a fájl érintetlen marad.")
        return 0
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    s = out["summary"]
    print(f"{s['n_items']} elem, ATM átlag {s['atm_mean']}, p90 {s['atm_p90']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
