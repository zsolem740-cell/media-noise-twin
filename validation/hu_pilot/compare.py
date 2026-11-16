"""Két modellfuttatás összevetése (például egy cím egy kérésben és csomagos mód ugyanazon az 50 címen). Csak a futások results.csv és summary.json fájljait olvassa, hálózat nélkül.
Mérőszámok: azonos pontszámú címek aránya, átlagos eltérés az összpontszámban (0-8), rangkorreláció, jelenkénti egyezés, érvénytelen arány, kérések és tokenek címenként."""
import csv
import json
from pathlib import Path

SIGNALS = ("curiosity_gap", "exaggeration", "emotional_pressure", "formal_noise")


def _num(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def load_run(run_dir):
    d = Path(run_dir)
    rows = {}
    with (d / "results.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            rows[r["id"]] = r
    summary = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    return rows, summary


def _ranks(x):
    order = sorted(range(len(x)), key=lambda k: x[k])
    rk, i = [0.0] * len(x), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
            j += 1
        for k in range(i, j + 1):
            rk[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return rk


def spearman(a, b):
    if len(a) < 3:
        return None
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((p - ma) * (q - mb) for p, q in zip(ra, rb))
    den = (sum((p - ma) ** 2 for p in ra) * sum((q - mb) ** 2 for q in rb)) ** 0.5
    return num / den if den else None


def compare(dir_a, dir_b, accept=None):
    ra, sa = load_run(dir_a)
    rb, sb = load_run(dir_b)
    ok = lambda r: r is not None and r.get("status") == "ok"
    common = sorted(i for i in ra if i in rb and ok(ra[i]) and ok(rb[i]))
    ta = [_num(ra[i]["total"]) for i in common]
    tb = [_num(rb[i]["total"]) for i in common]
    n = len(common)
    diffs = [b - a for a, b in zip(ta, tb)]
    per_signal = {s: (sum(1 for i in common if ra[i].get(f"{s}_score") == rb[i].get(f"{s}_score")) / n if n else None) for s in SIGNALS}

    def side(rows, summary, n_titles):
        st = {}
        for r in rows.values():
            st[r["status"]] = st.get(r["status"], 0) + 1
        tok = summary.get("tokens") or {}
        return {"statuses": st, "invalid_rate": (st.get("invalid", 0) + st.get("empty", 0)) / n_titles if n_titles else None, "requests": summary.get("requests_total"),
                "tokens_total": tok.get("total_tokens"), "tokens_per_title": (tok.get("total_tokens") / max(1, summary.get("n_ok", 0))) if tok.get("total_tokens") else None,
                "batch_size": summary.get("batch_size", 1), "provider": summary.get("provider"), "model": summary.get("model_requested")}
    nt = len(ra)
    out = {"n_titles": nt, "n_common_ok": n, "A": side(ra, sa, nt), "B": side(rb, sb, len(rb)),
           "exact_total_agreement": (sum(1 for d in diffs if d == 0) / n) if n else None,
           "mean_abs_total_diff": (sum(abs(d) for d in diffs) / n) if n else None, "mean_signed_total_diff_B_minus_A": (sum(diffs) / n) if n else None,
           "share_diff_ge_2": (sum(1 for d in diffs if abs(d) >= 2) / n) if n else None, "spearman_total": spearman(ta, tb), "per_signal_exact_agreement": per_signal}
    ta_, tb_ = out["A"]["tokens_per_title"], out["B"]["tokens_per_title"]
    out["tokens_per_title_ratio_B_over_A"] = (tb_ / ta_) if ta_ and tb_ else None
    out["requests_ratio_B_over_A"] = (out["B"]["requests"] / out["A"]["requests"]) if out["A"]["requests"] and out["B"]["requests"] else None
    if accept:
        out["accept"] = {"spearman_ok": out["spearman_total"] is not None and out["spearman_total"] >= accept["spearman_min"],
                         "mean_abs_diff_ok": out["mean_abs_total_diff"] is not None and out["mean_abs_total_diff"] <= accept["mean_abs_total_diff_max"],
                         "invalid_rate_ok": out["B"]["invalid_rate"] is not None and out["B"]["invalid_rate"] <= accept["invalid_rate_max"], "thresholds": {k: v for k, v in accept.items() if k != "note"}}
        out["accept"]["all_ok"] = all(v for k, v in out["accept"].items() if k.endswith("_ok"))
    return out
