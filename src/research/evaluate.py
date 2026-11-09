"""Önértékelés: igazolja-e az árfolyam a cégekről szóló hírek határozott piaci állítását?

Két kérdés, mindkettő permutációs teszttel a véletlenhez mérve (rögzített mag, tehát ismételhető):
 1) A „határozott állítással" bíró (cég, nap) párok hányad részét igazolta a tényleges mozgás
    (a benchmarkhoz mért, a cég saját korábbi ingadozásához normált eltérés, iránnyal és küszöbbel)?
 2) Előrejelzi-e a nap átlagos ATM-je, hogy az állítás NEM igazolódott (eltúlzott)? (AUC, 0,5 = véletlen)
"""
from __future__ import annotations

import random
from statistics import pstdev


def _returns(prices: dict) -> dict:
    ds = sorted(prices)
    return {ds[i]: prices[ds[i]] / prices[ds[i - 1]] - 1.0 for i in range(1, len(ds)) if prices[ds[i - 1]]}


def abnormal_z(stock: dict, bench: dict, window: int = 40, min_obs: int = 15) -> dict:
    """Napi benchmark-hoz mért hozam, a megelőző napok szórásához normálva (nincs előretekintés)."""
    rs, rb = _returns(stock), _returns(bench)
    ar = [(d, rs[d] - rb[d]) for d in sorted(set(rs) & set(rb))]
    out = {}
    for i, (d, a) in enumerate(ar):
        prev = [x for _, x in ar[max(0, i - window):i]]
        if len(prev) >= min_obs:
            sd = pstdev(prev)
            if sd > 0:
                out[d] = a / sd
    return out


def auc(scores: list, labels: list):
    n = len(scores)
    order = sorted(range(n), key=lambda i: scores[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    n1 = sum(1 for x in labels if x)
    n0 = n - n1
    if n1 == 0 or n0 == 0:
        return None
    return (sum(r for r, l in zip(ranks, labels) if l) - n1 * (n1 + 1) / 2) / (n1 * n0)


def collect_pairs(res: dict, comps: list, rc: dict) -> list:
    min_claims = rc.get("min_claims", 1)
    pairs = []
    for c in comps:
        sp, bp = res["prices"].get(c["symbol"]), res["prices"].get(c["bench_symbol"])
        if not sp or not bp:
            continue
        z = abnormal_z(sp, bp)
        for day, per in res["news_daily"].items():
            a = per.get(c["id"])
            if not a or a.get("claim_n", 0) < min_claims or abs(a.get("claim_net", 0)) < 0.5 or day not in z:
                continue
            pairs.append((1 if a["claim_net"] > 0 else -1, z[day], a["mean_atm"]))
    return pairs


def evaluate(res: dict, comps: list, rc: dict, rounds: int = 500, seed: int = 7) -> dict:
    thr = rc.get("z_threshold", 1.0)
    need = rc.get("min_days", 30)
    pairs = collect_pairs(res, comps, rc)
    n = len(pairs)
    if n < need:
        return {"state": "gyűjt", "n": n, "need": need}

    dirs = [p[0] for p in pairs]
    zs = [p[1] for p in pairs]
    atm = [p[2] for p in pairs]

    def conf(zlist):
        return sum(1 for d, z in zip(dirs, zlist) if z * d > 0 and abs(z) >= thr) / n

    obs = conf(zs)
    rng = random.Random(seed)
    nulls = []
    zz = zs[:]
    for _ in range(rounds):
        rng.shuffle(zz)
        nulls.append(conf(zz))
    base = sum(nulls) / rounds
    p_conf = (1 + sum(1 for x in nulls if x >= obs)) / (rounds + 1)

    wrong = [0 if (z * d > 0 and abs(z) >= thr) else 1 for d, z in zip(dirs, zs)]  # 1 = nem igazolódott (eltúlzott)
    a_obs = auc(atm, wrong)
    p_auc = None
    if a_obs is not None:
        lab = wrong[:]
        cnt = 0
        for _ in range(rounds):
            rng.shuffle(lab)
            a = auc(atm, lab)
            if a is not None and abs(a - 0.5) >= abs(a_obs - 0.5):
                cnt += 1
        p_auc = (1 + cnt) / (rounds + 1)
    return {"state": "kész", "n": n, "confirmed": round(obs, 3), "baseline": round(base, 3), "p_confirm": round(p_conf, 3),
            "auc": None if a_obs is None else round(a_obs, 3), "p_auc": None if p_auc is None else round(p_auc, 3)}
