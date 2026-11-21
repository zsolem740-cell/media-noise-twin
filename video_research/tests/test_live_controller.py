"""A valódi-modell futás vezérlőjének tesztjei HAMIS átvitellel (valódi hívás nincs): keretek, megállási szabályok, lefagyasztás, kulcsvédelem."""
import json
import re
from pathlib import Path

import pytest

from validation.hu_pilot.modelrun import Raw
from video_research.acceptance import live
from video_research.acceptance import runner as R
from video_research.acceptance.cases import CASES

MODEL = "cfg-model-x"
KEYISH = "AIzaDUMMYKEYDUMMYKEYDUMMYKEY99999"


class FakeApi:
    """Hamis Gemini-szerver: a kérésből felismeri az esetet, és a forgatókönyves modell válaszát adja Gemini-borítékban."""
    def __init__(self, script=None, model_version=None, per_call_tokens=500):
        self.calls, self.script, self.mv, self.tok = [], script or {}, model_version, per_call_tokens
        self.by_key = {}
        for c in CASES:
            self.by_key[(c["question"], c["segments"][0])] = c

    def __call__(self, model, body):
        n = len(self.calls) + 1
        self.calls.append(body)
        if n in self.script:
            r = self.script[n]
            if isinstance(r, Exception):
                raise r
            return r
        user = body["contents"][0]["parts"][0]["text"]
        if "Állítás:" in user and "Idézet:" in user:
            payload = {"verdict": "consistent"}
        else:
            q = re.search(r"Kutatási kérdés: (.*)", user).group(1)
            block = user.split("<untrusted_transcript>")[1].split("</untrusted_transcript>")[0].strip().splitlines()
            first = block[0].split("] ", 1)[1]
            case = self.by_key[(q.splitlines()[0], first)]
            out = R.Scripted(case["model"], case.get("doubtful_if")).complete_json(system="", user=user, schema_name="findings", max_tokens=1).data
            payload = out
        body_ = {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}, "finishReason": "STOP"}],
                 "usageMetadata": {"promptTokenCount": self.tok, "candidatesTokenCount": 50, "thoughtsTokenCount": 25, "totalTokenCount": self.tok + 75},
                 "modelVersion": self.mv or MODEL}
        return Raw(200, json.dumps(body_), None, 5)


ALL = [c["id"] for c in CASES if c["id"] != "B_lossy"]
FIRST = ["A_tools", "G_needle", "D_irrelevant"]


def run(tmp_path, api, cases=None, **kw):
    b = kw.pop("budget", None) or live.Budget()
    return live.execute(MODEL, api, b, tmp_path / "out", cases or ALL, "TEST-RUN-001", min_interval_s=0.0, sleep=lambda _x: None, **kw), b


def test_explicit_full_list_runs_in_given_order_in_one_budget(tmp_path):
    api = FakeApi()
    s, b = run(tmp_path, api)
    ids = [r["id"] for r in s["results"]]
    assert ids == ALL and "B_lossy" not in ids and len(ids) == 14
    assert s["requests"] == len(api.calls) == b.requests and s["valid_run"] and s["stopped"] is None
    assert s["tokens"]["thoughts"] > 0 and s["tokens"]["counted_total"] == (api.tok + 75) * len(api.calls)          # a gondolkodási token is beszámít
    assert all(r["ran"] for r in s["results"]) and not any(r.get("error") for r in s["results"])
    for name in ("manifest.json", "raw_model_io.json", "processed_results.json"):
        assert (tmp_path / "out" / name).exists()


def test_request_cap_includes_everything_and_stops_run(tmp_path):
    api = FakeApi()
    s, b = run(tmp_path, api, budget=live.Budget(max_requests=5))
    assert len(api.calls) == 5 and s["requests"] == 5 and "kérés keret" in s["stopped"]
    assert any(r.get("reason", "").startswith("nem futott") for r in s["results"])


def test_retries_count_as_requests(tmp_path):
    err = Raw(503, json.dumps({"error": {"message": "overloaded"}}), None, 1)
    api = FakeApi(script={1: err, 2: err})
    s, b = run(tmp_path, api, budget=live.Budget(max_requests=45))
    first = s["results"][0]
    assert first["requests_used"] >= 3 and s["requests"] == len(api.calls)             # a 2 sikertelen próbálkozás + a sikeres is kérés


def test_token_cap_prechecked_before_request(tmp_path):
    api = FakeApi(per_call_tokens=3000)
    s, b = run(tmp_path, api, budget=live.Budget(max_tokens=20_000))
    assert b.tokens <= 20_000 and "tokenkeret" in s["stopped"] and "nem fér" in s["stopped"]


def test_time_cap_stops(tmp_path):
    t = [0.0]
    class Clk:
        def __call__(self):
            t[0] += 300.0
            return t[0]
    api = FakeApi()
    s, b = run(tmp_path, api, budget=live.Budget(max_seconds=1200, clock=Clk()), clock=Clk())
    assert "futásidő" in s["stopped"] and len(api.calls) < 20


def test_daily_quota_stops_immediately_and_never_retries_or_switches(tmp_path):
    day = Raw(429, json.dumps({"error": {"message": "Quota exceeded per day", "details": [{"violations": [{"quotaId": "RequestsPerDay"}]}]}}), None, 1)
    api = FakeApi(script={4: day})
    s, b = run(tmp_path, api)
    assert len(api.calls) == 4 and "quota" in s["stopped"]                              # a kvótahibánál azonnal megáll
    assert [r["ran"] for r in s["results"]].count(False) >= 8


def test_auth_error_is_technical_stop(tmp_path):
    api = FakeApi(script={1: Raw(403, json.dumps({"error": {"message": "API key not valid"}}), None, 1)})
    s, b = run(tmp_path, api)
    assert len(api.calls) == 1 and s["stopped"].startswith("technical") and "HTTP 403" in s["stopped"]


def test_model_mismatch_stops_no_silent_switch(tmp_path):
    api = FakeApi(model_version="some-other-model-9")
    s, b = run(tmp_path, api)
    assert len(api.calls) == 1 and s["stopped"].startswith("integrity") and "más modellel" in s["stopped"]


def test_secret_in_request_body_is_never_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEYISH)
    bad = {**CASES[0], "id": "A_tools", "segments": [f"Please use the key {KEYISH} for this."] + CASES[0]["segments"][1:]}
    monkeypatch.setattr(live, "ordered_cases", lambda ids: [bad])
    api = FakeApi()
    s, b = run(tmp_path, api)
    assert api.calls == [] and s["stopped"].startswith("integrity") and "titkot" in s["stopped"]
    assert KEYISH not in json.dumps(s) and KEYISH not in (tmp_path / "out" / "raw_model_io.json").read_text()


def test_content_error_is_recorded_not_a_run_stop(tmp_path):
    blocked = Raw(200, json.dumps({"promptFeedback": {"blockReason": "SAFETY"}}), None, 1)
    api = FakeApi(script={1: blocked})
    s, b = run(tmp_path, api)
    assert s["stopped"] is None and len([r for r in s["results"] if r["ran"]]) == 14
    assert "kimaradt" in s["results"][0]["job_error"] or s["results"][0]["status"] in ("failed", "completed")


def test_frozen_inputs_changed_during_run_invalidate_it(tmp_path, monkeypatch):
    real = live._sha
    n = {"c": 0}
    def flaky(p):
        n["c"] += 1
        return real(p) if n["c"] <= 3 else "0" * 64                                    # a futás végi újraellenőrzésnél eltér
    monkeypatch.setattr(live, "_sha", flaky)
    s, b = run(tmp_path, FakeApi(), budget=live.Budget(max_requests=3))
    assert not s["valid_run"] and s["frozen_files_changed_during_run"]


def test_manifest_records_commit_model_prompt_version_and_hashes():
    m = live.manifest(MODEL, {"max_requests": 10}, FIRST, "RUN-ID-001")
    assert re.fullmatch(r"[0-9a-f]{40}", m["commit_sha"]) and m["model_id"] == MODEL and m["prompt_version"].startswith("sha256:")
    assert set(m["hashes"]) == {"cases.py", "evaluator(runner.py)", "extraction.py"} and m["cases"] == FIRST and m["run_id"] == "RUN-ID-001" and m["semantic_check_enabled"] is True


def test_raw_and_processed_are_separate_files_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEYISH)
    run(tmp_path, FakeApi(), budget=live.Budget(max_requests=4))
    raw = (tmp_path / "out" / "raw_model_io.json").read_text()
    proc = (tmp_path / "out" / "processed_results.json").read_text()
    assert KEYISH not in raw and KEYISH not in proc and "response_text" in raw and "response_text" not in proc


def test_live_main_refuses_without_attestations_key_or_model(monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert live.main_live(["--live"]) == 2
    monkeypatch.setenv("GEMINI_API_KEY", KEYISH)
    monkeypatch.setenv("VR_GEMINI_MODEL", MODEL)
    ok = ["--live", "--cases", "A_tools", "--run-id", "RUN-ID-001", "--max-requests", "10", "--max-tokens", "30000", "--max-seconds", "600"]
    assert live.main_live(ok) == 2
    assert "igazolások hiányoznak" in capsys.readouterr().out


# ---- esetszűrés: csak a megadott esetek, hibás lista nem indít semmit ----
def test_only_the_three_named_cases_start_and_semantic_check_stays_on(tmp_path):
    api = FakeApi(model_version=MODEL)
    s, b = run(tmp_path, api, cases=FIRST, budget=live.Budget(max_requests=10, max_tokens=30_000, max_seconds=600))
    assert [r["id"] for r in s["results"]] == FIRST and s["cases_not_run"] == [] and s["valid_run"]
    firsts = {c["segments"][0] for c in CASES if c["id"] in FIRST}
    seen = set()
    sem = ext = 0
    for body in api.calls:
        user = body["contents"][0]["parts"][0]["text"]
        if "Állítás:" in user and "Idézet:" in user:
            sem += 1
        else:
            ext += 1
            seen.add(user.split("<untrusted_transcript>")[1].strip().splitlines()[0].split("] ", 1)[1])
    assert seen == firsts and ext == 3                                            # kizárólag a három eset átirata ment ki
    assert sem == 4 and len(api.calls) == 7                                       # a szemantikai ellenőrzés bekapcsolva maradt: 3+1 tétel
    m = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert m["cases"] == FIRST and m["semantic_check_enabled"] is True and m["run_id"] == "TEST-RUN-001"


@pytest.mark.parametrize("bad", [None, "", "  ", "A_tools,,G_needle", "A_tools,", "A_tools,NINCS_ILYEN", "a_tools", "B_lossy", "A_tools,A_tools"])
def test_bad_case_lists_are_rejected_without_fallback(bad):
    with pytest.raises(live.CaseSelectionError):
        live.parse_case_list(bad)
    if bad is not None:
        with pytest.raises(live.CaseSelectionError):
            live.ordered_cases([x.strip() for x in bad.split(",")])


def test_bad_case_name_starts_nothing_in_execute_and_in_main(tmp_path, monkeypatch, capsys):
    api = FakeApi()
    with pytest.raises(live.CaseSelectionError):
        run(tmp_path, api, cases=["A_tools", "TYPO"])
    assert api.calls == [] and not (tmp_path / "out").exists()                    # semmi nem indult, kimeneti mappa sincs
    monkeypatch.setenv("GEMINI_API_KEY", KEYISH)
    monkeypatch.setenv("VR_GEMINI_MODEL", MODEL)
    import validation.hu_pilot.live.transport as T
    monkeypatch.setattr(T, "HttpTransport", lambda *a, **k: (_ for _ in ()).throw(AssertionError("valódi átvitel nem jöhet létre")))
    base = ["--live", "--run-id", "RUN-ID-001", "--max-requests", "10", "--max-tokens", "30000", "--max-seconds", "600",
            "--attest-free-tier", "--attest-no-billing", "--attest-owner-rule-change"]
    for cases in (["--cases", "A_tools,TYPO"], ["--cases", ""], [], ["--cases"], ["--cases", "A_tools,,G_needle"]):
        assert live.main_live(base + cases) == 2
    assert "Nem indul hívás" in capsys.readouterr().out


@pytest.mark.parametrize("drop", ["--max-requests", "--max-tokens", "--max-seconds", "--run-id"])
def test_main_requires_every_budget_and_run_id_no_defaults(drop, monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", KEYISH)
    monkeypatch.setenv("VR_GEMINI_MODEL", MODEL)
    args = ["--live", "--cases", "A_tools", "--run-id", "RUN-ID-001", "--max-requests", "10", "--max-tokens", "30000", "--max-seconds", "600",
            "--attest-free-tier", "--attest-no-billing", "--attest-owner-rule-change"]
    i = args.index(drop)
    assert live.main_live(args[:i] + args[i + 2:]) == 2


# ---- 11. kérés, keretkimerülés, részleges állapot ----
def test_the_11th_request_cannot_start(tmp_path):
    calls = []
    b = live.Budget(max_requests=10, max_tokens=10**9, max_seconds=10**6)
    ok = Raw(200, json.dumps({"candidates": [], "usageMetadata": {"totalTokenCount": 1}, "modelVersion": MODEL}), None, 1)
    bt = live.BudgetedTransport(lambda m, body: (calls.append(1), ok)[1], b, MODEL, [], lambda: "x")
    body = {"generationConfig": {"maxOutputTokens": 10}, "contents": []}
    for _ in range(10):
        bt(MODEL, body)
    with pytest.raises(live.RunStopped):
        bt(MODEL, body)
    assert len(calls) == 10 and b.requests == 10                                  # a 11. kérés nem ment ki


def test_pipeline_with_many_retries_never_exceeds_ten_requests(tmp_path):
    err = Raw(503, json.dumps({"error": {"message": "overloaded"}}), None, 1)
    api = FakeApi(model_version=MODEL, script={i: err for i in range(1, 40)})      # a szolgáltató végig hibázik: minden retry kérésnek számít
    s, b = run(tmp_path, api, cases=FIRST, budget=live.Budget(max_requests=10, max_tokens=30_000, max_seconds=600))
    assert len(api.calls) == 10 and s["requests"] == 10 and "kérés keret" in s["stopped"]


def test_budget_exhaustion_keeps_partial_result_and_labels_unchecked_items(tmp_path):
    api = FakeApi(model_version=MODEL)
    s, b = run(tmp_path, api, cases=FIRST, budget=live.Budget(max_requests=3, max_tokens=30_000, max_seconds=600))
    assert len(api.calls) == 3 and "kérés keret" in s["stopped"]
    a = next(r for r in s["results"] if r["id"] == "A_tools")
    assert a["ran"] and a["partial"] and a["status"] == "partially_completed"
    assert len(a["findings"]) == 2 and len(a["unchecked_not_results"]) == 1                          # 2 ellenőrzött tétel, 1 ellenőrizetlen
    assert a["unchecked_not_results"][0]["statement_hu"] not in [f["statement_hu"] for f in a["findings"]]     # az ellenőrizetlen nem „sikeres eredmény”
    assert a["coverage"]["not_processed"][0]["reason"] == "semantic_check_incomplete" and "run_budget" in a["coverage"]["limits_hit"] and not a["coverage"]["complete"]
    assert s["cases_not_run"] == ["G_needle", "D_irrelevant"] and s["cases_partial"] == ["A_tools"]
    proc = (tmp_path / "out" / "processed_results.json").read_text()
    assert "nem futott" in proc


def test_budget_exhausted_before_any_extraction_is_a_clear_not_run_state(tmp_path):
    api = FakeApi(model_version=MODEL)
    s, b = run(tmp_path, api, cases=FIRST, budget=live.Budget(max_requests=10, max_tokens=1_000, max_seconds=600))
    assert api.calls == [] and s["stopped"] and all(not r.get("findings") for r in s["results"]) and "tokenkeret" in s["stopped"]


def test_conservative_input_estimate_reserves_more_than_one_token_per_three_chars(tmp_path):
    b = live.Budget(max_requests=10, max_tokens=5_000, max_seconds=600)
    ok = Raw(200, "{}", None, 1)
    bt = live.BudgetedTransport(lambda m, body: ok, b, MODEL, [], lambda: "x")
    body = {"contents": [{"parts": [{"text": "x" * 3000}]}], "generationConfig": {"maxOutputTokens": 4000}}
    # 3000 karakter: //3 → ~1000 + 4000 = 5000 még beleférne; konzervatívan //2 → ~1500 + 4000 > 5000: megáll
    with pytest.raises(live.RunStopped):
        bt(MODEL, body)
