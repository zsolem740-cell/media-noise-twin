"""A trump-v2 esetkészlet és kiértékelő offline tesztje (hamisító modellel; hálózat nélkül). A csővezeték és a kiértékelő viselkedését bizonyítja,
NEM valódi modellminőséget, és nem futásengedély."""
import copy
import hashlib
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_research.acceptance import cases_trump_v2 as T
from video_research.acceptance import eval_trump_v2 as E2
from video_research.acceptance.eval_trump_v2 import (AUTO_GENERIC_LEAD_REASON, AUTO_PARTIAL_REASON, AUTO_QUALIFIER_REASON, AUTO_QUALIFIER_VQ, AUTO_UNTRANSLATED_REASON, AUTO_UNTRANSLATED_VQ,
                                                      ORIGIN_MARKERS, NOT_A_NAMED_CHECK_REASONS, PIPELINE_REASON_SITES, evaluate_trump_v2, expected_start, hard_ok, is_model_named_check_with_question, render_review, run_case_v2,
                                                      unsupported_numbers)
from video_research.acceptance.eval_trump_v1 import _has
from video_research import extraction
from video_research.acceptance.live import CaseSelectionError, parse_case_list
from video_research.extraction import _norm
from video_research.llm import LLMResult

C = T.CASES[0]


class PhraseModel:
    provider, model, kind = "phrase-fake", "phrase", "ai"

    def __init__(self, items):
        self.items, self.prompts = items, []

    def complete_json(self, *, system, user, schema_name, max_tokens):
        self.prompts.append((schema_name, user))
        if schema_name == "semantic":
            return LLMResult({"verdict": "consistent"}, 1)
        out = []
        for it in self.items:
            it = dict(it)
            out.append({"quotes": [{"segment_id": "x", "quote": it.pop("quote")}], **it})
        return LLMResult({"findings": out}, 50)


def it(quote, statement, **extra):
    return {"quote": quote, "kind": "claim", "statement_hu": statement, "why_relevant": "a kérdezett költség/feltétel", "relevance": "direct", "concrete": True, **extra}


L1_Q = "Ki és milyen módszerrel számolta az 1200 és a 4000 dolláros becslést, és milyen forrásból származik?"
GOOD = [
    it("he plans to levy 25% tariffs on everything from Canada and Mexico too",
       "A beszélő szerint Trump a Kínával szembeni további vámemelések mellett 25 százalékos vámot tervez a Kanadából és Mexikóból érkező árukra.", condition="terv, nem életbe lépett"),
    it("These new tariffs would cost the typical American household an additional $1,200 in 2025.",
       "A beszélő becslése szerint az új vámok az átlagos amerikai háztartásnak 2025-ben további 1200 dollárba kerülnének (feltételes becslés).",
       needs_check="a becslés forrása nincs megnevezve", verification_question=L1_Q),
    it("if Trump makes good on previous pledges to slap tariffs on imports from every country, American families can expect to spend as much as $4,000 more.",
       "Ha Trump betartja korábbi ígéreteit és minden ország importjára vámot vet ki, az amerikai családok a beszélő szerint akár 4000 dollárral többet költenének.",
       condition="korábbi ígéretek beváltása; felső határ"),
    it("any revenue raised from tariffs would be coming out of your pocket.", "A beszélő állítása szerint a vámokból származó bevétel a fogyasztók zsebéből jönne ki."),
    it("Trump has suggested he would use the revenue from tariffs to “offset” more tax cuts for the rich and big corporations.",
       "A beszélő szerint Trump azt javasolta, hogy a vámbevételt a gazdagok és a nagyvállalatok adócsökkentéseinek ellentételezésére fordítsa (szándék, nem döntés)."),
]


def run(items, tmp_path):
    res = run_case_v2(C, PhraseModel(copy.deepcopy(items)), tmp=tmp_path)
    return res, evaluate_trump_v2(C, res)


def replace(items, idx, **upd):
    out = copy.deepcopy(items)
    out[idx] = {**out[idx], **upd}
    return out


# --- a készlet, a bemenet és az állapot ---
def test_input_hash_and_srt_times_and_provenance():
    assert T.text_sha256() == T.TEXT_SHA256 and T.CASE_SET_VERSION == "trump-v2" and len(T.CASES) == 1 and C["id"] == "TRUMP_C_yt_manual"
    assert T.TEXT.endswith("know whom to blame.") and "Speaker" not in T.TEXT                         # a vég teljes, nincs fejléc
    assert "00:04:09,082 --> 00:04:11,542" in C["srt"] and "00:05:04,053 --> 00:05:10,184" in C["srt"]  # a hosszú videó valódi időbélyegei
    assert C["source"]["video_id"] == "AfVGUiet39E" and C["source"]["track"] == "manual en-US" and "not image-verified" in C["source"]["relation_to_short"]
    assert C["fmt"] == "srt" and C["lang"] == "en" and C["timestamps_null"] is False


def test_status_is_draft_until_user_approves_and_not_wired_into_live_controller():
    assert T.APPROVAL_STATUS in ("draft_pending_user_approval", "approved_frozen")
    if T.APPROVAL_STATUS == "approved_frozen":
        assert T.EXPECTATIONS_DRAFT_SHA256                                                          # jóváhagyás után a lenyomatot rögzíteni kell
    with pytest.raises(CaseSelectionError):
        parse_case_list("TRUMP_C_yt_manual")                                                         # az éles vezérlő nem ismeri: külön bekötés és jóváhagyás kell


def test_anchors_present_and_noise_phrases_present():
    for e in T.EXPECTED:
        assert all(_norm(a) in _norm(T.TEXT) for a in e["anchors"]["en"]), e["id"]
    assert all(_norm(n) in _norm(T.TEXT) for n in C["noise"])


def test_auto_qualifier_strings_match_the_pipeline():
    keep_only = replace(GOOD, 1, needs_check=None, verification_question=None)
    res = run_case_v2(C, PhraseModel(copy.deepcopy(keep_only)))
    e2 = next(f for f in res["report"].findings if "1,200" in f.source_references[0].supporting_quote)
    assert e2.disposition.value == "lead" and any(r.startswith(AUTO_QUALIFIER_REASON) for r in e2.lead_reasons) and e2.verification_question.startswith(AUTO_QUALIFIER_VQ)


# --- jó kimenet ---
def test_good_output_passes_hard_gates_with_real_timestamps(tmp_path):
    res, ev = run(GOOD, tmp_path)
    assert res["job"].status.value == "completed"
    assert hard_ok(ev), ev["hard"]
    assert ev["aux"] == [], ev["aux"]
    assert set(ev["assignment"]) == {"E1", "E2", "E3", "E4", "E5"}
    by = {f.id: f for f in res["report"].findings}
    e2 = by[ev["assignment"]["E2"]]
    assert e2.source_references[0].timestamp == pytest.approx(258.174, abs=1e-3)                    # valódi időbélyeg, nem null és nem a 6 s-os rács
    assert ev["human_content_judgement"].startswith("függőben")
    out = render_review(C, res, ev)
    assert "függőben" in out and "megőrzendő:" in out


# --- az L1 szigorítása (negatív és pozitív teszt) ---
def test_automatic_qualifier_lead_alone_does_not_satisfy_L1(tmp_path):
    items = replace(GOOD, 1, needs_check=None, verification_question=None)        # az E2-t a modell nem jelöli nyomnak
    res, ev = run(items, tmp_path)
    e2 = next(f for f in res["report"].findings if "1,200" in f.source_references[0].supporting_quote)
    assert e2.disposition.value == "lead"                                           # a rendszer automatikusan lead-re tette ("But if…" a következő sorban)
    assert any(m.startswith("L1") for m in ev["hard"]["missed"]) and not hard_ok(ev)
    assert any(a.startswith("L1:") and "automatikus" in a for a in ev["aux"])


def test_model_originated_lead_with_unrelated_question_passes_structurally_but_is_flagged(tmp_path):
    items = replace(GOOD, 1, needs_check="az évszám ellenőrzendő", verification_question="Tényleg 2025-re szól a becslés?")
    res, ev = run(items, tmp_path)
    assert not any(m.startswith("L1") for m in ev["hard"]["missed"])               # szerkezetileg modelltől származó nyom
    assert any(a.startswith("L1:") and "nem utal" in a for a in ev["aux"])        # de a tartalmi megfelelés emberi megítélés
    assert ev["review_rows"][-1]["id"] == "L1" and ev["review_rows"][-1]["found"]


def test_untranslated_statement_lead_does_not_satisfy_L1(tmp_path):
    # a modell az angol idézetet változatlanul adja állításként, nyomjelölés nélkül: a rendszer a fordítás hiánya miatt képez automatikus nyomot
    quote = "These new tariffs would cost the typical American household an additional $1,200 in 2025."
    items = replace(GOOD, 1, statement_hu=quote, needs_check=None, verification_question=None)
    res, ev = run(items, tmp_path)
    e2 = next(f for f in res["report"].findings if "1,200" in f.source_references[0].supporting_quote)
    assert e2.disposition.value == "lead" and any(r.startswith(AUTO_UNTRANSLATED_REASON) for r in e2.lead_reasons) and e2.verification_question.startswith(AUTO_UNTRANSLATED_VQ)   # a pipeline tényleges szövege
    assert any(m.startswith("L1") for m in ev["hard"]["missed"]) and not hard_ok(ev)
    assert any(a.startswith("L1:") and "automatikus kiegészítés" in a and "nem teljesíti az L1-et" in a for a in ev["aux"])


def test_untranslated_statement_with_model_reason_but_no_model_question_still_fails_L1(tmp_path):
    quote = "These new tariffs would cost the typical American household an additional $1,200 in 2025."
    items = replace(GOOD, 1, statement_hu=quote, needs_check="a becslés forrása nincs megnevezve", verification_question=None)
    res, ev = run(items, tmp_path)
    e2 = next(f for f in res["report"].findings if "1,200" in f.source_references[0].supporting_quote)
    assert e2.verification_question.startswith(AUTO_UNTRANSLATED_VQ)                  # nincs modell-kérdés: az automatikus kérdés lép be
    assert any(m.startswith("L1") for m in ev["hard"]["missed"])


def test_origin_markers_are_narrowed_and_generic_words_no_longer_count(tmp_path):
    assert "becslés" not in ORIGIN_MARKERS and "számít" not in ORIGIN_MARKERS and "forrás" in ORIGIN_MARKERS
    flagged = replace(GOOD, 1, needs_check="az összeg ellenőrzendő", verification_question="Tényleg 2025-re szól a becslés?")
    _, ev = run(flagged, tmp_path)
    assert any(a.startswith("L1:") and "nem utal" in a for a in ev["aux"])                 # "becslés" önmagában már nem forrásjelzés
    ok = replace(GOOD, 1, needs_check="a forrás hiányzik", verification_question="Milyen forrásból származik ez az összeg, és ki számolta?")
    _, ev2 = run(ok, tmp_path)
    assert not any(a.startswith("L1:") for a in ev2["aux"]) and hard_ok(ev2), (ev2["aux"], ev2["hard"])


# --- időbélyeg és számátvitel ---
def test_wrong_timestamp_is_a_hard_failure(tmp_path):
    res, _ = run(GOOD, tmp_path)
    res["report"].findings[0].source_references[0].timestamp = 1.0
    assert evaluate_trump_v2(C, res)["hard"]["timestamp_bad"]


def test_year_carried_from_E2_into_E3_is_a_content_error_even_when_hard_ok_is_true(tmp_path):
    items = replace(GOOD, 2, statement_hu="Ha Trump betartja korábbi ígéreteit, 2025-ben akár 4000 dollárral többet költenének az amerikai családok (a beszélő szerint).")
    res, ev = run(items, tmp_path)
    assert hard_ok(ev), ev["hard"]                                                           # a kemény kapuk NEM fogják meg
    assert any(a.startswith("E3:") and "TARTALMI HIBA GYANÚ" in a and "2025" in a for a in ev["aux"])
    assert ev["content_flags"] and "TARTALMI HIBA GYANÚ" in ev["human_content_judgement"] and ev["human_content_judgement"].startswith("függőben")   # emberi elbírálást kér, ítéletet nem mond
    row = next(r for r in ev["review_rows"] if r["id"] == "E3")
    assert any("TARTALMI HIBA GYANÚ" in fl for fl in row["flags"])                           # az E3 sorban látszik a felülvizsgálati lapon
    assert "TARTALMI HIBA GYANÚ" in render_review(C, res, ev)


def test_clean_run_has_no_content_flags(tmp_path):
    _, ev = run(GOOD, tmp_path)
    assert ev["content_flags"] == [] and ev["human_content_judgement"] == "függőben (emberi megítélés)"


def test_other_unsupported_numbers_stay_plain_auxiliary_hints(tmp_path):
    items = replace(GOOD, 1, statement_hu="A beszélő becslése szerint az új vámok az átlagos amerikai háztartásnak 2024-ben további 1200 dollárba kerülnének (feltételes becslés).")
    _, ev = run(items, tmp_path)
    assert hard_ok(ev) and ev["content_flags"] == []
    assert any(a.startswith("E2:") and "2024" in a for a in ev["aux"])


def test_expected_start_helper():
    assert expected_start(C, "These new tariffs would cost the typical") == pytest.approx(258.174)
    assert expected_start(C, "to slap tariffs on imports from every country, American families") == pytest.approx(268.935)
    assert expected_start(C, "nincs ilyen idézet a szövegben") is None


def test_v1_modules_untouched_and_no_network_in_v2_modules():
    from video_research.acceptance import cases_trump_v1 as V1
    assert V1.CASE_SET_VERSION == "trump-v1" and V1.FROZEN_EXPECTATIONS_SHA256 == "3adfa04c909047741a5dd7d28c0256543444d6009262d225486b58fbeaeef83a"
    src = open(T.__file__, encoding="utf-8").read() + open(E2.__file__, encoding="utf-8").read()
    for word in ("requests", "httpx", "urllib", "socket", "GEMINI_API_KEY", "HttpTransport"):
        assert word not in src


# --- L1 (K3a+K4): ugyanazon a lead-en modelltől származó, nem üres needs_check ÉS modelltől származó kérdés ---
UQ = "These new tariffs would cost the typical American household an additional $1,200 in 2025."
NC, MQ = "a becslés forrása nincs megnevezve", "Ki számolta ki ezt az összeget?"


def l1_missed(ev):
    return any(m.startswith("L1") for m in ev["hard"]["missed"])


L1_MATRIX = [
    ("1 ok+kérdés a modelltől", dict(needs_check=NC, verification_question=MQ), False),
    ("2 csak az ok a modelltől", dict(needs_check=NC, verification_question=None), True),
    ("3 csak a kérdés a modelltől", dict(needs_check=None, verification_question=MQ), True),
    ("4 egyik sem", dict(needs_check=None, verification_question=None), True),
    ("5 fordítatlan + ok + kérdés", dict(statement_hu=UQ, needs_check=NC, verification_question=MQ), False),
    ("6 fordítatlan + csak ok", dict(statement_hu=UQ, needs_check=NC, verification_question=None), True),
    ("7 fordítatlan + csak kérdés", dict(statement_hu=UQ, needs_check=None, verification_question=MQ), True),
    ("8 részben releváns + kérdés, nincs needs_check (javítva: bukik)", dict(relevance="partial", needs_check=None, verification_question=MQ), True),
    ("9 részben releváns, nincs kérdés", dict(relevance="partial", needs_check=None, verification_question=None), True),
    ("10 általános nyomjelölés (kind=lead) + kérdés, nincs needs_check", dict(kind="lead", needs_check=None, verification_question=MQ), True),
    ("11 részben releváns + needs_check + kérdés (pozitív kontroll)", dict(relevance="partial", needs_check=NC, verification_question=MQ), False),
    ("12 üres (szóközös) needs_check + kérdés", dict(needs_check="   ", verification_question=MQ), True),
    ("13 üres kérdés + needs_check", dict(needs_check=NC, verification_question=""), True),
    ("14 csak szóközös kérdés + needs_check", dict(needs_check=NC, verification_question="   "), True),
    ("15 üres needs_check + üres kérdés", dict(needs_check="", verification_question=""), True),
]


@pytest.mark.parametrize("name,kw,expect_missed", L1_MATRIX, ids=[m[0].split(" ")[0] for m in L1_MATRIX])
def test_L1_matrix(name, kw, expect_missed, tmp_path):
    res, ev = run(replace(GOOD, 1, **kw), tmp_path)
    assert l1_missed(ev) is expect_missed, (name, ev["hard"]["missed"], ev["aux"])
    if not expect_missed:
        assert hard_ok(ev), ev["hard"]


def test_partial_relevance_and_generic_lead_reasons_are_not_named_checks(tmp_path):
    res, _ = run(replace(GOOD, 1, relevance="partial", needs_check=None, verification_question=MQ), tmp_path)
    e2 = next(f for f in res["report"].findings if "1,200" in f.source_references[0].supporting_quote)
    assert e2.lead_reasons[0].startswith(AUTO_PARTIAL_REASON)                          # a pipeline tényleges szövege
    res, _ = run(replace(GOOD, 1, kind="lead", needs_check=None, verification_question=MQ), tmp_path)
    e2 = next(f for f in res["report"].findings if "1,200" in f.source_references[0].supporting_quote)
    assert any(r.startswith(AUTO_GENERIC_LEAD_REASON) for r in e2.lead_reasons)


def test_L1_can_be_satisfied_by_the_E3_lead(tmp_path):
    items = replace(replace(GOOD, 1, needs_check=None, verification_question=None), 2, needs_check=NC, verification_question=MQ)       # az E2 csak automatikus nyom, az E3 a modell nyoma
    res, ev = run(items, tmp_path)
    assert not l1_missed(ev) and hard_ok(ev), (ev["hard"], ev["aux"])
    assert ev["review_rows"][-1]["id"] == "L1" and "4 000" in _norm(ev["review_rows"][-1]["quotes"][0])


def test_pipeline_reason_sources_match_the_evaluator_denylist():
    """Dokumentált REGRESSZIÓS védőháló (nem kimerítő eredetbizonyítás): az L1-kapu tiltólistás eredetbecslése az extraction.py üzenetszövegeire épül. Ha egy rögzített szöveg megváltozik,
    vagy az ok-képzési helyek száma változik, ez a teszt bukik. Azt nem bizonyítja, hogy minden jövőbeli ok-típust helyesen osztályozunk."""
    src = inspect.getsource(extraction._validate_items)
    assert src.count("reasons.append(") == PIPELINE_REASON_SITES                       # 4 rögzített szöveg + a modell needs_check-je
    for fixed in NOT_A_NAMED_CHECK_REASONS + (AUTO_QUALIFIER_VQ, AUTO_UNTRANSLATED_VQ):
        assert fixed in src, fixed


# --- jelzőszavak: az izolált és a dokumentált korlátok ---
def test_isolated_ki_szamol_marker_matches_only_that_marker_and_is_only_an_auxiliary_hint(tmp_path):
    q = "Ki számolta ki ezt az összeget?"
    assert [m for m in ORIGIN_MARKERS if m in q.casefold()] == ["ki számol"]            # a "ki számolta" alak a "ki számol" részszövegre illeszkedik, mást nem érint
    _, ev = run(replace(GOOD, 1, needs_check=NC, verification_question=q), tmp_path)
    assert hard_ok(ev) and not l1_missed(ev) and not any(a.startswith("L1:") for a in ev["aux"])
    # a jelzőszó megléte NEM bizonyítja a megfelelést: ugyanez a kérdés kemény kapun nem múlik, a tartalmi megítélés emberi (human_content_judgement függőben)
    assert ev["human_content_judgement"].startswith("függőben")


def test_marker_list_known_limits_are_documented_behaviour():
    assert not _has("Számolta ki valaki ezt?", ORIGIN_MARKERS)                           # téves negatív: fordított szórend
    assert _has("Honnan tudjuk, hogy 2025-re szól?", ORIGIN_MARKERS)                     # téves pozitív: évszámkérdés "honnan"-nal
    assert not _has("Tényleg 2025-re szól a becslés?", ORIGIN_MARKERS)


# --- megvalósítási korlátok: időbélyeg-ablak és ismétlődő idézet ---
def test_six_segment_quote_is_accepted_and_seven_segment_quote_is_not(tmp_path):
    six = " ".join(T.LINES[8:14])
    res, ev = run(replace(GOOD, 3, quote=six), tmp_path)
    e4 = next(f for f in res["report"].findings if "pocket" in f.source_references[0].supporting_quote)
    assert e4.source_references[0].timestamp == pytest.approx(285.326, abs=1e-3) and hard_ok(ev), ev["hard"]     # az ablak első szegmensének kezdete
    seven = " ".join(T.LINES[7:14])
    res7, ev7 = run(replace(GOOD, 3, quote=seven), tmp_path)
    assert not any("pocket" in f.source_references[0].supporting_quote for f in res7["report"].findings)         # a pipeline 6 szegmensnél hosszabb idézetet nem fogad el
    assert any(m.startswith("E4") for m in ev7["hard"]["missed"])


def test_repeated_quote_resolves_to_first_occurrence_documented_limit():
    case = {"segments": ["the same phrase is repeated here", "something else entirely different", "the same phrase is repeated here"], "starts_s": [1.0, 2.0, 3.0]}
    assert expected_start(case, "the same phrase is repeated here") == 1.0              # a második előfordulásra való hivatkozást az ellenőrzés nem különbözteti meg


# --- szóköz-kizárás: pipeline-garancia és kiértékelő-oldali ellenőrzés ---
def test_pipeline_strips_needs_check_and_question_before_use():
    """A pipeline oldali garancia forrásszinten: a needs_check és a kérdés .strip()-elt, üres needs_check nem lesz ok. (Regressziós védőháló; a viselkedést a mátrix 12-15. esete bizonyítja.)"""
    src = inspect.getsource(extraction._validate_items)
    assert 'needs = str(item.get("needs_check") or "").strip()' in src and 'vq = str(item.get("verification_question") or "").strip()' in src
    assert "if needs:\n            reasons.append(needs)" in src


@pytest.mark.parametrize("reasons,question,expected", [
    ([NC], MQ, True),                                                   # pozitív kontroll
    ([f"  {NC}  "], f"  {MQ}  ", True),                                 # környező szóköz nem árt
    (["", NC], MQ, True),                                               # üres ok mellett van valódi ok
    (["   "], MQ, False),                                               # csak szóközös ok
    ([""], MQ, False),                                                  # üres ok
    ([], MQ, False),                                                    # nincs ok
    (None, MQ, False),
    ([NC], "", False),                                                  # üres kérdés
    ([NC], "   ", False),                                               # csak szóközös kérdés
    ([NC], None, False),
    ([f"  {AUTO_UNTRANSLATED_REASON}: ..."], MQ, False),                 # vezető szóközös automatikus ok is automatikus
    ([f"  {AUTO_PARTIAL_REASON}"], MQ, False),
    ([NC], f"  {AUTO_QUALIFIER_VQ}: „...”?", False),                     # vezető szóközös automatikus kérdés is automatikus
    ([NC], f"{AUTO_UNTRANSLATED_VQ}, és releváns-e a kérdéshez?", False),
])
def test_evaluator_requires_nonblank_reason_and_question_independently_of_the_pipeline(reasons, question, expected):
    f = SimpleNamespace(lead_reasons=reasons, verification_question=question)
    assert is_model_named_check_with_question(f) is expected


# --- számátvitel: mely idézeteket vizsgálja ---
def test_number_check_uses_the_union_of_support_and_qualifier_quotes():
    support = SimpleNamespace(role="support", supporting_quote="would cost an additional $1,200")
    qualifier = SimpleNamespace(role="qualifier", supporting_quote="But in 2025 things change")
    assert unsupported_numbers("1200 dollár 2025-ben", [support, qualifier]) == []                  # a 2025 csak a minősítő idézetében van: a fő+minősítő unió fedezi
    assert unsupported_numbers("1200 dollár 2025-ben", [support]) == ["2025"]                       # csak a fő idézettel jelezné
    assert unsupported_numbers("1200 dollár", []) == ["1200"]


def test_repeated_quote_later_correct_occurrence_would_be_rejected_documented_limit():
    case = {"segments": ["the same phrase is repeated here", "something else entirely different", "the same phrase is repeated here"], "starts_s": [1.0, 2.0, 3.0]}
    later_correct_reference = 3.0                                                                    # a második előfordulás kezdete: helyes hivatkozás lenne
    assert abs(later_correct_reference - expected_start(case, "the same phrase is repeated here")) > 0.0015   # a jelenlegi ellenőrzés ezt hibás időbélyegként utasítaná el (téves bukás)


# --- lefagyasztott állapot: a jóváhagyott dokumentum rögzítése ---
def test_frozen_state_pins_the_approved_document():
    approved = "2b4596962b7c30465deec0f5ce1bb690667bdc1fc5cc605ab5527e5e03c01158"
    assert T.APPROVAL_STATUS == "approved_frozen" and T.EXPECTATIONS_DRAFT_SHA256 == approved
    doc = Path(T.__file__).parent / "frozen" / "expectations_trump_v2.md"
    assert hashlib.sha256(doc.read_bytes()).hexdigest() == approved                      # a repóbeli másolat bájtjai a jóváhagyottal azonosak
