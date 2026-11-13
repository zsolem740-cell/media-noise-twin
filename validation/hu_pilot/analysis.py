"""A pilot szavazatainak elemzése: mentések beolvasása, kappa, egyezés, Krippendorff-alfa, referencia (a szavazatok átlaga), kapu, harmadik szavazat listája.
Független a felület JS-kódjától: ugyanazt az exportot számolja újra, az egyezést külön lehet ellenőrizni."""
import csv
import hashlib
import json
import random
from itertools import combinations
from pathlib import Path

from .paths import check_write

MAX_BYTES = 60_000_000


# ---------------------------------------------------------------- beolvasás

def _backups_from_text(text):
    t = text.strip()
    if not t:
        return []
    try:
        j = json.loads(t)
        return [j] if isinstance(j, dict) else [x for x in j if isinstance(x, dict)]
    except ValueError:
        out = []
        for line in t.splitlines():                       # „Minden szavazó mentése”: soronként egy önálló mentés
            line = line.strip()
            if line:
                try:
                    x = json.loads(line)
                except ValueError:
                    continue
                if isinstance(x, dict):
                    out.append(x)
        return out


def parse_exports(paths, cfg):
    """Visszaad: (szavazatok, jelentés). Egy szavazat: voter, id, ordinal, ts, title. Csak a vak szavazatok számítanak; (szavazó, cím) páronként az újabb marad."""
    lm = cfg["label_map"]
    rep = {"files": [], "backups": 0, "votes_seen": 0, "not_blind": 0, "invalid": 0, "duplicates_replaced": 0, "unknown_voter": 0, "skipped_by_voter": {}}
    best = {}
    for p in paths:
        p = Path(p)
        if p.stat().st_size > MAX_BYTES:
            raise ValueError(f"túl nagy fájl: {p.name}")
        raw = p.read_bytes()
        rep["files"].append({"name": p.name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
        for b in _backups_from_text(raw.decode("utf-8")):
            if b.get("format") != "mnt-backup":
                continue
            rep["backups"] += 1
            top = str(b.get("voter") or "")
            sk = rep["skipped_by_voter"].setdefault(top or "?", set())
            sk.update(x for x in (b.get("skipped") or []) if isinstance(x, str))
            for v in list(b.get("votes") or []) + list(b.get("mids") or []):
                rep["votes_seen"] += 1
                if not isinstance(v, dict) or v.get("vote") not in lm or not isinstance(v.get("id"), str):
                    rep["invalid"] += 1
                    continue
                if v.get("blind") is not True:
                    rep["not_blind"] += 1
                    continue
                voter = str(v.get("voter") or top)
                if not voter:
                    rep["unknown_voter"] += 1
                    continue
                rec = {"voter": voter, "id": v["id"], "ordinal": lm[v["vote"]], "ts": v.get("ts") or 0, "title": v.get("title", "")}
                k = (voter, v["id"])
                if k in best:
                    rep["duplicates_replaced"] += 1
                    if rec["ts"] < best[k]["ts"]:
                        continue
                best[k] = rec
    rep["skipped_by_voter"] = {k: sorted(v) for k, v in rep["skipped_by_voter"].items()}
    return sorted(best.values(), key=lambda r: (r["voter"], r["id"])), rep


def ratings(votes, ids=None):
    """{cím: {szavazó: 0/1/2}}; ids megadva esetén csak ezek."""
    out = {}
    for v in votes:
        if ids is None or v["id"] in ids:
            out.setdefault(v["id"], {})[v["voter"]] = v["ordinal"]
    return out


# ---------------------------------------------------------------- egyezés

def cohen_kappa(x, y, k=3, weighted=False):
    n = len(x)
    if n == 0 or n != len(y):
        return None
    o = [[0.0] * k for _ in range(k)]
    for a, b in zip(x, y):
        o[a][b] += 1
    r = [sum(o[i]) / n for i in range(k)]
    c = [sum(o[i][j] for i in range(k)) / n for j in range(k)]
    w = (lambda i, j: abs(i - j) / (k - 1)) if weighted else (lambda i, j: 0.0 if i == j else 1.0)
    d_obs = sum(w(i, j) * o[i][j] / n for i in range(k) for j in range(k))
    d_exp = sum(w(i, j) * r[i] * c[j] for i in range(k) for j in range(k))
    return None if d_exp == 0 else 1 - d_obs / d_exp


def confusion(x, y, k=3):
    m = [[0] * k for _ in range(k)]
    for a, b in zip(x, y):
        m[a][b] += 1
    return m


def krippendorff_alpha(units, metric="ordinal", k=3):
    """units: lista, minden elem a címhez tartozó értékek listája (hiányzó érték nincs benne). metric: nominal, interval, ordinal."""
    vals = [u for u in units if len(u) >= 2]
    if not vals:
        return None
    cats = list(range(k))
    o = [[0.0] * k for _ in cats]
    for u in vals:
        m = len(u)
        for i, a in enumerate(u):
            for j, b in enumerate(u):
                if i != j:
                    o[a][b] += 1.0 / (m - 1)
    n_c = [sum(o[c]) for c in cats]
    n = sum(n_c)
    if n <= 1:
        return None
    if metric == "nominal":
        d = lambda a, b: 0.0 if a == b else 1.0
    elif metric == "interval":
        d = lambda a, b: float((a - b) ** 2)
    else:
        d = lambda a, b: (sum(n_c[g] for g in range(min(a, b), max(a, b) + 1)) - (n_c[a] + n_c[b]) / 2.0) ** 2
    d_o = sum(o[a][b] * d(a, b) for a in cats for b in cats) / n
    d_e = sum(n_c[a] * n_c[b] * d(a, b) for a in cats for b in cats) / (n * (n - 1))
    return None if d_e == 0 else 1 - d_o / d_e


def pair_stats(rat, a, b, k=3):
    common = sorted(i for i, r in rat.items() if a in r and b in r)
    x, y = [rat[i][a] for i in common], [rat[i][b] for i in common]
    return {"voters": [a, b], "n": len(common), "kappa": cohen_kappa(x, y, k), "kappa_weighted": cohen_kappa(x, y, k, True),
            "agreement": (sum(1 for p, q in zip(x, y) if p == q) / len(common)) if common else None, "confusion": confusion(x, y, k)}


def bootstrap_ci(rat, a, b, B, seed, k=3):
    ids = sorted(i for i, r in rat.items() if a in r and b in r)
    if len(ids) < 5:
        return None
    rng, vals = random.Random(seed), []
    for _ in range(B):
        s = [ids[rng.randrange(len(ids))] for _ in ids]
        v = cohen_kappa([rat[i][a] for i in s], [rat[i][b] for i in s], k, True)
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    vals.sort()
    return [vals[int(0.025 * (len(vals) - 1))], vals[int(0.975 * (len(vals) - 1))]]


# ---------------------------------------------------------------- referencia, kapu, harmadik szavazat

def reference(rat):
    out = {}
    for i, r in rat.items():
        vs = list(r.values())
        cnt = {c: vs.count(c) for c in (0, 1, 2)}
        top = max(cnt.values())
        winners = [c for c, n in cnt.items() if n == top]
        out[i] = {"n_votes": len(vs), "human_mean": sum(vs) / len(vs), "majority": winners[0] if len(winners) == 1 else None}
    return out


def adjudication_ids(rat, primary):
    a, b = primary
    return sorted(i for i, r in rat.items() if a in r and b in r and r[a] != r[b])


def gate(rat_measured, cfg, seed=1):
    g, (a, b) = cfg["gate"], cfg["voters"]["primary"]
    ps = pair_stats(rat_measured, a, b)
    ci = bootstrap_ci(rat_measured, a, b, g["bootstrap"], seed)
    ref = reference(rat_measured)
    n = len(ref)
    shares = {c: sum(1 for r in ref.values() if r["majority"] == c) for c in (0, 1, 2)}
    warnings = []
    if n and max(shares.values()) / n > g["dominant_class_share_max"]:
        warnings.append("egy osztály a címek több mint 80%-a: a kappa megbízhatatlan lehet")
    if any(v < g["min_class_count_measured"] for v in shares.values()):
        warnings.append(f"van osztály, amelyből kevesebb mint {g['min_class_count_measured']} cím van (többségi címke szerint)")
    k = ps["kappa_weighted"]
    if k is None:
        decision = "nem_szamolhato"
    elif k >= g["kappa_min"]:
        decision = "atment"
    elif ci and ci[1] >= g["kappa_min"]:
        decision = "eldonthetetlen"
    else:
        decision = "elbukott"
    return {"pair": [a, b], "n_common": ps["n"], "kappa_weighted": k, "kappa_unweighted": ps["kappa"], "agreement": ps["agreement"], "ci95_weighted": ci,
            "kappa_min": g["kappa_min"], "decision": decision, "majority_class_counts": shares, "warnings": warnings}


def usage_stats(votes, ids, skipped_by_voter, cfg):
    g = cfg["gate"]
    mid = sum(1 for v in votes if v["id"] in ids and v["ordinal"] == 1)
    tot = sum(1 for v in votes if v["id"] in ids)
    skip = sum(len(set(s) & ids) for s in skipped_by_voter.values())
    return {"votes": tot, "mid_share": mid / tot if tot else None, "mid_share_ok": (mid / tot < g["mid_share_max"]) if tot else None,
            "skipped": skip, "skip_share": skip / (skip + tot) if (skip + tot) else None,
            "skip_share_ok": (skip / (skip + tot) <= g["skip_share_max"]) if (skip + tot) else None}


def analyze(votes, rep, sel, cfg):
    """sel: a selection.json tartalma (anchor_ids, measured_ids)."""
    anchors, measured = set(sel["anchor_ids"]), set(sel["measured_ids"])
    out = {"parse": {k: v for k, v in rep.items() if k != "skipped_by_voter"}, "voters": sorted({v["voter"] for v in votes})}
    for name, ids in (("anchors", anchors), ("measured", measured)):
        rat = ratings(votes, ids)
        voters = sorted({x for r in rat.values() for x in r})
        out[name] = {"n_titles_with_votes": len(rat), "pairs": [pair_stats(rat, a, b) for a, b in combinations(voters, 2)],
                     "krippendorff_alpha_ordinal": krippendorff_alpha([list(r.values()) for r in rat.values()], "ordinal"),
                     "usage": usage_stats(votes, ids, rep["skipped_by_voter"], cfg)}
    rm = ratings(votes, measured)
    out["gate"] = gate(rm, cfg)
    out["adjudication_ids"] = adjudication_ids(rm, cfg["voters"]["primary"])
    out["coverage"] = {"measured_all_primary_voted": sum(1 for r in rm.values() if all(p in r for p in cfg["voters"]["primary"])), "measured_total": len(measured)}
    return out


def write_reference_csv(votes, ids, path, rdir):
    ref = reference(ratings(votes, ids))
    p = check_write(path, rdir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "n_votes", "human_mean", "majority"])
        for i in sorted(ref):
            r = ref[i]
            w.writerow([i, r["n_votes"], f"{r['human_mean']:.4f}", "" if r["majority"] is None else r["majority"]])
    return p
