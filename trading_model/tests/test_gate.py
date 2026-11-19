"""A kapu rögzített protokoll-paramétereinek próbái. Csak a repóba tett konfigurációt és az ideiglenes mappába írt mintákat használja; hálózat nincs.
A hálózati zárat a közös autouse fixture adja (lásd test_network_guard.py)."""
import ast
import copy
import json
import re
from pathlib import Path

import pytest

from trading_model import gate as G

HERE = Path(__file__).resolve().parent
DOC = HERE.parent / "docs" / "KUTATASI_KERDES_ES_KAPU.md"
PINNED_HASH = "f7fd5ecd22b8430a086e7ce6698070974e2eaed6c48a672253c414c526de4e29"
DEL = object()
BASE, _PROBLEMS = G.load_config()


def mutated(path, value):
    cfg = copy.deepcopy(BASE)
    node = cfg
    for p in path[:-1]:
        node = node[p]
    if value is DEL:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return cfg


def pairs(cfg):
    return [(p["field"], p["reason"]) for p in G.validate(cfg)]


# ---------------------------------------------------------------- a rögzített tartalom (a felhasználó döntései, kézzel felvéve)

def test_the_repo_config_is_valid_and_loads():
    assert _PROBLEMS == [] and BASE is not None
    cfg, problems = G.load_config(G.CONFIG_PATH)
    assert problems == [] and cfg == BASE


def test_the_frozen_values_are_exactly_the_four_approved_decisions():
    assert BASE["status"] == "protocol_frozen" and BASE["frozen_on"] == "2026-11-19"
    assert BASE["split_percent"] == {"train": 60, "validation": 20, "test": 20}                               # 1. döntés: 60 / 20 / 20
    assert BASE["embargo"] == {"rule": "at_least_max_lookback_bars"}
    assert BASE["metrics"] == ["net_result_after_costs", "max_drawdown", "trade_count"]                       # 2. döntés: nettó eredmény + max. visszaesés + ügyletszám
    assert BASE["bootstrap"] == {"resamples": 2000, "base_confidence_percent": 95} and BASE["min_trades"] == 30      # bootstrap 95%, B=2000, min. 30 ügylet
    assert BASE["multiple_testing"] == {"method": "bonferroni_by_trials", "trial_log_required": True, "trials_may_not_decrease": True}      # 3. döntés
    assert BASE["states"] == ["atment", "nem_ment_at", "eldonthetetlen", "nem_szamolhato"]
    assert BASE["pending"] == {"cost_model": None, "benchmarks": None, "thresholds": None}                    # 4. döntés: költség, viszonyítás, küszöb később
    assert BASE["changes"] == [] and BASE["rules"] == {"test_opens_once": True, "silent_change_forbidden": True, "no_lookahead": True}


def test_the_content_hash_is_pinned_so_a_silent_change_fails_here():
    """Ha ez elbukik, a rögzített konfiguráció tartalma megváltozott. Csak a felhasználó kifejezett jóváhagyásával, a `changes` bejegyzésével, a dokumentáció és ez a hash frissítésével lehet rendben."""
    assert G.config_hash(BASE) == PINNED_HASH


def test_the_documentation_states_the_same_hash():
    assert PINNED_HASH in DOC.read_text(encoding="utf-8")


def test_the_hash_ignores_formatting_but_not_content():
    reformatted = json.loads(json.dumps(BASE, indent=7, ensure_ascii=True))
    assert G.config_hash(reformatted) == G.config_hash(BASE)
    reordered = dict(reversed(list(BASE.items())))
    assert G.config_hash(reordered) == G.config_hash(BASE)
    for path, value in [(("min_trades",), 31), (("split_percent", "train"), 59), (("bootstrap", "resamples"), 2001), (("status",), "frozen"), (("changes",), [{"x": 1}]),
                        (("pending", "cost_model"), {"bps": 1}), (("rules", "no_lookahead"), False), (("frozen_on",), "2026-11-20"), (("_note",), "más")]:
        assert G.config_hash(mutated(path, value)) != G.config_hash(BASE), path


def test_the_file_is_small_and_contains_no_secrets_or_personal_data():
    text = G.CONFIG_PATH.read_text(encoding="utf-8")
    assert len(text) < 3000 and not re.search(r"(?i)api[_-]?key|secret|token|password|bearer|gsk_|AIza|@|https?://", text)


# ---------------------------------------------------------------- a mérés zára

def test_the_measurement_gate_is_closed_while_anything_is_pending():
    assert G.measurement_ready(BASE) == (False, ["cost_model", "benchmarks", "thresholds"])


@pytest.mark.parametrize("filled", [("cost_model",), ("benchmarks",), ("thresholds",), ("cost_model", "benchmarks")])
def test_a_partly_filled_pending_list_still_keeps_the_gate_closed(filled):
    cfg = copy.deepcopy(BASE)
    for k in filled:
        cfg["pending"][k] = {"rögzítve": True}
    ready, open_items = G.measurement_ready(cfg)
    assert ready is False and open_items == [k for k in G.PENDING_KEYS if k not in filled]


def test_the_gate_opens_only_when_everything_is_filled_and_the_status_is_frozen():
    cfg = copy.deepcopy(BASE)
    cfg["pending"] = {k: {"rögzítve": True} for k in G.PENDING_KEYS}
    cfg["status"] = "frozen"
    assert G.validate(cfg) == [] and G.measurement_ready(cfg) == (True, [])


def test_a_status_that_contradicts_the_pending_list_is_an_error_not_a_way_to_open_the_gate():
    frozen_but_open = copy.deepcopy(BASE)
    frozen_but_open["status"] = "frozen"
    assert ("status", "inconsistent") in pairs(frozen_but_open) and G.measurement_ready(frozen_but_open) == (False, ["invalid_config"])
    filled_but_protocol = copy.deepcopy(BASE)
    filled_but_protocol["pending"] = {k: {"rögzítve": True} for k in G.PENDING_KEYS}
    assert ("status", "inconsistent") in pairs(filled_but_protocol) and G.measurement_ready(filled_but_protocol)[0] is False


def test_an_invalid_config_never_reports_ready():
    for bad in ([], None, "x", 5, {}, mutated(("min_trades",), "30")):
        assert G.measurement_ready(bad) == (False, ["invalid_config"])


# ---------------------------------------------------------------- szigorú ellenőrzés (nincs alapérték, nincs típusátalakítás)

CASES = [
    (("schema",), "1", ("schema", "invalid_value")), (("schema",), 1.0, ("schema", "invalid_value")), (("schema",), True, ("schema", "invalid_value")),
    (("schema",), 2, ("schema", "invalid_value")), (("schema",), DEL, ("schema", "missing")),
    (("status",), "draft", ("status", "invalid_value")), (("status",), None, ("status", "invalid_value")), (("status",), 5, ("status", "invalid_value")), (("status",), DEL, ("status", "missing")),
    (("frozen_on",), "2026-13-01", ("frozen_on", "invalid_value")), (("frozen_on",), "20261119", ("frozen_on", "invalid_value")),
    (("frozen_on",), "2026-11-19T00:00:00Z", ("frozen_on", "invalid_value")), (("frozen_on",), None, ("frozen_on", "invalid_value")),
    (("frozen_on",), 5, ("frozen_on", "invalid_value")), (("frozen_on",), DEL, ("frozen_on", "missing")),
    (("approved_by",), "", ("approved_by", "invalid_value")), (("approved_by",), "   ", ("approved_by", "invalid_value")), (("approved_by",), 5, ("approved_by", "invalid_value")),
    (("approved_by",), None, ("approved_by", "invalid_value")), (("approved_by",), DEL, ("approved_by", "missing")),
    (("split_percent",), DEL, ("split_percent", "missing")), (("split_percent",), "x", ("split_percent", "invalid_type")), (("split_percent",), {}, ("split_percent.train", "missing")),
    (("split_percent", "extra"), 1, ("split_percent.extra", "unknown_field")), (("split_percent", "test"), DEL, ("split_percent.test", "missing")),
    (("split_percent", "train"), "60", ("split_percent.train", "invalid_type")), (("split_percent", "train"), True, ("split_percent.train", "invalid_type")),
    (("split_percent", "train"), 60.0, ("split_percent.train", "invalid_type")), (("split_percent", "train"), 0, ("split_percent.train", "invalid_value")),
    (("split_percent", "train"), -1, ("split_percent.train", "invalid_value")), (("split_percent", "train"), 50, ("split_percent", "inconsistent")),
    (("split_percent", "train"), 61, ("split_percent", "inconsistent")),
    (("embargo",), DEL, ("embargo", "missing")), (("embargo",), "x", ("embargo", "invalid_type")), (("embargo", "rule"), "none", ("embargo.rule", "invalid_value")),
    (("embargo", "rule"), DEL, ("embargo.rule", "missing")), (("embargo", "extra"), 1, ("embargo.extra", "unknown_field")),
    (("metrics",), ["max_drawdown", "net_result_after_costs", "trade_count"], ("metrics", "invalid_value")), (("metrics",), ["net_result_after_costs", "max_drawdown"], ("metrics", "invalid_value")),
    (("metrics",), ["net_result_after_costs", "max_drawdown", "trade_count", "sharpe"], ("metrics", "invalid_value")), (("metrics",), "x", ("metrics", "invalid_type")),
    (("metrics",), DEL, ("metrics", "missing")),
    (("bootstrap", "resamples"), 0, ("bootstrap.resamples", "invalid_value")), (("bootstrap", "resamples"), "2000", ("bootstrap.resamples", "invalid_type")),
    (("bootstrap", "resamples"), True, ("bootstrap.resamples", "invalid_type")), (("bootstrap", "resamples"), 2000.0, ("bootstrap.resamples", "invalid_type")),
    (("bootstrap", "base_confidence_percent"), 0, ("bootstrap.base_confidence_percent", "invalid_value")),
    (("bootstrap", "base_confidence_percent"), 100, ("bootstrap.base_confidence_percent", "invalid_value")),
    (("bootstrap", "base_confidence_percent"), "95", ("bootstrap.base_confidence_percent", "invalid_type")),
    (("bootstrap", "base_confidence_percent"), DEL, ("bootstrap.base_confidence_percent", "missing")),
    (("min_trades",), 0, ("min_trades", "invalid_value")), (("min_trades",), -1, ("min_trades", "invalid_value")), (("min_trades",), "30", ("min_trades", "invalid_type")),
    (("min_trades",), True, ("min_trades", "invalid_type")), (("min_trades",), 30.5, ("min_trades", "invalid_type")), (("min_trades",), None, ("min_trades", "invalid_type")),
    (("min_trades",), DEL, ("min_trades", "missing")),
    (("multiple_testing", "method"), "none", ("multiple_testing.method", "invalid_value")), (("multiple_testing", "trial_log_required"), False, ("multiple_testing.trial_log_required", "invalid_value")),
    (("multiple_testing", "trial_log_required"), "yes", ("multiple_testing.trial_log_required", "invalid_type")),
    (("multiple_testing", "trials_may_not_decrease"), DEL, ("multiple_testing.trials_may_not_decrease", "missing")),
    (("states",), ["nem_ment_at", "atment", "eldonthetetlen", "nem_szamolhato"], ("states", "invalid_value")), (("states",), ["atment"], ("states", "invalid_value")),
    (("states",), "x", ("states", "invalid_type")), (("states",), DEL, ("states", "missing")),
    (("pending",), DEL, ("pending", "missing")), (("pending", "extra"), None, ("pending.extra", "unknown_field")), (("pending", "benchmarks"), DEL, ("pending.benchmarks", "missing")),
    (("pending", "cost_model"), [], ("pending.cost_model", "invalid_type")), (("pending", "cost_model"), {}, ("pending.cost_model", "invalid_value")),
    (("pending", "cost_model"), "x", ("pending.cost_model", "invalid_type")),
    (("changes",), "x", ("changes", "invalid_type")), (("changes",), [5], ("changes[0]", "invalid_type")), (("changes",), [{}], ("changes[0].date", "missing")),
    (("changes",), [{"date": "2026-13-40", "what": "x", "approved_by": "y", "before_first_measurement": True}], ("changes[0]", "invalid_value")),
    (("changes",), [{"date": "2026-11-20", "what": " ", "approved_by": "y", "before_first_measurement": True}], ("changes[0]", "invalid_value")),
    (("changes",), [{"date": "2026-11-20", "what": "x", "approved_by": "y", "before_first_measurement": "yes"}], ("changes[0].before_first_measurement", "invalid_type")),
    (("changes",), DEL, ("changes", "missing")),
    (("rules", "test_opens_once"), False, ("rules.test_opens_once", "invalid_value")), (("rules", "silent_change_forbidden"), "yes", ("rules.silent_change_forbidden", "invalid_type")),
    (("rules", "no_lookahead"), DEL, ("rules.no_lookahead", "missing")), (("rules", "extra"), True, ("rules.extra", "unknown_field")),
    (("zebra",), 1, ("zebra", "unknown_field")),
]


@pytest.mark.parametrize("path,value,expected", CASES, ids=[f"{'.'.join(p)}={'DEL' if v is DEL else v!r}" for p, v, _e in CASES])
def test_every_invalid_variant_is_reported_with_a_fixed_reason(path, value, expected):
    assert expected in pairs(mutated(path, value))


def test_every_variant_blocks_loading_from_a_file(tmp_path):
    for i, (path, value, expected) in enumerate(CASES):
        p = tmp_path / f"c{i}.json"
        p.write_text(json.dumps(mutated(path, value), ensure_ascii=False), encoding="utf-8")
        cfg, problems = G.load_config(p)
        assert cfg is None and expected in [(x["field"], x["reason"]) for x in problems], (path, value)


def test_the_optional_note_may_be_removed_and_nothing_else_is_optional():
    assert pairs(mutated(("_note",), DEL)) == []
    for key in G.TOP_KEYS:
        if key != "_note":
            assert (key, "missing") in pairs(mutated((key,), DEL)), key


def test_a_non_object_config_is_an_invalid_type():
    for bad in ([], None, "x", 5, 1.5, True):
        assert G.validate(bad) == [{"field": None, "reason": "invalid_type"}]


@pytest.mark.parametrize("raw", [b"", b"   ", b"{nem json", b'{"schema": 1,', b"\xff\xfe\x00{", b"\x80\x81", b"\xef\xbb\xbf" + json.dumps(BASE).encode(),
                                 b'{"schema": 1, "schema": 1}', b'{"min_trades": NaN}', b'{"min_trades": Infinity}'])
def test_a_corrupt_config_file_is_an_invalid_json_and_gives_no_value(tmp_path, raw):
    p = tmp_path / "c.json"
    p.write_bytes(raw)
    assert G.load_config(p) == (None, [{"field": None, "reason": "invalid_json"}])


def test_loading_never_modifies_the_file_and_returns_independent_copies(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(BASE), encoding="utf-8")
    before = p.read_bytes()
    a, _ = G.load_config(p)
    b, _ = G.load_config(p)
    a["min_trades"] = 1
    assert p.read_bytes() == before and b["min_trades"] == 30


def test_missing_values_are_never_filled_with_defaults(tmp_path):
    cfg = {k: v for k, v in BASE.items() if k != "min_trades"}
    p = tmp_path / "c.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    loaded, problems = G.load_config(p)
    assert loaded is None and [(x["field"], x["reason"]) for x in problems] == [("min_trades", "missing")]


# ---------------------------------------------------------------- dokumentáció és modul-szerződés

def test_the_documentation_lists_every_fixed_parameter_name_and_value():
    text = DOC.read_text(encoding="utf-8")
    for token in (G.TOP_KEYS[5:12] + G.METRICS + G.GATE_STATES + G.PENDING_KEYS + G.STATUSES):
        assert f"`{token}`" in text, token
    for needle in ("`protocol_frozen`", "tanító 60 / validációs 20 / zárt teszt 20", "2000", "95%", "`min_trades`", "30", "`bonferroni_by_trials`", "`at_least_max_lookback_bars`", "nincs rögzítve"):
        assert needle in text, needle


def test_every_validation_reason_is_asserted_by_at_least_one_test_in_this_file():
    src = Path(__file__).read_text(encoding="utf-8")
    missing = [r for r in G.REASONS if f'"{r}"' not in src]
    assert not missing, missing


def test_the_module_imports_only_the_allowed_standard_library_and_never_calls_str():
    src = (HERE.parent / "gate.py").read_text(encoding="utf-8")
    names, str_calls = set(), []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            names |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            names.add(("." * n.level) + (n.module or ""))
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "str":
            str_calls.append(n.lineno)
    assert names == {"datetime", "hashlib", "json", "re", "pathlib"}
    assert "environ" not in src and "getenv" not in src and not str_calls
