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


def run(tmp_path, api, **kw):
    b = kw.pop("budget", None) or live.Budget()
    return live.execute(MODEL, api, b, tmp_path / "out", min_interval_s=0.0, sleep=lambda _x: None, **kw), b


def test_starter_cases_first_and_all_counted_in_one_budget(tmp_path):
    api = FakeApi()
    s, b = run(tmp_path, api)
    ids = [r["id"] for r in s["results"]]
    assert ids[:3] == ["A_tools", "G_needle", "D_irrelevant"] and "B_lossy" not in ids and len(ids) == 14
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
    monkeypatch.setattr(live, "ordered_cases", lambda: [bad])
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
    m = live.manifest(MODEL, {"max_requests": 45})
    assert re.fullmatch(r"[0-9a-f]{40}", m["commit_sha"]) and m["model_id"] == MODEL and m["prompt_version"].startswith("sha256:")
    assert set(m["hashes"]) == {"cases.py", "evaluator(runner.py)", "extraction.py"} and m["starter_cases"] == ["A_tools", "G_needle", "D_irrelevant"]


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
    assert live.main_live(["--live", "--max-requests", "45"]) == 2
    assert "igazolások hiányoznak" in capsys.readouterr().out
