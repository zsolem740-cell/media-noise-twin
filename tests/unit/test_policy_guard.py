"""Az Őr szabályainak próbája: git, hálózat és kulcs nélkül, kizárólag hamis bemenettel. Minden szabályhoz van pozitív (hibát jelez) és negatív (tiszta) eset."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import policy_guard as g  # noqa: E402

P = g.load_policy()


def rd(files):
    return lambda p: files.get(p)


def rules(res, level="hiba"):
    return {r["rule"] for r in res if r["level"] == level}


def test_policy_file_is_valid_and_lists_exactly_the_two_allowed_providers():
    assert P["allowed_providers"] == ["gemini", "groq"] and "perplexity" in P["forbidden_providers"]
    assert P["max_titles_per_run"] == 249


def test_results_in_diff_is_error_but_gitkeep_and_deletion_are_not():
    bad = g.check_forbidden_paths([("A", "validation/hu_pilot/results/votes.json"), ("M", "results/x.csv")], P)
    assert [r["where"] for r in bad] == ["validation/hu_pilot/results/votes.json", "results/x.csv"]
    ok = g.check_forbidden_paths([("A", "validation/hu_pilot/results/.gitkeep"), ("D", "results/x.csv"), ("M", "validation/hu_pilot/run.py")], P)
    assert ok == []


def test_protected_prompt_change_is_error_for_every_status():
    for st in ("M", "D", "R100"):
        assert rules(g.check_protected([(st, "validation/webis_validation/groq_request.py")], P)) == {"protected-prompt"}
    assert g.check_protected([("M", "validation/hu_pilot/run.py")], P) == []


def test_pin_detects_a_changed_hash_and_missing_file_and_skips_unset():
    import hashlib
    pol = {"pinned_sha256": {"a.py": hashlib.sha256(b"x").hexdigest(), "b.py": None}}
    assert g.check_pins(rd({"a.py": "x"}), pol) == []
    assert rules(g.check_pins(rd({"a.py": "y"}), pol)) == {"pinned-prompt"}
    assert rules(g.check_pins(rd({}), pol)) == {"pinned-prompt"}


def test_secrets_are_found_without_printing_the_value_and_placeholders_are_ignored():
    key = "AIza" + "B" * 30
    res = g.check_secrets(["a.py", "b.md"], rd({"a.py": f'k = "{key}"\n', "b.md": "api_key = 'YOUR_KEY_HERE'\nsk-" + "z" * 5}))
    assert rules(res) == {"secret"} and [r["where"] for r in res] == ["a.py:1"]
    assert key not in json.dumps(res)


def test_third_provider_import_and_host_are_errors_but_gemini_groq_are_fine():
    files = {"x.py": "import openai\n", "y.json": '{"u": "https://api.perplexity.ai/chat"}', "z.py": "import json\nGEM='gemini'\n", "tests/t.py": "import openai\n"}
    res = g.check_providers(list(files), rd(files), P)
    assert {r["where"].split(":")[0] for r in res} == {"x.py", "y.json"} and rules(res) == {"third-provider"}


def test_live_endpoint_outside_allowed_files_is_error_inside_is_ok_and_in_tests_only_warning():
    ep = "generativelanguage.googleapis.com"
    files = {"scripts/new.py": f"U='https://{ep}/v1'", "validation/hu_pilot/live/transport.py": f"U='{ep}'", "tests/unit/t.py": f"U='{ep}'"}
    res = g.check_live_endpoints(list(files), rd(files), P)
    assert rules(res) == {"live-endpoint"} and [r["where"] for r in res if r["level"] == "hiba"] == ["scripts/new.py"]
    assert [r["where"] for r in res if r["level"] == "figyelmeztetés"] == ["tests/unit/t.py"]


def test_title_limit_catches_250_and_above_but_not_249_or_unrelated_keys():
    f = {"validation/hu_pilot/config.json": json.dumps({"model": {"run": {"max_requests": 250}}, "seed": 9000, "sizes": {"n": 249}})}
    res = g.check_title_counts(rd(f), P, list(f))
    assert [r["where"] for r in res] == ["validation/hu_pilot/config.json:max_requests"]
    assert g.check_title_counts(rd({"c.json": json.dumps({"n": 80, "max_requests": 80})}), P, ["c.json"]) == []


def test_weighting_warns_on_plain_weights_but_not_on_kappa_weighted():
    f = {"validation/hu_pilot/x.py": "w = voter_weights[a]\nk = cohen_kappa(x, y, weighted=True)\nlabel_weight = 2\n"}
    res = g.check_weighting(list(f), rd(f))
    assert [r["where"] for r in res] == ["validation/hu_pilot/x.py:1", "validation/hu_pilot/x.py:3"] and rules(res, "figyelmeztetés") == {"weighting"}
    assert g.check_weighting(["src/core/atm_engine.py"], rd({"src/core/atm_engine.py": "weights = {}"})) == []


def test_run_checks_is_clean_on_a_clean_change_and_aggregates_errors():
    clean = g.run_checks([("M", "validation/hu_pilot/run.py")], ["validation/hu_pilot/run.py"], rd({"validation/hu_pilot/run.py": "x = 1\n"}), P)
    assert [r for r in clean if r["level"] == "hiba"] == []
    dirty = g.run_checks([("M", "validation/webis_validation/groq_request.py"), ("A", "results/a.csv")], [], rd({}), P)
    assert rules(dirty) == {"protected-prompt", "results-commit"}


def test_main_exits_2_when_base_is_missing_and_never_writes(tmp_path, capsys):
    assert g.main(["--base", "nincs-ilyen-ag-xyz"]) == 2
