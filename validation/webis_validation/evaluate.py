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


def binary_metrics(truth, pred):
    """Kétosztályos mutatók (1 = zajos). Nem számítható mutató értéke None."""
    tp = sum(1 for t_, p_ in zip(truth, pred) if t_ == 1 and p_ == 1)
    fp = sum(1 for t_, p_ in zip(truth, pred) if t_ == 0 and p_ == 1)
    fn = sum(1 for t_, p_ in zip(truth, pred) if t_ == 1 and p_ == 0)
    tn = sum(1 for t_, p_ in zip(truth, pred) if t_ == 0 and p_ == 0)
    n = tp + fp + fn + tn
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = None if prec is None or rec is None else (0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec))
    return {"n": n, "true_noisy": tp, "false_noisy": fp, "missed_noisy": fn, "true_calm": tn,
            "accuracy": (tp + tn) / n if n else None, "precision": prec, "recall": rec, "f1": f1}


def roc_auc(truth, scores):
    """Terület a ROC-görbe alatt (Mann–Whitney, holtversennyel); None, ha csak egy osztály van."""
    truth = np.asarray(truth)
    n1, n0 = int(np.sum(truth == 1)), int(np.sum(truth == 0))
    if n1 == 0 or n0 == 0:
        return None
    r = average_ranks(scores)
    return float((np.sum(r[truth == 1]) - n1 * (n1 + 1) / 2) / (n1 * n0))


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
    thr, lab = cfg["clickbait_threshold"], cfg["class_labels"]
    p = [s["scaled"] for _, s in pairs]
    mean = [r.human_mean for r, _ in pairs]
    med = [r.human_median for r, _ in pairs]
    pred = [1 if pv >= thr else 0 for pv in p]          # az AI-pontszám binárisítása (a hivatalos eval.py szerint: 0,5 alatt 0, egyébként 1)
    rep = {"coverage": cover, "scaling_assumption": "scaled = total / 8 (kezdeti feltevés, nem bizonyított)",
           # 1) regresszió a truthMean-re (a Clickbait Challenge elsődleges célja)
           "regression_vs_truthMean": _metrics(mean, p, cfg),
           # 2) kiegészítő eredmény a truthMedian-ra
           "supplementary_vs_truthMedian": _metrics(med, p, cfg)}
    fit = isotonic_fit(p, mean)
    rep["isotonic_insample_vs_mean"] = {"mse": mse(mean, fit), "note": "mintán belüli, optimista illesztés; csak a 0–8 → 0–1 átváltás vizsgálatához, hangolásra nem"}
    rep["per_signal_spearman_vs_mean"] = {k: spearman(mean, [s["signals"][k]["score"] for _, s in pairs]) for k in cfg["scoring"]["signals"]}
    # 3) osztályozás a fájlbeli truthClass-szal (a többségi annotátori ítélet)
    known = [(i, r) for i, (r, _) in enumerate(pairs) if r.truth_class in (lab["positive"], lab["negative"])]
    if known:
        y = [1 if r.truth_class == lab["positive"] else 0 for _, r in known]
        pc = [pred[i] for i, _ in known]
        rep["classification_vs_truthClass"] = {
            "available": True, "truth_rule": "a fájlbeli truthClass (többségi annotátori ítélet)", "ai_rule": f"scaled >= {thr}",
            "unlabeled_or_unknown_records": len(pairs) - len(known), **binary_metrics(y, pc), "roc_auc": roc_auc(y, [p[i] for i, _ in known]),
            "false_noisy_ids": [r.id for (i, r), yy, pp in zip(known, y, pc) if yy == 0 and pp == 1],
            "missed_noisy_ids": [r.id for (i, r), yy, pp in zip(known, y, pc) if yy == 1 and pp == 0]}
    else:
        rep["classification_vs_truthClass"] = {"available": False, "reason": "a rekordokhoz nincs ismert truthClass"}
    # 4) az átlagküszöb alapú binárisítás (NEM azonos a truthClass-szal)
    y2 = [1 if m >= thr else 0 for m in mean]
    rep["binarized_mean_threshold"] = {"truth_rule": f"truthMean >= {thr}", "ai_rule": f"scaled >= {thr}", **binary_metrics(y2, pred), "roc_auc": roc_auc(y2, p),
                                       "false_noisy_ids": [r.id for (r, _), yy, pp in zip(pairs, y2, pred) if yy == 0 and pp == 1],
                                       "missed_noisy_ids": [r.id for (r, _), yy, pp in zip(pairs, y2, pred) if yy == 1 and pp == 0]}
    # a két igazság eltérése a vizsgált mintán
    dis = [(r, 1 if r.truth_class == lab["positive"] else 0, 1 if r.human_mean >= thr else 0) for r, _ in pairs if r.truth_class in (lab["positive"], lab["negative"])]
    dis = [(r, c, m) for r, c, m in dis if c != m]
    rep["truthClass_vs_mean_threshold_disagreement"] = {
        "n_checked": len(known), "n_disagree": len(dis),
        "clickbait_below_threshold": sum(1 for _, c, m in dis if c == 1 and m == 0), "no_clickbait_at_or_above_threshold": sum(1 for _, c, m in dis if c == 0 and m == 1),
        "ids": [r.id for r, _, _ in dis]}
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
