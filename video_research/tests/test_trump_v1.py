"""A trump-v1 esetkészlet és kiértékelő offline tesztje (hamisító modellel; hálózat nélkül). Ez a csővezeték és a kiértékelő viselkedését bizonyítja,
NEM valódi modellminőséget, és nem futásengedély."""
import copy

import pytest

from video_research.acceptance import cases as OLD_CASES
from video_research.acceptance import cases_trump_v1 as T
from video_research.acceptance.eval_trump_v1 import evaluate_trump, hard_ok, pair_summary, render_review
from video_research.acceptance.live import CaseSelectionError, parse_case_list
from video_research.acceptance.runner import run_case
from video_research.llm import LLMResult

A, B = T.CASES


class PhraseModel:
    """Hamisító modell: a megadott szó szerinti kifejezéseket idézi (nem egész szegmenseket, mint a Scripted), a szemantikai ellenőrzés mindig egyező."""
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


def it(quote, kind, statement, **extra):
    return {"quote": quote, "kind": kind, "statement_hu": statement, "why_relevant": "a kérdezett költség/feltétel", "relevance": "direct", "concrete": True, **extra}


L1_Q = "Ki és milyen módszerrel számolta az 1200 és a 4000 dolláros becslést, és milyen forrásból származik?"

GOOD_A = [
    it("he plans to levy twenty-five percent tariffs on everything from Canada and Mexico too", "claim",
       "A beszélő szerint Trump a Kínával szembeni további vámemelések mellett 25 százalékos vámot tervez a Kanadából és Mexikóból érkező árukra.", condition="terv, nem életbe lépett"),
    it("These new tariffs would cost the typical American household an additional one thousand two hundred dollars in 2025", "claim",
       "A beszélő becslése szerint az új vámok az átlagos amerikai háztartásnak 2025-ben további 1200 dollárba kerülnének (feltételes becslés).",
       needs_check="a becslés forrása nincs megnevezve", verification_question=L1_Q),
    it("if Trump makes good on previous pledges to slap tariffs on imports from every country, American families can expect to spend as much as four thousand dollars more", "claim",
       "Ha Trump betartja korábbi ígéreteit és minden ország importjára vámot vet ki, az amerikai családok a beszélő szerint akár négyezer dollárral többet költenének.",
       condition="korábbi ígéretek beváltása; felső határ"),
    it("any revenue raised from tariffs would be coming out of your pocket", "claim", "A beszélő állítása szerint a vámokból származó bevétel a fogyasztók zsebéből jönne ki."),
    it("Trump has suggested he would use the revenue from tariffs to offset more tax cuts for the rich and big corporations", "claim",
       "A beszélő szerint Trump azt javasolta, hogy a vámbevételt a gazdagok és a nagyvállalatok adócsökkentéseinek ellentételezésére fordítsa (szándék, nem döntés)."),
]
GOOD_B = [
    it("25 százalékos vámot tervez kivetni mindenre. Kanadából és Mexikóból is.", "claim",
       "A beszélő szerint Trump a Kínával szembeni további vámemelések mellett 25 százalékos vámot tervez a Kanadából és Mexikóból érkező árukra."),
    it("Ezek az új vámok egy átlagos amerikai háztartásnak sokba kerülnének. további ezerkétszáz dollár 2025-ben.", "claim",
       "A beszélő szerint az új vámok az átlagos amerikai háztartásnak 2025-ben további 1200 dollárba kerülnének (feltételes becslés).",
       needs_check="a becslés forrása nincs megnevezve", verification_question=L1_Q),
    it("De ha Trump betartja korábbi ígéreteit ha minden országból vámot vetnek ki az importra, az amerikai családok várhatóan annyit költenek majd, négyezer dollárral több.", "claim",
       "Ha Trump betartja korábbi ígéreteit és minden ország importjára vámot vet ki, a beszélő szerint akár négyezer dollárral többet költenének az amerikai családok."),
    it("A vámokból származó bevétel a te zsebedből jönne ki.", "claim", "A beszélő állítása szerint a vámokból származó bevétel a fogyasztók zsebéből jönne ki."),
    it("Trump azt javasolta, hogy a vámokból származó bevételt arra fordítsa, hogy ellensúlyozza a gazdagok és nagyvállalatok adócsökkentéseinek növekedését", "claim",
       "A beszélő szerint Trump azt javasolta, hogy a vámbevételt a gazdagok és nagyvállalatok adócsökkentéseinek ellentételezésére fordítsa (szándék, nem döntés)."),
]


def run(case, items, tmp_path):
    res = run_case(case, llm=PhraseModel(copy.deepcopy(items)), tmp=tmp_path)
    return res, evaluate_trump(case, res)


def replace(items, idx, **upd):
    out = copy.deepcopy(items)
    out[idx] = {**out[idx], **upd}
    return out


# --- a készlet és a lefagyasztott bemenet ---
def test_inputs_match_frozen_hashes_and_cases_are_wired_as_expected():
    assert T.text_sha256(T.TEXT_A) == T.TEXT_SHA256["A"] and T.text_sha256(T.TEXT_B) == T.TEXT_SHA256["B"]
    assert [c["id"] for c in T.CASES] == ["TRUMP_A_en", "TRUMP_B_hu"] and {c["version"] for c in T.CASES} == {"trump-v1"}
    assert [c["lang"] for c in T.CASES] == ["en", "hu"] and all(c["fmt"] == "text" and c["question"] == T.QUESTION for c in T.CASES)
    assert "\n".join(A["segments"]) == T.TEXT_A and "\n".join(B["segments"]) == T.TEXT_B
    assert T.TEXT_A.endswith("know whom-") and T.TEXT_B.endswith("kinek...")           # a levágott vég megmarad
    for header in ("Speaker 0", "Hangszóró 0", "2026", "Spoiler"):
        assert header not in T.TEXT_A and header not in T.TEXT_B                          # a fejléc kivéve
    assert [e["id"] for e in T.EXPECTED] == ["E1", "E2", "E3", "E4", "E5"] and T.LEAD_L1["id"] == "L1"


def test_old_frozen_case_set_untouched_and_new_set_not_wired_into_live_controller():
    assert len(OLD_CASES.CASES) == 15 and not any(c["id"].startswith("TRUMP") for c in OLD_CASES.CASES)
    for cid in ("TRUMP_A_en", "TRUMP_B_hu"):
        with pytest.raises(CaseSelectionError):
            parse_case_list(cid)                                                           # az éles vezérlő nem ismeri: külön bekötés és jóváhagyás kell


def test_anchors_present_in_source_texts():
    from video_research.extraction import _norm
    for case, text in ((A, T.TEXT_A), (B, T.TEXT_B)):
        for e in T.EXPECTED:
            assert all(_norm(a) in _norm(text) for a in e["anchors"][case["lang"]]), (case["id"], e["id"])
        assert all(_norm(n) in _norm(text) for n in case["noise"]), case["id"]


# --- jó kimenet: minden automatikus kapu teljesül, nincs segédjelzés ---
@pytest.mark.parametrize("case,items", [(A, GOOD_A), (B, GOOD_B)], ids=["A", "B"])
def test_good_output_passes_all_hard_gates(case, items, tmp_path):
    res, ev = run(case, items, tmp_path)
    assert res["job"].status.value == "completed"
    assert hard_ok(ev), ev["hard"]
    assert ev["aux"] == [], ev["aux"]
    assert set(ev["assignment"]) == {"E1", "E2", "E3", "E4", "E5"}
    assert ev["human_content_judgement"].startswith("függőben")                           # a gép nem mond ki tartalmi ítéletet
    for f in res["report"].findings:
        assert f.verification_status == "not_externally_verified" and all(r.timestamp is None for r in f.source_references)
    out = render_review(case, res, ev)
    assert "Tartalmi megítélés:" in out and "függőben" in out and "megőrzendő:" in out


def test_pair_summary_is_signals_only(tmp_path):
    evs = {c["id"]: run(c, i, tmp_path)[1] for c, i in ((A, GOOD_A), (B, GOOD_B))}
    s = pair_summary(evs)
    assert "TRUMP_A_en" in s and "TRUMP_B_hu" in s and "emberi" in s


# --- a kiértékelő észreveszi a lefagyasztott csapdákat ---
def test_merged_1200_and_4000_is_caught(tmp_path):
    merged = it("These new tariffs would cost the typical American household an additional one thousand two hundred dollars in 2025", "claim",
                "Az új vámok 1200 dollárba, a minden országra kivetettek akár 4000 dollárba kerülnének egy háztartásnak.", needs_check="forrás hiányzik", verification_question=L1_Q)
    res, ev = run(A, [GOOD_A[0], merged, GOOD_A[3], GOOD_A[4]], tmp_path)
    assert ev["hard"]["merged_estimates"] and any(m.startswith("E3") for m in ev["hard"]["missed"])
    assert not hard_ok(ev)


def test_e1_generalized_to_every_country_is_caught_in_hungarian(tmp_path):
    items = replace(GOOD_B, 0, statement_hu="A beszélő szerint 25 százalékos vámot terveznek kivetni mindenre.")
    res, ev = run(B, items, tmp_path)
    assert ev["hard"]["scope_generalized"] and not hard_ok(ev)


def test_noise_as_standalone_finding_is_caught(tmp_path):
    noise = it("this massive transfer of wealth from most Americans to the super-rich", "claim", "A vámok a legtöbb amerikaitól a szupergazdagokhoz juttatnak vagyont.")
    res, ev = run(A, GOOD_A + [noise], tmp_path)
    assert any("zaj önálló találatként" in w for w in ev["hard"]["wrongly_included"]) and not hard_ok(ev)


def test_broken_sentence_completed_as_fact_is_caught(tmp_path):
    broken = it("A befizetett vámok segíthetnének ez a hatalmas vagyonátadás a legtöbb amerikaitól a szupergazdagokhoz", "claim",
                "A befizetett vámok segítenek a vagyon átadásában a legtöbb amerikaitól a szupergazdagoknak.")
    res, ev = run(B, GOOD_B + [broken], tmp_path)
    assert ev["hard"]["broken_sentence_completed"] and not hard_ok(ev)


def test_missing_lead_is_a_miss(tmp_path):
    keep_only = replace(GOOD_B, 1, needs_check=None, verification_question=None)       # B: a következő sor nem feltételt jelző szóval kezdődik, így nem lesz automatikus nyom
    res, ev = run(B, keep_only, tmp_path)
    assert all(f.disposition.value == "keep" for f in res["report"].findings)
    assert any(m.startswith("L1") for m in ev["hard"]["missed"])


def test_english_case_gets_automatic_lead_from_qualifier_heuristic(tmp_path):
    # megfigyelés (nem elvárás): az A esetben az E2 mondatát a „But if…" kezdetű szegmens követi, ezért a rendszer az E2-t akkor is nyomként kezeli, ha a modell nem jelölte
    keep_only = replace(GOOD_A, 1, needs_check=None, verification_question=None)
    res, ev = run(A, keep_only, tmp_path)
    e2 = next(f for f in res["report"].findings if "one thousand two hundred" in f.source_references[0].supporting_quote)
    assert e2.disposition.value == "lead" and e2.verification_question and any(r.role == "qualifier" for r in e2.source_references)


def test_condition_words_missing_only_raise_auxiliary_flags_not_hard_failures(tmp_path):
    items = replace(GOOD_A, 2, statement_hu="A beszélő négyezer dollárt említ a háztartások többletköltségeként.")
    items = replace(items, 4, statement_hu="Trump a vámbevételt adócsökkentésekre fordítja.")
    res, ev = run(A, items, tmp_path)
    assert hard_ok(ev), ev["hard"]
    assert any(a.startswith("E3:") for a in ev["aux"]) and any(a.startswith("E5:") for a in ev["aux"])        # segédjelzés, nem ítélet
    assert "⚠ segédjelzés (szinonimalista, nem ítélet)" in render_review(A, res, ev)


def test_enacted_phrasing_is_flagged_for_human(tmp_path):
    items = replace(GOOD_A, 0, statement_hu="Trump 25 százalékos vámot vetett ki a Kanadából és Mexikóból érkező árukra és Kínára.", condition=None)
    res, ev = run(A, items, tmp_path)
    assert any(a.startswith("E1:") and "életbe" in a for a in ev["aux"])


def test_verified_status_would_be_a_hard_failure(tmp_path, monkeypatch):
    res, ev = run(A, GOOD_A, tmp_path)
    assert not ev["hard"]["verification"]
    monkeypatch.setattr(type(res["report"].findings[0]), "verification_status", property(lambda self: "externally_verified"))
    assert evaluate_trump(A, res)["hard"]["verification"]


def test_no_model_call_and_no_network_in_this_module(tmp_path):
    import video_research.acceptance.cases_trump_v1 as m, video_research.acceptance.eval_trump_v1 as e
    src = open(m.__file__, encoding="utf-8").read() + open(e.__file__, encoding="utf-8").read()
    for word in ("requests", "httpx", "urllib", "socket", "GEMINI_API_KEY", "HttpTransport"):
        assert word not in src
