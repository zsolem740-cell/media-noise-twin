"""A v2 esetkészlet (trump-v2) bekötésének offline tesztjei a VALÓDI vezérlő útvonalán (live.execute / live.main_live), HAMIS átvitellel: valódi hívás és hálózat nincs.
Lefedi: sikeres v2 útvonal (v2 kiértékelő), a nem jóváhagyott státusz / hiányzó dokumentum / lenyomateltérés elutasítása (modellhívás nélkül), a manifeszt tartalma, és a v1 (legacy) változatlan működése."""
import hashlib
import json
import re
from pathlib import Path

import pytest

from validation.hu_pilot.modelrun import Raw
from video_research.acceptance import cases_trump_v2 as C2
from video_research.acceptance import live
from video_research.tests import test_trump_v2 as T2
from video_research.tests.test_live_controller import FIRST as LEGACY_FIRST
from video_research.tests.test_live_controller import FakeApi as LegacyFakeApi

MODEL = "cfg-model-x"
KEYISH = "AIzaDUMMYKEYDUMMYKEYDUMMYKEY99999"
CID = "TRUMP_C_yt_manual"
APPROVED = "2b4596962b7c30465deec0f5ce1bb690667bdc1fc5cc605ab5527e5e03c01158"


class FakeApiV2:
    """Hamis Gemini-szerver a v2 esethez: a szemantikai ellenőrzésre 'consistent', a kinyerésre a jó (GOOD) forgatókönyvet adja Gemini-borítékban."""
    def __init__(self, items=None, model_version=None, per_call_tokens=500):
        self.calls, self.items, self.mv, self.tok = [], (items if items is not None else T2.GOOD), model_version, per_call_tokens

    def __call__(self, model, body):
        self.calls.append(body)
        user = body["contents"][0]["parts"][0]["text"]
        if "Állítás:" in user and "Idézet:" in user:
            payload = {"verdict": "consistent"}
        else:
            payload = {"findings": [{"quotes": [{"segment_id": "x", "quote": it["quote"]}], **{k: v for k, v in it.items() if k != "quote"}} for it in self.items]}
        env = {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}, "finishReason": "STOP"}],
               "usageMetadata": {"promptTokenCount": self.tok, "candidatesTokenCount": 50, "thoughtsTokenCount": 25, "totalTokenCount": self.tok + 75},
               "modelVersion": self.mv or MODEL}
        return Raw(200, json.dumps(env), None, 5)


def run_v2(tmp_path, api, case_ids=None, run_id="TEST-V2-001", **kw):
    b = kw.pop("budget", None) or live.Budget(max_requests=10, max_tokens=30_000, max_seconds=600)
    return live.execute(MODEL, api, b, tmp_path / "out", case_ids or [CID], run_id, min_interval_s=0.0, sleep=lambda _x: None, case_set=live.V2_SET, **kw), b


# ---- sikeres v2 útvonal ----
def test_v2_success_path_runs_through_the_real_controller_with_the_v2_evaluator(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a v1 kiértékelő/futtató nem használható a v2 útvonalon")
    monkeypatch.setattr(live.RUNNER_MOD, "evaluate", boom)
    monkeypatch.setattr(live.RUNNER_MOD, "run_case", boom)
    api = FakeApiV2()
    s, b = run_v2(tmp_path, api)
    assert s["valid_run"] and s["stopped"] is None and s["case_set"] == "trump-v2" and s["cases_not_run"] == []
    r = s["results"][0]
    assert r["id"] == CID and r["ran"] and r["status"] == "completed" and r["hard_ok"] is True and r["content_flags"] == []
    assert set(r["checks"]["assignment"]) == {"E1", "E2", "E3", "E4", "E5"} and not any(r["checks"]["hard"].values())      # a v2 kiértékelő kimenete
    assert r["human_content_judgement"].startswith("függőben")                                                           # a hard_ok nem tartalmi ítélet
    assert s["requests"] == len(api.calls) == b.requests == 6                                                             # 1 kinyerés + 5 szemantikai ellenőrzés
    assert any(x["role"] == "support" and x["timestamp"] is not None for f in r["findings"] for x in f["refs"])         # valódi időbélyegek a feldolgozott kimenetben
    for name in ("manifest.json", "raw_model_io.json", "processed_results.json"):
        assert (tmp_path / "out" / name).exists()


def test_v2_manifest_records_case_set_evaluator_doc_hashes_and_git_state(tmp_path):
    run_v2(tmp_path, FakeApiV2())
    m = json.loads((tmp_path / "out" / "manifest.json").read_text())
    files = live._frozen_files(live.V2_SET)
    assert set(m["hashes"]) == set(files) == {"extraction.py", "cases_trump_v2.py", "evaluator(eval_trump_v2.py)", "evaluator_base(eval_trump_v1.py)", "controller(live.py)", "frozen/expectations_trump_v2.md"}
    for name, path in files.items():
        assert m["hashes"][name] == hashlib.sha256(Path(path).read_bytes()).hexdigest()                                    # TÉNYLEGES lenyomatok
    assert m["case_set"] == "trump-v2" and m["case_set_version"] == "trump-v2" and m["approval_status"] == "approved_frozen" and m["cases"] == [CID]
    doc = m["expectations_doc"]
    assert doc["expected_sha256"] == doc["actual_sha256"] == doc["sha256_in_case_set_constant"] == APPROVED and doc["match"] is True
    assert m["input_text_sha256"] == C2.TEXT_SHA256
    assert re.fullmatch(r"[0-9a-f]{40}", m["commit_sha"]) and isinstance(m["working_tree_clean"], bool) and isinstance(m["dirty_files"], list)         # Git HEAD és munkafa állapota
    assert isinstance(m["pinned_files_modified_vs_head"], list)
    assert m["run_id"] == "TEST-V2-001" and m["semantic_check_enabled"] is True and m["model_id"] == MODEL


# ---- elutasítás modellhívás nélkül ----
def _draft(mp, tmp):
    mp.setattr(C2, "APPROVAL_STATUS", "draft_pending_user_approval")


def _other_status(mp, tmp):
    mp.setattr(C2, "APPROVAL_STATUS", "approved")


def _missing_doc(mp, tmp):
    mp.setattr(live, "v2_doc_path", lambda: tmp / "nincs_ilyen.md")


def _tampered_doc(mp, tmp):
    f = tmp / "doc.md"
    f.write_bytes(live.v2_doc_path().read_bytes() + b"x")
    mp.setattr(live, "v2_doc_path", lambda: f)


def _constant_disagrees(mp, tmp):
    mp.setattr(C2, "EXPECTATIONS_DRAFT_SHA256", "0" * 64)


def _input_changed(mp, tmp):
    mp.setattr(C2, "TEXT_SHA256", "0" * 64)


REFUSALS = [
    pytest.param(_draft, "nem jóváhagyott", id="nem_jovahagyott_statusz"),
    pytest.param(_other_status, "nem jóváhagyott", id="mas_statusz"),
    pytest.param(_missing_doc, "hiányzik a lefagyasztott dokumentum", id="hianyzo_dokumentum"),
    pytest.param(_tampered_doc, "eltér a jóváhagyottól", id="lenyomateltérés"),
    pytest.param(_constant_disagrees, "rögzített elvárás-lenyomata", id="konstans_eltérés"),
    pytest.param(_input_changed, "bemeneti szöveg", id="bemenet_változott"),
]


@pytest.mark.parametrize("breaker,message", REFUSALS)
def test_v2_refuses_in_execute_before_any_model_call_or_output(breaker, message, tmp_path, monkeypatch):
    breaker(monkeypatch, tmp_path)
    api = FakeApiV2()
    with pytest.raises(live.FrozenCaseSetError, match=message):
        run_v2(tmp_path, api)
    assert api.calls == []                                                           # nem történt modellhívás
    assert not (tmp_path / "out").exists()                                           # kimeneti mappa és manifeszt sem jött létre


@pytest.mark.parametrize("breaker,message", REFUSALS)
def test_v2_refuses_in_main_before_any_transport_is_created(breaker, message, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", KEYISH)
    monkeypatch.setenv("VR_GEMINI_MODEL", MODEL)
    import validation.hu_pilot.live.transport as T
    made = []
    monkeypatch.setattr(T, "HttpTransport", lambda *a, **k: made.append(a) or (_ for _ in ()).throw(AssertionError("valódi átvitel nem jöhet létre")))
    breaker(monkeypatch, tmp_path)
    args = ["--live", "--case-set", "trump-v2", "--cases", CID, "--run-id", "RUN-V2-001", "--max-requests", "10", "--max-tokens", "30000", "--max-seconds", "600",
            "--attest-free-tier", "--attest-no-billing", "--attest-owner-rule-change"]
    assert live.main_live(args) == 2
    out = capsys.readouterr().out
    assert "Nem indul hívás" in out and message in out
    assert made == []                                                                # még az átvitel példányosítása sem történt meg


@pytest.mark.parametrize("extra", [["--case-set"], ["--case-set", ""], ["--case-set", "valami"], ["--case-set", "trump-v2", "--cases", "A_tools"], ["--case-set", "trump-v2", "--cases", f"{CID},A_tools"],
                                   ["--case-set", "trump-v2", "--cases", ""], ["--case-set", "trump-v2", "--cases", f"{CID},{CID}"], ["--case-set", "trump-v2", "--cases", "TRUMP_A_en"]])
def test_main_rejects_bad_case_set_or_case_list_without_fallback(extra, monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", KEYISH)
    monkeypatch.setenv("VR_GEMINI_MODEL", MODEL)
    import validation.hu_pilot.live.transport as T
    monkeypatch.setattr(T, "HttpTransport", lambda *a, **k: (_ for _ in ()).throw(AssertionError("valódi átvitel nem jöhet létre")))
    base = ["--live", "--run-id", "RUN-V2-001", "--max-requests", "10", "--max-tokens", "30000", "--max-seconds", "600", "--attest-free-tier", "--attest-no-billing", "--attest-owner-rule-change"]
    has_cases = "--cases" in extra
    assert live.main_live(base + ([] if has_cases else ["--cases", CID]) + extra) == 2
    assert "Nem indul hívás" in capsys.readouterr().out


# ---- esetlisták: a két készlet nem keverhető ----
def test_case_lists_are_set_specific_and_never_mixed():
    assert live.parse_case_list(CID, "trump-v2") == [CID]
    for bad in (None, "", "  ", f"{CID},{CID}", "A_tools", f"{CID},A_tools", f"{CID},", "TRUMP_A_en"):
        with pytest.raises(live.CaseSelectionError):
            live.parse_case_list(bad, "trump-v2")
    with pytest.raises(live.CaseSelectionError):
        live.parse_case_list(CID, "valami")
    assert live.ordered_cases([CID], "trump-v2")[0]["id"] == CID


# ---- futás közbeni módosítás érvényteleníti ----
def test_v2_files_changed_during_the_run_invalidate_it(tmp_path, monkeypatch):
    real, n = live._sha, {"c": 0}

    def flaky(p):
        n["c"] += 1
        return real(p) if n["c"] <= 7 else "0" * 64                                  # 1 (induláskori dokumentum-ellenőrzés) + 6 (manifeszt) után a futás végi újraellenőrzésnél eltér
    monkeypatch.setattr(live, "_sha", flaky)
    s, _ = run_v2(tmp_path, FakeApiV2())
    assert not s["valid_run"] and {"frozen/expectations_trump_v2.md", "evaluator(eval_trump_v2.py)", "cases_trump_v2.py"} <= set(s["frozen_files_changed_during_run"])


# ---- a v2 a main_live útvonalon is (átvitel és pacing kiváltva, hálózat nélkül) ----
def test_v2_through_main_live_end_to_end_offline(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", KEYISH)
    monkeypatch.setenv("VR_GEMINI_MODEL", MODEL)
    monkeypatch.setattr(live, "ROOT", tmp_path)
    monkeypatch.setattr(live, "_git_state", lambda: ("a" * 40, ""))
    monkeypatch.setattr(live, "_modified_vs_head", lambda files: [])
    monkeypatch.setattr("builtins.input", lambda *_a: "IGEN")
    api, made = FakeApiV2(), []
    import validation.hu_pilot.live.transport as T
    monkeypatch.setattr(T, "HttpTransport", lambda *a, **k: made.append(a) or api)
    real = live.execute
    monkeypatch.setattr(live, "execute", lambda *a, **k: real(*a, min_interval_s=0.0, sleep=lambda _x: None, **k))          # csak a várakozást váltjuk ki; az útvonal a valódi
    args = ["--live", "--case-set", "trump-v2", "--cases", CID, "--run-id", "RUN-V2-001", "--max-requests", "10", "--max-tokens", "30000", "--max-seconds", "600",
            "--attest-free-tier", "--attest-no-billing", "--attest-owner-rule-change"]
    assert live.main_live(args) == 0
    assert made == [("gemini", KEYISH, 60.0)] and len(api.calls) == 6
    out = tmp_path / "video_research" / "results" / "RUN-V2-001"
    m = json.loads((out / "manifest.json").read_text())
    p = json.loads((out / "processed_results.json").read_text())
    assert m["case_set"] == "trump-v2" and m["commit_sha"] == "a" * 40 and m["working_tree_clean"] is True and m["expectations_doc"]["match"] is True
    assert p["valid_run"] and p["results"][0]["hard_ok"] is True and p["case_set"] == "trump-v2"
    assert KEYISH not in (out / "raw_model_io.json").read_text() + (out / "processed_results.json").read_text()


# ---- a v1 (legacy) viselkedése változatlan ----
def test_legacy_path_is_unchanged(tmp_path, monkeypatch):
    with pytest.raises(live.CaseSelectionError):
        live.parse_case_list(CID)                                                    # alapértelmezetten (legacy) a v2 azonosító ismeretlen
    assert live.parse_case_list("A_tools,G_needle,D_irrelevant") == LEGACY_FIRST == live.parse_case_list("A_tools,G_needle,D_irrelevant", "legacy")
    m = live.manifest(MODEL, {"max_requests": 10}, LEGACY_FIRST, "RUN-ID-001")
    assert set(m["hashes"]) == {"cases.py", "evaluator(runner.py)", "extraction.py"} and "case_set" not in m and "expectations_doc" not in m

    def boom(*a, **k):
        raise AssertionError("a v2 kiértékelő nem használható a legacy útvonalon")
    monkeypatch.setattr(T2.E2, "evaluate_trump_v2", boom)
    api = LegacyFakeApi(model_version=MODEL)
    s = live.execute(MODEL, api, live.Budget(max_requests=10, max_tokens=30_000, max_seconds=600), tmp_path / "out", LEGACY_FIRST, "TEST-RUN-001", min_interval_s=0.0, sleep=lambda _x: None)
    assert [r["id"] for r in s["results"]] == LEGACY_FIRST and s["valid_run"] and len(api.calls) == 7 and "case_set" not in s     # ugyanaz, mint a v2 bekötés előtt
    assert all("hard" not in r["checks"] for r in s["results"])                                                                   # a v1 kiértékelő kimenetének alakja
