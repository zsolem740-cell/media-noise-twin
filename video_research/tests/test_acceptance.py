"""Az elfogadási esetek automatikus futtatása (hamisító modellel). Ez a csővezeték viselkedését bizonyítja, nem valódi modellminőséget."""
import pytest

from video_research.acceptance.runner import baseline_cross_language, run_all
from video_research.models import ResearchReport

RESULTS = None


@pytest.fixture(scope="module")
def results():
    return {case["id"]: (case, res, checks) for case, res, checks in run_all()}


def test_every_case_meets_manual_expectations_except_the_deliberate_lossy_one(results):
    for cid, (case, res, checks) in results.items():
        bad = {k: v for k, v in checks.items() if v}
        if case.get("expect_eval_failure"):
            assert set(bad) == {case["expect_eval_failure"]}, (cid, bad)          # a kiértékelő észreveszi az elvesztett korlátozást
        else:
            assert not bad, (cid, bad)


def test_question_drives_different_output_on_same_transcript(results):
    a, b = results["A_tools"][1]["report"], results["B_errors"][1]["report"]
    assert a.findings and b.findings
    assert {f.category.value for f in a.findings}.isdisjoint({f.category.value for f in b.findings})
    # a kérdés tényleg bekerült a modellnek küldött kérésbe, a két futás csak a kérdésben (és abból következően a kimenetben) tér el
    pa = next(u for s, u in results["A_tools"][1]["llm"].prompts if s == "findings")
    pb = next(u for s, u in results["B_errors"][1]["llm"].prompts if s == "findings")
    assert "eszközök és előfeltételek" in pa and "hibákat vagy korlátokat" in pb


def test_english_transcript_hungarian_statement_quote_stays_original(results):
    r = results["A_tools"][1]["report"]
    for f in r.findings:
        ref = f.source_references[0]
        assert f.statement_is_translation and ref.quote_language == "en"
        assert f.statement_hu != ref.supporting_quote and any(w in f.statement_hu for w in ("Android", "AutoDroid", "Gemini"))
        assert ref.supporting_quote in " ".join(case_seg for case_seg in results["A_tools"][0]["segments"])         # idézet szó szerint az eredetiből


def test_zero_result_cases_are_completed_with_note_not_failures(results):
    for cid in ("D_irrelevant", "E_ad"):
        job, r = results[cid][1]["job"], results[cid][1]["report"]
        assert job.status.value == "completed" and r.findings == [] and r.no_result_note


def test_exact_quote_unverified_claim_is_lead_and_never_externally_verified(results):
    f = results["F_unverified"][1]["report"].findings[0]
    assert f.report_bucket == "lead" and f.verification_status == "not_externally_verified"
    assert f.source_support_status == "supported_by_passage"           # a (hamisított) szemantikai ellenőr egyezőnek ítélte, mégis nyom marad: a két tengely független


def test_injection_candidate_skipped_and_model_cannot_set_verification(results):
    r = results["J_injection"][1]["report"]
    assert [f.statement_hu for f in r.findings] == ["Az AutoDroid alkalmazás szükséges."]
    assert all(f.verification_status == "not_externally_verified" and f.report_bucket == "keep" for f in r.findings)
    assert any(e.reason_code.value == "suspected_injection" for e in r.filter_log)


def test_missing_timestamps_stay_null_and_are_stated(results):
    r = results["I_no_timestamps"][1]["report"]
    f = r.findings[0]
    assert f.source_references[0].timestamp is None and any("nem tartalmaz időbélyeget" in l for l in f.limitations)
    from video_research.report import to_markdown
    assert "időbélyeg nem ismert" in to_markdown(r, results["I_no_timestamps"][1]["job"])


def test_contradiction_flagged_not_resolved(results):
    r = results["H_contradiction"][1]["report"]
    assert len(r.findings) == 2 and len(r.contradictions) == 1 and "nem döntötte el" in r.contradictions[0]["note"]


def test_baseline_is_labelled_not_ai_and_misses_semantic_items():
    txt, checks = baseline_cross_language()
    assert "NEM AI" in txt and checks["missed"] and checks["wrongly_included"]


def test_known_information_repeat_does_not_grow_main_report_and_is_not_confirmation(results):
    case, res, _ = results["L_known_counter"]
    r, job = res["report"], res["job"]
    from video_research.report import evidence_markdown, to_markdown
    main, ev = to_markdown(r, job), evidence_markdown(r, job)
    assert [f.version for f in r.findings] == ["Android 14"] and r.findings[0].extends_known == case["known"][0]
    assert main.count("Az alkalmazás minden Android-verzión működik") == 0                # az ismert állítás ismétlése nincs a fő jelentésben
    assert "nem független" in main and "Ismert információt ismétlő részlet: 1" in main
    assert "nem független megerősítés" in ev and r.findings[0].verification_status == "not_externally_verified"
    assert r.findings[0].evidence_status.value == "source_claim"                           # az ismert + új URL nem lett „repeated”


def test_following_sentence_condition_is_kept_as_qualifier_reference(results):
    lost = results["K_multiseg_lost"][1]["report"].findings[0]
    assert lost.report_bucket == "lead" and [r.role for r in lost.source_references] == ["support", "qualifier"]
    assert "accessibility" in lost.source_references[1].supporting_quote and "kisegítő" not in lost.statement_hu
    assert "accessibility" in lost.verification_question
    ok = results["K_multiseg_ok"][1]["report"].findings[0]
    assert ok.report_bucket == "keep" and [r.role for r in ok.source_references] == ["support", "support"]     # a modell mindkét mondatot idézte: nincs felesleges nyom


def test_every_lead_has_verification_question_and_irrelevant_is_never_a_lead(results):
    for cid, (case, res, checks) in results.items():
        for f in res["report"].findings:
            if f.report_bucket == "lead":
                assert (f.verification_question or "").strip(), cid
    assert results["N_unreliable"][1]["report"].filter_log[0].reason_code.value in ("extraction_unreliable", "irrelevant")
