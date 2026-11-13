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
    assert all(0 <= r.human_mean <= 1 and r.human_median in (0.0, 0.33, 0.66, 1.0) for r in recs)


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
