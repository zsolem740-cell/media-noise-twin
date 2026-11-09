"""Öntanuló szerver-oldali elemzés: forrásprofilok (Welford), anomália, trend, felszálló kifejezések."""
import math
import re
from collections import Counter
from datetime import timedelta

from src.utils.time_helper import now_utc, parse_iso

WORD = re.compile(r"[^\W\d_]{4,}", re.UNICODE)

# Töltelékszavak: a "felszálló kifejezések" között nem témaként számítanak (angol, magyar, német).
STOP = frozenset("""
about above after again against also always among amid another back been before being below between both
bring brings came cannot come comes could did does doing done down during each even ever every first from further
gets give gives goes going gone good great have having here hers himself into itself just keep know last later
less like likely look looks made make makes many more most much must near need needs never next none only onto
other others over part said same says see seen shall should since some still such take takes than that their
them then there these they thing things this those though three through today told took toward towards under
until upon very want wants was well were what when where whether which while whom whose will with within without
would year years your live news update updates latest breaking report reports video watch
hogy volt lesz van nincs mint még már csak vagy majd után előtt közben miatt szerint ezt azt egy két három több
kell lehet által amely amelyek akkor ahol aki akik illetve szintén olyan ilyen minden most nagy első volna nem
nach über auch eine einem einen einer eines dass nicht sich oder aber wird wurde werden sind sein hat haben wie
mehr noch nur vor bei aus mit für von und ist zum zur heute alle neue neuer
""".split())


def update_profiles(profiles: dict, new_items: list[dict], max_domains: int = 300) -> dict:
    """Inkrementális átlag/szórás forrásonként; a megőrzési időn túl is tanul."""
    for it in new_items:
        d = it.get("source_domain") or "?"
        p = profiles.setdefault(d, {"n": 0, "mS": 0.0, "M2S": 0.0, "mA": 0.0})
        p["n"] += 1
        delta = it["S"] - p["mS"]
        p["mS"] += delta / p["n"]
        p["M2S"] += delta * (it["S"] - p["mS"])
        p["mA"] += (it["ATM"] - p["mA"]) / p["n"]
    if len(profiles) > max_domains:
        keep = sorted(profiles, key=lambda k: profiles[k]["n"], reverse=True)[:max_domains]
        profiles = {k: profiles[k] for k in keep}
    return profiles


def global_mean(profiles: dict) -> float:
    """Az összes forrás súlyozott átlagos szenzációszintje (n szerint)."""
    tot = sum(p["n"] for p in profiles.values())
    return sum(p["n"] * p["mS"] for p in profiles.values()) / tot if tot else 0.0


def _stems(title: str) -> set[str]:
    return {w[:6] for w in WORD.findall(title.lower())}


def cluster_events(items: list[dict], now, hours: int = 48, sim_min: float = 0.40) -> list[dict]:
    """Ugyanarról az eseményről szóló hírek csoportosítása (idf-súlyozott koszinusz-hasonlóság a címeken)."""
    cutoff = now - timedelta(hours=hours)
    docs = []
    for i in items:
        t = parse_iso(i["published"])
        if t >= cutoff and not i.get("official"):
            st = _stems(i["title"])
            if len(st) >= 3:
                docs.append((t, i, st))
    docs.sort(key=lambda d: d[0])
    n = len(docs)
    if n < 3:
        return []
    df: Counter = Counter()
    for _, _, st in docs:
        df.update(st)
    idf = {w: math.log((n + 1) / (c + 1)) + 1.0 for w, c in df.items()}
    maxdf = max(5, int(n * 0.15))  # a túl gyakori szavak nem indexelnek
    clusters: list[dict] = []
    index: dict[str, set[int]] = {}
    for _, it, st in docs:
        vec = {w: idf[w] for w in st}
        nv = math.sqrt(sum(v * v for v in vec.values()))
        cand: set[int] = set()
        for w in st:
            if df[w] <= maxdf:
                cand |= index.get(w, set())
        best, bs = None, 0.0
        for ci in cand:
            c = clusters[ci]
            dot = sum(v * c["vec"].get(w, 0.0) for w, v in vec.items())
            sim = dot / (nv * math.sqrt(c["sq"])) if nv and c["sq"] else 0.0
            if sim > bs:
                best, bs = ci, sim
        if best is not None and bs >= sim_min:
            c = clusters[best]
            for w, v in vec.items():
                c["vec"][w] = c["vec"].get(w, 0.0) + v
            c["sq"] = sum(v * v for v in c["vec"].values())
            c["members"].append(it)
            ci = best
        else:
            clusters.append({"vec": dict(vec), "sq": sum(v * v for v in vec.values()), "members": [it]})
            ci = len(clusters) - 1
        for w in st:
            if df[w] <= maxdf:
                index.setdefault(w, set()).add(ci)

    events = []
    for c in clusters:
        m = c["members"]
        by_domain: dict[str, dict] = {}
        for it in m:
            d = it.get("source_domain") or "?"
            if d not in by_domain or it["S"] > by_domain[d]["S"]:
                by_domain[d] = it
        if len(m) < 3 or len(by_domain) < 2:
            continue
        srcs = sorted(by_domain.values(), key=lambda x: x["S"], reverse=True)
        events.append({
            "label": srcs[-1]["title"],  # a legnyugodtabb cím a semleges megnevezés
            "n": len(m),
            "spread": round(srcs[0]["S"] - srcs[-1]["S"], 3),
            "atm": round(sum(x["ATM"] for x in m) / len(m), 4),
            "sources": [{"id": s["id"], "domain": s.get("source_domain", ""), "source": s.get("source", ""),
                         "S": s["S"], "title": s["title"]} for s in srcs[:6]],
        })
    events.sort(key=lambda e: (e["spread"], e["n"]), reverse=True)
    return events[:8]


def _std(p: dict) -> float:
    return math.sqrt(p["M2S"] / (p["n"] - 1)) if p["n"] > 1 else 0.0


def compute(items: list[dict], profiles: dict, now=None) -> dict:
    now = now or now_utc()
    t24, t48, t6 = now - timedelta(hours=24), now - timedelta(hours=48), now - timedelta(hours=6)
    ts = {i["id"]: parse_iso(i["published"]) for i in items}

    # trend: elmúlt 24 óra átlag-ATM vs. az azt megelőző 24 óra, régiónként
    buckets: dict[str, dict[str, list]] = {}
    for i in items:
        t = ts[i["id"]]
        key = "now" if t >= t24 else "prev" if t >= t48 else None
        if key:
            buckets.setdefault(i["region"], {"now": [], "prev": []})[key].append(i["ATM"])
    trend = {}
    for code, b in buckets.items():
        a = sum(b["now"]) / len(b["now"]) if b["now"] else None
        p = sum(b["prev"]) / len(b["prev"]) if b["prev"] else None
        trend[code] = {
            "now": round(a, 4) if a is not None else None,
            "prev": round(p, 4) if p is not None else None,
            "delta": round(a - p, 4) if a is not None and p is not None else None,
            "n": len(b["now"]),
        }

    # anomália: a forrás megszokott szenzációszintjétől 2σ-nál nagyobb eltérés
    anomalies = []
    for i in items:
        if ts[i["id"]] < t24:
            continue
        p = profiles.get(i.get("source_domain") or "?")
        if not p or p["n"] < 10 or i["S"] < 0.3:
            continue
        z = (i["S"] - p["mS"]) / max(_std(p), 0.05)
        if z >= 2.0:
            anomalies.append({"id": i["id"], "title": i["title"], "source": i.get("source", ""),
                              "region": i["region"], "S": i["S"], "z": round(z, 1)})
    anomalies.sort(key=lambda a: a["z"], reverse=True)

    # felszálló kifejezések: az elmúlt 6 óra gyakorisága a korábbi átlaghoz képest
    recent, base, oldest = Counter(), Counter(), now
    for i in items:
        toks = set(WORD.findall(i["title"].lower()))
        if ts[i["id"]] >= t6:
            recent.update(toks)
        else:
            base.update(toks)
            oldest = min(oldest, ts[i["id"]])
    base_hours = max((t6 - oldest).total_seconds() / 3600, 6.0)
    scale = 6.0 / base_hours
    bursts = []
    for term, c in recent.items():
        if c < 4 or term in STOP:
            continue
        exp = base.get(term, 0) * scale
        ratio = (c + 1) / (exp + 1)
        if ratio >= 2.5:
            bursts.append((ratio, {"term": term, "recent": c, "expected": round(exp, 1)}))
    bursts.sort(key=lambda x: x[0], reverse=True)

    by_domain: dict[str, list] = {}
    for i in items:
        by_domain.setdefault(i.get("source_domain") or "?", []).append(i)
    sources = sorted(
        ({"domain": d, "n": len(v), "mean_S": round(sum(x["S"] for x in v) / len(v), 3),
          "mean_ATM": round(sum(x["ATM"] for x in v) / len(v), 4)}
         for d, v in by_domain.items() if len(v) >= 5),
        key=lambda s: s["mean_ATM"], reverse=True)[:12]

    return {"trend": trend, "anomalies": anomalies[:8], "bursts": [b for _, b in bursts[:8]],
            "sources": sources, "events": cluster_events(items, now)}
