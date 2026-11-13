"""Az AI-kimenet ellenőrzése, a modell bemenetének korlátozása és a séma-fájl egyezése a kóddal."""
import copy
import json

import pytest

from validation.webis_validation import scoring, synthetic
from validation.webis_validation.isolation import MODULE_DIR
from validation.webis_validation.loader import Record

TEXT = "You won't believe the most shocking story: BREAKING!!! 10 things"


def good():
    return {"id": "a1", "source": "webis-clickbait-17", "total": 5, "scaled": 5 / 8, "signals": {
        "curiosity_gap": {"score": 2, "reason": "teases an unrevealed outcome", "span": "You won't believe"},
        "exaggeration": {"score": 1, "reason": "superlative framing", "span": "most shocking"},
        "emotional_pressure": {"score": 0, "reason": "no emotional appeal", "span": ""},
        "formal_noise": {"score": 2, "reason": "caps and listicle", "span": "BREAKING!!!"}}}


def errs(mutator, text=TEXT, cfg=None):
    o = good()
    mutator(o)
    return scoring.validate_score(o, text, cfg)


def test_valid_score_has_no_errors(cfg):
    assert scoring.validate_score(good(), TEXT, cfg) == []


def test_scale_assumption_is_linear_over_eight():
    assert scoring.to_scaled(0) == 0 and scoring.to_scaled(8) == 1 and scoring.to_scaled(4) == 0.5 and scoring.MAX_TOTAL == 8


@pytest.mark.parametrize("mut,frag", [
    (lambda o: o.update(source="hu-clickbait"), "source"),
    (lambda o: o.update(extra=1), "ismeretlen mező"),
    (lambda o: o.pop("total"), "hiányzó mező"),
    (lambda o: o["signals"].pop("formal_noise"), "signals kulcsai"),
    (lambda o: o["signals"].update(bonus={}), "signals kulcsai"),
    (lambda o: o["signals"]["exaggeration"].update(score=3), "0, 1 vagy 2"),
    (lambda o: o["signals"]["exaggeration"].update(score=-1), "0, 1 vagy 2"),
    (lambda o: o["signals"]["exaggeration"].update(score=1.0), "0, 1 vagy 2"),
    (lambda o: o["signals"]["exaggeration"].update(score=True), "0, 1 vagy 2"),
    (lambda o: o["signals"]["exaggeration"].update(reason="one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"), "indoklás"),
    (lambda o: o["signals"]["exaggeration"].update(span="not in the title"), "szó szerinti"),
    (lambda o: o["signals"]["exaggeration"].update(span=""), "szó szerinti"),
    (lambda o: o["signals"]["emotional_pressure"].update(span="You"), "0 pontnál a span üres"),
    (lambda o: o["signals"]["exaggeration"].pop("reason"), "pontosan score, reason, span"),
    (lambda o: o.update(total=6), "total nem egyezik"),
    (lambda o: o.update(total=True), "total nem egyezik"),
    (lambda o: o.update(scaled=0.5), "scaled"),
    (lambda o: o.update(id=""), "id"),
])
def test_rule_violations_are_reported(cfg, mut, frag):
    out = errs(mut, cfg=cfg)
    assert out and any(frag in e for e in out), out


def test_reason_of_exactly_fifteen_words_is_fine(cfg):
    assert errs(lambda o: o["signals"]["exaggeration"].update(reason=" ".join(["w"] * 15)), cfg=cfg) == []


def test_span_check_is_case_sensitive_and_literal(cfg):
    assert errs(lambda o: o["signals"]["exaggeration"].update(span="MOST SHOCKING"), cfg=cfg)


def test_non_dict_input(cfg):
    assert scoring.validate_score(None, TEXT, cfg) == ["az objektum nem szótár"]


def test_mock_scores_are_valid_against_the_validator(cfg):
    inst, _ = synthetic.make_corpus(80, seed=5)
    for r in inst:
        t = r["postText"][0]
        assert scoring.validate_score(synthetic.mock_score(r["id"], t), t, cfg) == []


def test_model_input_contains_only_id_and_postText():
    r = Record(id="x", text="Some title", human_mean=0.9, human_median=1.0, judgments=(1.0,) * 5, n_annotators=5, file_mean=0.9)
    inp = scoring.build_model_input(r)
    assert inp == {"id": "x", "postText": "Some title"}
    assert not set(inp) & set(scoring.FORBIDDEN_MODEL_FIELDS)
    assert "0.9" not in json.dumps(inp)


def test_forbidden_fields_cover_the_leak_list():
    for f in ("targetTitle", "targetParagraphs", "truthMean", "truthJudgments", "publisher", "human_mean", "prior_score", "votes"):
        assert f in scoring.FORBIDDEN_MODEL_FIELDS


def test_schema_file_matches_the_code(cfg):
    sch = json.loads((MODULE_DIR / "schema" / "score.schema.json").read_text(encoding="utf-8"))
    assert set(sch["required"]) == {"id", "source", "signals", "total", "scaled"}
    assert sch["properties"]["source"]["const"] == cfg["source"]
    assert list(sch["properties"]["signals"]["required"]) == list(scoring.SIGNALS) == cfg["scoring"]["signals"]
    assert sch["$defs"]["signal"]["properties"]["score"]["enum"] == [0, 1, 2]
    assert sch["properties"]["total"]["maximum"] == scoring.MAX_TOTAL == 4 * cfg["scoring"]["max_points_per_signal"]
    assert sch["additionalProperties"] is False and sch["$defs"]["signal"]["additionalProperties"] is False
