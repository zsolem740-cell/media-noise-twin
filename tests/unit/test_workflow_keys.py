"""A szolgáltatói API-kulcsot használó munkafolyamat csak kézzel indítható lehet (workflow_dispatch). Így nincs ütemezett vagy automatikus valódi API-hívás (CLAUDE.md: éles futást csak a felhasználó indíthat),
és a napi Gemini/Groq-kvótát nem fogyasztja el semmi a háttérben. Csak fájlokat olvas."""
import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
KEYS = ("GEMINI_API_KEY", "GROQ_API_KEY")
AUTO_TRIGGERS = re.compile(r"^\s{2}(schedule|push|pull_request|pull_request_target|workflow_run|release|issues|issue_comment):", re.M)


def key_workflows():
    return [p for p in sorted(WORKFLOWS.glob("*.y*ml")) if any(k in p.read_text(encoding="utf-8") for k in KEYS)]


def test_every_workflow_with_a_provider_key_is_manual_only():
    bad = []
    for p in key_workflows():
        t = p.read_text(encoding="utf-8")
        on = t.split("\non:", 1)[1].split("\npermissions:", 1)[0] if "\non:" in t else ""
        if "workflow_dispatch" not in on or AUTO_TRIGGERS.search(on):
            bad.append(p.name)
    assert bad == [], f"ütemezett vagy automatikus munkafolyamat használ API-kulcsot: {bad}"


def test_the_detector_sees_the_pilot_run_workflow_and_would_catch_a_scheduled_one():
    names = [p.name for p in key_workflows()]
    assert "pilot-model-run.yml" in names and "gemini-labels.yml" not in names
    sample = "name: x\non:\n  schedule:\n    - cron: '17 * * * *'\n  workflow_dispatch:\npermissions:\n"
    assert AUTO_TRIGGERS.search(sample.split("\non:", 1)[1])
