"""Rétegzett mintavétel: a darabszámok kézzel számolt esetei, a hiánypótlás, a határok és a determinizmus."""
import copy

import pytest

from validation.webis_validation import loader, sample
from validation.webis_validation.loader import Record


def rec(i, mean, short=False):
    return Record(id=f"r{i:04d}", text=f"headline {i}", human_mean=mean, human_median=mean, judgments=(mean,) * 5, n_annotators=5, short_title=short)


def test_allocate_exact_targets_when_everything_is_available():
    n, moved, short = sample.allocate([500, 500, 500, 500], [75, 50, 50, 75], 250)
    assert (n, moved, short) == ([75, 50, 50, 75], [0, 0, 0, 0], 0)


def test_allocate_redistributes_deficit_proportionally_to_targets():
    # az első rétegben csak 20 van: hiány 55, a többi réteg célszámaival (50, 50, 75) arányosan: 15,71 / 15,71 / 23,57 → 16 / 16 / 23
    n, moved, short = sample.allocate([20, 200, 200, 200], [75, 50, 50, 75], 250)
    assert n == [20, 66, 66, 98] and moved == [0, 16, 16, 23] and short == 0 and sum(n) == 250


def test_allocate_caps_at_availability_and_continues():
    n, moved, short = sample.allocate([0, 0, 0, 300], [75, 50, 50, 75], 250)
    assert n == [0, 0, 0, 250] and short == 0
    n, _, short = sample.allocate([10, 60, 60, 300], [75, 50, 50, 75], 250)
    assert sum(n) == 250 and n[0] == 10 and n[1] <= 60 and n[2] <= 60 and short == 0


def test_allocate_reports_shortfall_when_corpus_is_too_small():
    n, _, short = sample.allocate([5, 5, 5, 5], [75, 50, 50, 75], 250)
    assert n == [5, 5, 5, 5] and short == 230
    assert sample.allocate([0, 0, 0, 0], [75, 50, 50, 75], 250)[2] == 250


@pytest.mark.parametrize("mean,idx", [(0.0, 0), (0.2499, 0), (0.25, 1), (0.4999, 1), (0.5, 2), (0.7499, 2), (0.75, 3), (1.0, 3)])
def test_stratum_boundaries(cfg, mean, idx):
    assert sample.stratum_of(mean, cfg["sample"]["strata"]) == idx


def test_mean_outside_all_strata_is_an_error(cfg):
    with pytest.raises(sample.SampleError):
        sample.stratum_of(1.5, cfg["sample"]["strata"])


def make_corpus(per_stratum=(100, 80, 60, 90)):
    out, i = [], 0
    for n, base in zip(per_stratum, (0.05, 0.3, 0.55, 0.85)):
        for k in range(n):
            out.append(rec(i, base + (k % 10) * 0.01, short=(k % 7 == 0)))
            i += 1
    return out


def test_sample_has_requested_size_unique_ids_and_correct_strata(cfg):
    recs = make_corpus()
    picked, rep = sample.stratified_sample(recs, cfg)
    assert len(picked) == 250 == rep["size_actual"] and rep["shortfall"] == 0
    assert len({r.id for r in picked}) == 250 and [r.id for r in picked] == sorted(r.id for r in picked) == rep["ids"]
    per = [sum(1 for r in picked if sample.stratum_of(r.human_mean, cfg["sample"]["strata"]) == i) for i in range(4)]
    assert per == [s["allocated"] for s in rep["strata"]]
    assert per == [75, 50, 50, 75]                                         # elég elem van mindenhol: a célszámok pontosan teljesülnek, pótlás nincs
    assert [s["available"] for s in rep["strata"]] == [100, 80, 60, 90]
    assert sum(s["added_from_deficit"] for s in rep["strata"]) == 250 - sum(min(t, a) for t, a in zip((75, 50, 50, 75), (100, 80, 60, 90)))


def test_sample_documents_the_deficit_fill(cfg):
    recs = make_corpus((100, 30, 30, 200))
    _, rep = sample.stratified_sample(recs, cfg)
    s = {x["name"]: x for x in rep["strata"]}
    assert s["0.25-0.5"]["allocated"] == 30 and s["0.5-0.75"]["allocated"] == 30            # a szűk rétegek teljesen bekerülnek
    assert s["0-0.25"]["allocated"] + s["0.75-1"]["allocated"] == 190
    assert rep["size_actual"] == 250
    assert s["0-0.25"]["added_from_deficit"] > 0 and s["0.75-1"]["added_from_deficit"] > 0


def test_sample_is_deterministic_and_seed_dependent(cfg):
    recs = make_corpus()
    a, _ = sample.stratified_sample(recs, cfg)
    b, _ = sample.stratified_sample(list(reversed(recs)), cfg)               # a bemeneti sorrend nem számít
    assert [r.id for r in a] == [r.id for r in b]
    cfg2 = copy.deepcopy(cfg)
    cfg2["sample"]["seed"] += 1
    c, _ = sample.stratified_sample(recs, cfg2)
    assert [r.id for r in a] != [r.id for r in c]


def test_sample_does_not_modify_the_input(cfg):
    recs = make_corpus()
    snap = [(r.id, r.human_mean, r.short_title) for r in recs]
    sample.stratified_sample(recs, cfg)
    assert snap == [(r.id, r.human_mean, r.short_title) for r in recs]


def test_sample_with_too_few_records_reports_shortfall(cfg):
    picked, rep = sample.stratified_sample(make_corpus((10, 10, 10, 10)), cfg)
    assert len(picked) == 40 and rep["shortfall"] == 210


def test_sample_with_empty_corpus(cfg):
    picked, rep = sample.stratified_sample([], cfg)
    assert picked == [] and rep["shortfall"] == 250


def test_target_sum_must_match_size(cfg):
    bad = copy.deepcopy(cfg)
    bad["sample"]["size"] = 240
    with pytest.raises(sample.SampleError, match="célszámainak összege"):
        sample.stratified_sample(make_corpus(), bad)


def test_short_titles_are_counted_per_stratum_not_dropped(cfg):
    picked, rep = sample.stratified_sample(make_corpus(), cfg)
    assert sum(s["short_title"] for s in rep["strata"]) == sum(r.short_title for r in picked) > 0


def test_distribution_counts_the_whole_corpus(cfg):
    d = sample.distribution(make_corpus(), cfg["sample"]["strata"])
    assert [x["available"] for x in d] == [100, 80, 60, 90]


def test_sample_from_loaded_synthetic_corpus(corpus, cfg):
    data, inst, truth = corpus
    recs, _ = loader.load(inst, truth, cfg, data)
    small = copy.deepcopy(cfg)
    small["sample"].update(size=40, strata=[dict(s, target=10) for s in cfg["sample"]["strata"]])
    picked, rep = sample.stratified_sample(recs, small)
    assert len(picked) + rep["shortfall"] == 40
