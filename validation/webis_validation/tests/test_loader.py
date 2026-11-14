"""Betöltő: mezőleképezés, átlag és medián újraszámolása, hibás rekordok, kizárások. Csak szintetikus adat."""
import json

import pytest

from validation.webis_validation import loader, synthetic
from validation.webis_validation.isolation import IsolationError


def write(d, name, rows):
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def test_load_synthetic_corpus(corpus, cfg):
    data, inst, truth = corpus
    recs, rep = loader.load(inst, truth, cfg, data)
    assert rep["n_kept"] == len(recs) and rep["n_kept"] > 350
    assert rep["annotator_counts"] == {5: rep["n_kept"]}
    assert rep["mean_mismatch"] == 0 and rep["median_mismatch"] == 0
    assert [r.id for r in recs] == sorted(r.id for r in recs)
    assert all(0 <= r.human_mean <= 1 and any(abs(r.human_median - s) < 1e-6 for s in (0.0, 1 / 3, 2 / 3, 1.0)) for r in recs)
    assert rep["truth_class_available"] and sum(rep["truth_class_counts"].values()) == rep["n_kept"]
    assert rep["class_vs_majority_mismatch"] == 0                     # a szintetikus címke is többségi ítélet


def test_mean_and_median_recomputed_by_hand(tmp_path, cfg):
    d = tmp_path / "data"
    write(d, "i.jsonl", [{"id": "a", "postText": ["Some headline here today"]}])
    write(d, "t.jsonl", [{"id": "a", "truthJudgments": [0.0, 0.33, 0.33, 0.66, 1.0], "truthMean": 0.464, "truthMedian": 0.33}])
    (r,), rep = loader.load(d / "i.jsonl", d / "t.jsonl", cfg, d)
    assert r.human_mean == pytest.approx((0 + 0.33 + 0.33 + 0.66 + 1.0) / 5)
    assert r.human_median == 0.33
    # populációs szórás kézzel: eltérések −0,464, −0,134, −0,134, 0,196, 0,536; négyzetösszeg 0,57692; /5 = 0,115384; gyök = 0,33968
    assert r.disagreement == pytest.approx(0.33968, abs=1e-4)
    assert rep["mean_mismatch"] == 0


def test_even_number_of_judgments_median(tmp_path, cfg):
    d = tmp_path / "data"
    write(d, "i.jsonl", [{"id": "a", "postText": "A four judgment headline"}])
    write(d, "t.jsonl", [{"id": "a", "truthJudgments": [0.0, 0.33, 0.66, 1.0]}])
    (r,), rep = loader.load(d / "i.jsonl", d / "t.jsonl", cfg, d)
    assert r.human_median == pytest.approx(0.495)
    assert "annotators_unexpected" in r.flags and rep["annotator_counts"] == {4: 1}
    assert r.file_mean is None                                           # hiányzó fájlbeli átlag nem hiba


def test_file_value_mismatch_is_reported_not_corrected(tmp_path, cfg):
    d = tmp_path / "data"
    write(d, "i.jsonl", [{"id": "a", "postText": ["A headline with words"]}])
    write(d, "t.jsonl", [{"id": "a", "truthJudgments": [0.0] * 5, "truthMean": 0.9, "truthMedian": 1.0}])
    (r,), rep = loader.load(d / "i.jsonl", d / "t.jsonl", cfg, d)
    assert r.human_mean == 0.0 and r.file_mean == 0.9                    # az újraszámolt érték marad, a fájlbeli külön
    assert rep["mean_mismatch"] == 1 and rep["median_mismatch"] == 1 and rep["max_mean_diff"] == pytest.approx(0.9)
    assert set(r.flags) == {"mean_mismatch", "median_mismatch"}


def test_alternate_field_spelling_and_text_forms(tmp_path, cfg):
    d = tmp_path / "data"
    write(d, "i.jsonl", [{"id": "a", "postText": ["First part", "second part"]}, {"id": "b", "postText": "Plain string headline"}])
    write(d, "t.jsonl", [{"id": "a", "truthJudgements": [0.33] * 5}, {"id": "b", "truthJudgements": [1.0] * 5}])
    recs, _ = loader.load(d / "i.jsonl", d / "t.jsonl", cfg, d)
    assert [r.text for r in recs] == ["First part second part", "Plain string headline"]


def test_missing_required_field_stops_and_lists_actual_keys(tmp_path, cfg):
    d = tmp_path / "data"
    write(d, "i.jsonl", [{"id": "a", "tweet": "text"}])
    write(d, "t.jsonl", [{"id": "a", "truthJudgments": [0.0] * 5}])
    with pytest.raises(loader.LoadError, match="hiányzó kötelező mező: text.*instances mezői: \\['id', 'tweet'\\]"):
        loader.load(d / "i.jsonl", d / "t.jsonl", cfg, d)


def test_bad_records_are_excluded_and_counted(tmp_path, cfg):
    d = tmp_path / "data"
    inst = [{"id": "ok", "postText": ["A perfectly fine headline"]}, {"id": "empty", "postText": ["  "]}, {"id": "dup", "postText": ["a PERFECTLY  fine headline"]},
            {"id": "range", "postText": ["Judgment out of range headline"]}, {"id": "none", "postText": ["No judgments headline"]},
            {"id": "notruth", "postText": ["Truth row is missing headline"]}, {"id": "hu", "postText": ["Ez egy őszinte magyar cím"]},
            {"id": "str", "postText": ["String judgments headline"]}]
    truth = [{"id": "ok", "truthJudgments": [0.33] * 5}, {"id": "empty", "truthJudgments": [0.0] * 5}, {"id": "dup", "truthJudgments": [1.0] * 5},
             {"id": "range", "truthJudgments": [0.0, 0.5, 0.0, 0.0, 0.0]}, {"id": "none", "truthJudgments": []},
             {"id": "hu", "truthJudgments": [0.0] * 5}, {"id": "str", "truthJudgments": ["0.33"] * 5}]
    write(d, "i.jsonl", inst)
    write(d, "t.jsonl", truth)
    recs, rep = loader.load(d / "i.jsonl", d / "t.jsonl", cfg, d)
    assert rep["missing_truth"] == 1
    assert rep["excluded"]["üres szöveg"] == 1
    assert rep["excluded"]["hibás vagy skálán kívüli ítélet"] == 3         # tartományon kívüli, üres lista, szöveg típusú
    assert rep["excluded"]["magyar-specifikus betű (nem Webis-adat)"] == 1
    assert rep["excluded"]["ismétlődő szöveg"] == 1                       # a nagybetű- és szóközkülönbség nem számít
    assert rep["n_kept"] == 1 and recs[0].id == "dup"                      # a duplikátumból az azonosító szerint első marad


def test_short_title_flag_is_set_not_dropped(tmp_path, cfg):
    d = tmp_path / "data"
    write(d, "i.jsonl", [{"id": "a", "postText": ["Wow"]}, {"id": "b", "postText": ["Three words here"]}, {"id": "c", "postText": ["Four words are here"]}])
    write(d, "t.jsonl", [{"id": x, "truthJudgments": [0.66] * 5} for x in "abc"])
    recs, rep = loader.load(d / "i.jsonl", d / "t.jsonl", cfg, d)
    assert {r.id: r.short_title for r in recs} == {"a": True, "b": True, "c": False} and rep["n_short_title"] == 2


def test_class_count_uses_threshold(tmp_path, cfg):
    d = tmp_path / "data"
    write(d, "i.jsonl", [{"id": "a", "postText": ["First headline text"]}, {"id": "b", "postText": ["Second headline text"]}])
    write(d, "t.jsonl", [{"id": "a", "truthJudgments": [0.33, 0.66, 0.33, 0.66, 0.33]}, {"id": "b", "truthJudgments": [0.66, 0.66, 0.66, 0.33, 0.66]}])
    _, rep = loader.load(d / "i.jsonl", d / "t.jsonl", cfg, d)
    assert rep["n_clickbait_at_threshold"] == 1                           # 0,462 < 0,5 ≤ 0,594


def test_invalid_json_line_reports_line_number(tmp_path, cfg):
    d = tmp_path / "data"
    d.mkdir()
    (d / "i.jsonl").write_text('{"id": "a", "postText": "x y z w"}\n{rossz\n', encoding="utf-8")
    (d / "t.jsonl").write_text('{"id": "a", "truthJudgments": [0]}\n', encoding="utf-8")
    with pytest.raises(loader.LoadError, match="i.jsonl:2"):
        loader.load(d / "i.jsonl", d / "t.jsonl", cfg, d)


def test_empty_files_stop(tmp_path, cfg):
    d = tmp_path / "data"
    d.mkdir()
    (d / "i.jsonl").write_text("", encoding="utf-8")
    (d / "t.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(loader.LoadError, match="üres"):
        loader.load(d / "i.jsonl", d / "t.jsonl", cfg, d)


def test_loading_outside_the_data_dir_is_refused(tmp_path, cfg):
    d = tmp_path / "data"
    other = tmp_path / "other"
    write(other, "i.jsonl", [{"id": "a", "postText": "x y z w"}])
    write(other, "t.jsonl", [{"id": "a", "truthJudgments": [0.0] * 5}])
    with pytest.raises(IsolationError):
        loader.load(other / "i.jsonl", other / "t.jsonl", cfg, d)


def test_verify_archive(tmp_path):
    import hashlib
    f = tmp_path / "clickbait17-train-170331.zip"
    f.write_bytes(b"abc")
    good = {"clickbait17-train-170331.zip": {"md5": hashlib.md5(b"abc").hexdigest(), "size": 3}}
    assert loader.verify_archive(f, good)["md5_ok"] and loader.verify_archive(f, good)["size_ok"]
    bad = {"clickbait17-train-170331.zip": {"md5": "0" * 32, "size": 4}}
    r = loader.verify_archive(f, bad)
    assert not r["md5_ok"] and not r["size_ok"]
    with pytest.raises(loader.LoadError):
        loader.verify_archive(tmp_path / "ismeretlen.zip", good)


def test_truth_class_is_kept_and_compared_with_majority_and_mean_threshold(tmp_path, cfg):
    d = tmp_path / "data"
    third, two3 = 0.3333333, 0.6666667
    write(d, "i.jsonl", [{"id": x, "postText": [f"Headline number {x} here"]} for x in ("a", "b", "c", "d")])
    write(d, "t.jsonl", [
        {"id": "a", "truthJudgments": [0.0, 0.0, two3, two3, two3], "truthClass": "clickbait"},        # átlag 0,4 < 0,5, de 3 : 2 a felső szintek javára
        {"id": "b", "truthJudgments": [third, third, third, 1.0, 1.0], "truthClass": "no-clickbait"},   # átlag 0,6 >= 0,5, de 2 : 3 az alsó szintek javára
        {"id": "c", "truthJudgments": [0.0] * 5, "truthClass": "no-clickbait"},                          # mindkét szabály szerint nyugodt
        {"id": "d", "truthJudgments": [1.0] * 5, "truthClass": "no-clickbait"}])                        # a fájl a többséggel is ellentmond (hibás címke)
    recs, rep = loader.load(d / "i.jsonl", d / "t.jsonl", cfg, d)
    by = {r.id: r for r in recs}
    assert [by[x].truth_class for x in "abcd"] == ["clickbait", "no-clickbait", "no-clickbait", "no-clickbait"]
    assert [by[x].majority_class for x in "abcd"] == ["clickbait", "no-clickbait", "no-clickbait", "clickbait"]
    assert rep["truth_class_available"] and rep["truth_class_counts"] == {"clickbait": 1, "no-clickbait": 3}
    assert rep["class_vs_mean_threshold"] == {"mismatch": 3, "clickbait_below_threshold": 1, "no_clickbait_at_or_above_threshold": 2}
    assert rep["class_vs_majority_mismatch"] == 1 and "class_majority_mismatch" in by["d"].flags
    assert rep["class_check_all_valid_rows"] == {"rows": 4, "mean_threshold_mismatch": 3, "majority_mismatch": 1, "unknown_label": 0}


def test_class_check_counts_rows_before_duplicate_exclusion(tmp_path, cfg):
    d = tmp_path / "data"
    write(d, "i.jsonl", [{"id": "a", "postText": ["Same headline text"]}, {"id": "b", "postText": ["same HEADLINE text"]}])
    write(d, "t.jsonl", [{"id": "a", "truthJudgments": [0.0, 0.0, 0.6666667, 0.6666667, 0.6666667], "truthClass": "clickbait"},
                         {"id": "b", "truthJudgments": [0.0, 0.0, 0.6666667, 0.6666667, 0.6666667], "truthClass": "clickbait"}])
    recs, rep = loader.load(d / "i.jsonl", d / "t.jsonl", cfg, d)
    assert len(recs) == 1 and rep["class_vs_mean_threshold"]["mismatch"] == 1                     # a kizárás után egy
    assert rep["class_check_all_valid_rows"]["rows"] == 2 and rep["class_check_all_valid_rows"]["mean_threshold_mismatch"] == 2   # kizárás előtt kettő


def test_missing_or_unknown_truth_class(tmp_path, cfg):
    d = tmp_path / "data"
    write(d, "i.jsonl", [{"id": "a", "postText": ["First headline here"]}, {"id": "b", "postText": ["Second headline here"]}])
    write(d, "t.jsonl", [{"id": "a", "truthJudgments": [0.0] * 5}, {"id": "b", "truthJudgments": [1.0] * 5, "truthClass": "maybe"}])
    recs, rep = loader.load(d / "i.jsonl", d / "t.jsonl", cfg, d)
    assert [r.truth_class for r in recs] == [None, "maybe"] and not rep["truth_class_available"]
    assert rep["class_check_all_valid_rows"]["unknown_label"] == 1 and rep["class_vs_mean_threshold"]["mismatch"] == 0   # ismeretlen címke nem számít eltérésnek


def test_even_split_has_no_majority_and_is_not_a_mismatch(tmp_path, cfg):
    d = tmp_path / "data"
    write(d, "i.jsonl", [{"id": "a", "postText": ["Tied headline words here"]}])
    write(d, "t.jsonl", [{"id": "a", "truthJudgments": [0.0, 0.0, 1.0, 1.0], "truthClass": "no-clickbait"}])
    (r,), rep = loader.load(d / "i.jsonl", d / "t.jsonl", cfg, d)
    assert r.majority_class is None and "class_majority_mismatch" not in r.flags and rep["class_vs_majority_mismatch"] == 0
    assert "class_mean_threshold_mismatch" in r.flags                    # az átlag 0,5, a fájl mégis no-clickbait
