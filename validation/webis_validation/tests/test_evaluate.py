"""Mutatók kézzel számolt példákon: MSE, RMSE, Spearman, Kendall tau-b (holtversennyel), PAV, kiértékelő jelentés."""
import copy
import math

import numpy as np
import pytest

from validation.webis_validation import evaluate as ev
from validation.webis_validation.loader import Record

SIG = ("curiosity_gap", "exaggeration", "emotional_pressure", "formal_noise")


def rec(i, mean, median=None, short=False, dis=0.1):
    return Record(id=f"r{i}", text=f"headline number {i}", human_mean=mean, human_median=mean if median is None else median, judgments=(mean,) * 5,
                  n_annotators=5, short_title=short, disagreement=dis)


def score(i, total):
    left, sig = total, {}
    for k in SIG:
        s = min(2, left)
        left -= s
        sig[k] = {"score": s, "reason": "x", "span": ""}
    return {"id": f"r{i}", "source": "webis-clickbait-17", "signals": sig, "total": total, "scaled": total / 8}


def test_mse_rmse_by_hand():
    y, p = [0, 0.5, 1], [0, 1, 1]
    assert ev.mse(y, p) == pytest.approx(0.25 / 3) and ev.rmse(y, p) == pytest.approx(math.sqrt(0.25 / 3))


def test_nmse_by_hand_and_constant_truth():
    assert ev.nmse([0, 1], [0.5, 0.5]) == pytest.approx(1.0)          # az átlagot jósló modell: 1
    assert ev.nmse([0.3, 0.3], [0.1, 0.9]) is None                     # állandó valóság: nem számítható


def test_average_ranks_with_ties():
    assert list(ev.average_ranks([10, 20, 20, 30])) == [1, 2.5, 2.5, 4]
    assert list(ev.average_ranks([5, 5, 5])) == [2, 2, 2]


def test_perfect_and_reversed_rank_correlation():
    x = [0.1, 0.4, 0.5, 0.9]
    assert ev.spearman(x, x) == pytest.approx(1) and ev.kendall_tau_b(x, x) == pytest.approx(1)
    assert ev.spearman(x, x[::-1]) == pytest.approx(-1) and ev.kendall_tau_b(x, x[::-1]) == pytest.approx(-1)


def test_rank_correlations_with_ties_by_hand():
    x, y = [1, 2, 2, 3], [1, 2, 3, 3]
    assert ev.kendall_tau_b(x, y) == pytest.approx(0.8)               # C=4, D=0, Tx=1, Ty=1 → 4 / 5
    assert ev.spearman(x, y) == pytest.approx(3.75 / 4.5)             # rangok [1,2.5,2.5,4] és [1,2,3.5,3.5]
    assert ev.kendall_tau_b([1, 1, 2, 2], [1, 2, 1, 2]) == pytest.approx(0)


def test_correlations_are_not_computable_for_constant_input():
    assert ev.spearman([1, 2, 3], [0.5, 0.5, 0.5]) is None and ev.kendall_tau_b([1, 2, 3], [0.5, 0.5, 0.5]) is None
    assert ev.spearman([1], [1]) is None and ev.kendall_tau_b([1], [1]) is None
    assert ev.pearson([], []) is None


def test_spearman_is_invariant_to_monotone_transforms():
    x, y = [0.1, 0.9, 0.4, 0.4, 0.7], [0.3, 0.8, 0.1, 0.5, 0.9]
    assert ev.spearman(x, y) == pytest.approx(ev.spearman([v ** 3 + 2 for v in x], y))


def test_isotonic_fit_by_hand_and_order_restored():
    assert list(ev.isotonic_fit([1, 2, 3, 4], [1, 3, 2, 4])) == [1, 2.5, 2.5, 4]
    out = ev.isotonic_fit([4, 1, 3, 2], [4, 1, 2, 3])                  # ugyanaz az eset keverve
    assert list(out) == [4, 1, 2.5, 2.5]
    f = ev.isotonic_fit(list(range(10)), [5, 4, 3, 2, 1, 0, 0, 1, 2, 3])
    assert all(np.diff(np.asarray(sorted(zip(range(10), f)))[:, 1]) >= -1e-12)


def test_bootstrap_ci_is_deterministic_and_contains_the_estimate():
    rng = np.random.default_rng(0)
    x = rng.random(80)
    y = x + rng.normal(0, 0.1, 80)
    a, b = ev.bootstrap_ci(ev.spearman, x, y, 200, 7), ev.bootstrap_ci(ev.spearman, x, y, 200, 7)
    assert a == b and a[0] <= ev.spearman(x, y) <= a[1]
    assert ev.bootstrap_ci(ev.spearman, [1, 1, 1], [1, 2, 3], 50, 1) is None     # nem számítható minta: nincs sáv


def test_evaluate_classification_counts_by_hand(cfg):
    recs = [rec(0, 0.1), rec(1, 0.6), rec(2, 0.9), rec(3, 0.4)]
    scs = [score(0, 0), score(1, 2), score(2, 6), score(3, 5)]          # scaled: 0, 0,25, 0,75, 0,625
    r = ev.evaluate(recs, scs, cfg)["classification_at_threshold"]
    assert (r["false_noisy"], r["missed_noisy"], r["true_noisy"]) == (1, 1, 1)
    assert r["false_noisy_ids"] == ["r3"] and r["missed_noisy_ids"] == ["r1"] and r["precision"] == 0.5 and r["recall"] == 0.5


def test_evaluate_precision_and_recall_not_computable(cfg):
    out = ev.evaluate([rec(0, 0.1), rec(1, 0.2)], [score(0, 0), score(1, 1)], cfg)["classification_at_threshold"]
    assert out["precision"] is None and out["recall"] is None and out["true_noisy"] == 0


def test_evaluate_coverage_missing_and_unknown_scores(cfg):
    recs = [rec(i, i / 10) for i in range(6)]
    scs = [score(i, i) for i in range(4)] + [score(99, 3)]
    rep = ev.evaluate(recs, scs, cfg)
    assert rep["coverage"] == {"records": 6, "scored": 4, "missing_scores": 2, "unknown_scores": 1}


def test_evaluate_with_too_few_scored_titles(cfg):
    assert "error" in ev.evaluate([rec(0, 0.2), rec(1, 0.4)], [score(0, 1)], cfg)
    assert "error" in ev.evaluate([], [], cfg)


def test_evaluate_reports_both_targets_and_scaling_assumption(cfg):
    recs = [rec(i, i / 10, median=(10 - i) / 10) for i in range(11)]
    scs = [score(i, min(8, i)) for i in range(11)]
    rep = ev.evaluate(recs, scs, cfg)
    assert "total / 8" in rep["scaling_assumption"] and "nem bizonyított" in rep["scaling_assumption"]
    assert rep["vs_human_mean"]["spearman"] > 0.9 and rep["vs_human_median"]["spearman"] < -0.5      # a medián fordított: a két cél külön számolódik
    assert set(rep["vs_human_mean"]["ci95"]) == {"mse", "spearman", "kendall_tau_b"}
    assert set(rep["per_signal_spearman_vs_mean"]) == set(SIG)
    assert rep["isotonic_insample_vs_mean"]["mse"] <= rep["vs_human_mean"]["mse"] + 1e-12     # az illesztés nem lehet rosszabb a nyers átváltásnál


def test_top_errors_are_sorted_with_a_stable_tie_break(cfg):
    recs = [rec(0, 0.0), rec(1, 1.0), rec(2, 0.5), rec(3, 0.5)]
    scs = [score(0, 8), score(1, 0), score(2, 4), score(3, 4)]          # r0 és r1 hibája 1,0; r2 és r3 hibája 0
    top = ev.evaluate(recs, scs, cfg)["top_errors"]
    assert [t["id"] for t in top] == ["r0", "r1", "r2", "r3"] and top[0]["abs_error"] == 1.0
    small = copy.deepcopy(cfg)
    small["evaluation"]["top_errors"] = 2
    assert len(ev.evaluate(recs, scs, small)["top_errors"]) == 2


def test_breakdown_by_short_title_only_when_both_groups_exist(cfg):
    recs = [rec(i, i / 10, short=(i < 4)) for i in range(10)]
    rep = ev.evaluate(recs, [score(i, i) for i in range(10)], cfg)
    assert set(rep["by_short_title"]) == {"True", "False"} and rep["by_short_title"]["True"]["n"] == 4
    only = ev.evaluate([rec(i, i / 10) for i in range(5)], [score(i, i) for i in range(5)], cfg)
    assert set(only["by_short_title"]) == {"False"}


def test_breakdown_by_annotator_agreement_splits_at_the_median(cfg):
    recs = [rec(i, i / 10, dis=0.0 if i < 5 else 0.4) for i in range(10)]
    rep = ev.evaluate(recs, [score(i, i) for i in range(10)], cfg)["by_annotator_agreement"]
    assert rep["uniform"]["n"] == 5 and rep["contested"]["n"] == 5


def test_evaluate_does_not_modify_inputs(cfg):
    recs, scs = [rec(i, i / 10) for i in range(8)], [score(i, i) for i in range(8)]
    a, b = copy.deepcopy(scs), [(r.id, r.human_mean) for r in recs]
    ev.evaluate(recs, scs, cfg)
    assert scs == a and b == [(r.id, r.human_mean) for r in recs]


def test_constant_ai_score_gives_non_computable_correlations(cfg):
    recs = [rec(i, i / 10) for i in range(10)]
    rep = ev.evaluate(recs, [score(i, 3) for i in range(10)], cfg)
    assert rep["vs_human_mean"]["spearman"] is None and rep["vs_human_mean"]["kendall_tau_b"] is None
    assert rep["vs_human_mean"]["mse"] > 0 and rep["vs_human_mean"]["ci95"]["spearman"] is None
