"""Kiértékelés: az AI skálázott pontszáma az emberi átlaghoz és mediánhoz viszonyítva. Tiszta Python + numpy, külső mérőcsomag nélkül."""
import math
import random

import numpy as np


def mse(y, p):
    return float(np.mean((np.asarray(y, float) - np.asarray(p, float)) ** 2))


def rmse(y, p):
    return math.sqrt(mse(y, p))


def nmse(y, p):
    """MSE osztva a valódi értékek szórásnégyzetével (a Clickbait Challenge normált mutatójához hasonló; a hivatalos eval.py-vel
    való egyezést a korpusz mellett kell ellenőrizni). 0-szórásnál nem számítható."""
    v = float(np.var(np.asarray(y, float)))
    return mse(y, p) / v if v > 0 else None


def average_ranks(a):
    a = np.asarray(a, float)
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(len(a))
    i = 0
    while i < len(a):
        j = i
        while j + 1 < len(a) and a[order[j + 1]] == a[order[i]]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def pearson(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 2 or np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def spearman(x, y):
    return pearson(average_ranks(x), average_ranks(y))


def kendall_tau_b(x, y):
    """Kendall tau-b (holtversenyeket kezel). Közös holtversenyek mindkét nevezőből kiesnek."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 2:
        return None
    iu = np.triu_indices(len(x), 1)
    dx, dy = np.sign(x[:, None] - x[None, :])[iu], np.sign(y[:, None] - y[None, :])[iu]
    both = (dx != 0) & (dy != 0)
    c, d = int(np.sum(both & (dx == dy))), int(np.sum(both & (dx != dy)))
    tx, ty = int(np.sum((dx == 0) & (dy != 0))), int(np.sum((dy == 0) & (dx != 0)))
    denom = math.sqrt((c + d + tx) * (c + d + ty))
    return (c - d) / denom if denom else None


def isotonic_fit(x, y):
    """Monoton nem csökkenő illesztés (PAV). Csak diagnosztika: a mintán belüli (optimista) illesztés, hangolásra nem használható."""
    order = np.argsort(np.asarray(x, float), kind="mergesort")
    ys = [float(np.asarray(y, float)[i]) for i in order]
    blocks = []
    for v in ys:
        blocks.append([v, 1])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            s, n = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += n
    fit = []
    for s, n in blocks:
        fit.extend([s / n] * n)
    out = np.empty(len(ys))
    out[order] = fit
    return out


def bootstrap_ci(fn, y, p, b, seed):
    rng = random.Random(seed)
    n = len(y)
    y, p = np.asarray(y, float), np.asarray(p, float)
    vals = []
    for _ in range(b):
        idx = [rng.randrange(n) for _ in range(n)]
        v = fn(y[idx], p[idx])
        if v is not None and not (isinstance(v, float) and math.isnan(v)):
            vals.append(v)
    if len(vals) < max(10, b // 2):
        return None
    vals.sort()
    return [vals[int(0.025 * len(vals))], vals[min(len(vals) - 1, int(0.975 * len(vals)))]]


def _metrics(y, p, cfg, ci=True):
    ev = cfg["evaluation"]
    m = {"n": len(y), "mse": mse(y, p), "rmse": rmse(y, p), "nmse": nmse(y, p), "spearman": spearman(y, p), "kendall_tau_b": kendall_tau_b(y, p)}
    if ci and len(y) >= 10:
        m["ci95"] = {"mse": bootstrap_ci(mse, y, p, ev["bootstrap_b"], ev["bootstrap_seed"]),
                     "spearman": bootstrap_ci(spearman, y, p, ev["bootstrap_b"], ev["bootstrap_seed"]),
                     "kendall_tau_b": bootstrap_ci(kendall_tau_b, y, p, ev["bootstrap_b"], ev["bootstrap_seed"])}
    return m


def pair_up(records, scores):
    """Az azonosító szerint összepárosított (rekord, pontszám) lista; a hiányzó és a felesleges pontszámok megszámolva."""
    by = {s["id"]: s for s in scores}
    pairs = [(r, by[r.id]) for r in records if r.id in by]
    return pairs, {"records": len(records), "scored": len(pairs), "missing_scores": len(records) - len(pairs),
                   "unknown_scores": len(set(by) - {r.id for r in records})}


def evaluate(records, scores, cfg):
    pairs, cover = pair_up(records, scores)
    if len(pairs) < 2:
        return {"coverage": cover, "error": "legalább 2 pontozott cím kell"}
    thr = cfg["clickbait_threshold"]
    p = [s["scaled"] for _, s in pairs]
    mean = [r.human_mean for r, _ in pairs]
    med = [r.human_median for r, _ in pairs]
    rep = {"coverage": cover, "scaling_assumption": "scaled = total / 8 (kezdeti feltevés, nem bizonyított)",
           "vs_human_mean": _metrics(mean, p, cfg), "vs_human_median": _metrics(med, p, cfg)}
    fit = isotonic_fit(p, mean)
    rep["isotonic_insample_vs_mean"] = {"mse": mse(mean, fit), "note": "mintán belüli, optimista illesztés; csak a 0–8 → 0–1 átváltás vizsgálatához, hangolásra nem"}
    rep["per_signal_spearman_vs_mean"] = {k: spearman(mean, [s["signals"][k]["score"] for _, s in pairs]) for k in cfg["scoring"]["signals"]}
    fn = [r.id for (r, _), pv in zip(pairs, p) if pv >= thr and r.human_mean < thr]
    miss = [r.id for (r, _), pv in zip(pairs, p) if pv < thr and r.human_mean >= thr]
    tp = sum(1 for (r, _), pv in zip(pairs, p) if pv >= thr and r.human_mean >= thr)
    prec, rec = tp / (tp + len(fn)) if tp + len(fn) else None, tp / (tp + len(miss)) if tp + len(miss) else None
    rep["classification_at_threshold"] = {"threshold": thr, "false_noisy": len(fn), "missed_noisy": len(miss), "true_noisy": tp,
                                          "precision": prec, "recall": rec, "false_noisy_ids": fn, "missed_noisy_ids": miss}
    errs = sorted(((abs(pv - r.human_mean), r, s) for (r, s), pv in zip(pairs, p)), key=lambda e: (-e[0], e[1].id))
    rep["top_errors"] = [{"id": r.id, "text": r.text, "human_mean": r.human_mean, "scaled": s["scaled"], "abs_error": round(e, 4),
                          "signals": {k: s["signals"][k]["score"] for k in cfg["scoring"]["signals"]}, "short_title": r.short_title,
                          "disagreement": round(r.disagreement, 4)} for e, r, s in errs[:cfg["evaluation"]["top_errors"]]]
    rep["by_short_title"] = {str(flag): _metrics([m for (r, _), m in zip(pairs, mean) if r.short_title == flag], [pv for (r, _), pv in zip(pairs, p) if r.short_title == flag], cfg, ci=False)
                             for flag in (True, False) if any(r.short_title == flag for r, _ in pairs)}
    med_dis = float(np.median([r.disagreement for r, _ in pairs]))
    rep["by_annotator_agreement"] = {name: _metrics([m for (r, _), m in zip(pairs, mean) if (r.disagreement > med_dis) == contested],
                                                    [pv for (r, _), pv in zip(pairs, p) if (r.disagreement > med_dis) == contested], cfg, ci=False)
                                     for name, contested in (("contested", True), ("uniform", False)) if any((r.disagreement > med_dis) == contested for r, _ in pairs)}
    return rep
