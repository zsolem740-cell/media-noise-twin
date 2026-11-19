"""Kereskedelmi modell: a kapu RÖGZÍTETT protokoll-paramétereinek szigorú betöltése, ellenőrzése és hash-elése.

Csak helyi fájlt olvas; hálózatot, szolgáltatót, kulcsot és környezeti beállítást nem használ. A konfigurációt nem módosítja és nem egészíti ki alapértékekkel:
ismeretlen vagy hiányzó kulcs, rossz típus és ellentmondó állapot hiba. A rögzített tartalom hash-ét a teszt és a dokumentáció is rögzíti, így a csendes módosítás elbukik.
A számszerű küszöbök, a költségmodell és a viszonyítási alapok MÉG NEM rögzítettek (`pending`): amíg bármelyik nyitott, a mérés nem indulhat (`measurement_ready`).
Szabályok: docs/KUTATASI_KERDES_ES_KAPU.md és docs/SZABALYOK.md.
"""
import datetime
import hashlib
import json
import re
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "gate_config.json"
SCHEMA = 1
STATUSES = ("protocol_frozen", "frozen")
TOP_KEYS = ("_note", "schema", "status", "frozen_on", "approved_by", "split_percent", "embargo", "metrics", "bootstrap", "min_trades", "multiple_testing", "states", "pending",
            "changes", "rules")
SPLIT_KEYS = ("train", "validation", "test")
METRICS = ("net_result_after_costs", "max_drawdown", "trade_count")
GATE_STATES = ("atment", "nem_ment_at", "eldonthetetlen", "nem_szamolhato")
PENDING_KEYS = ("cost_model", "benchmarks", "thresholds")
RULE_KEYS = ("test_opens_once", "silent_change_forbidden", "no_lookahead")
CHANGE_KEYS = ("date", "what", "approved_by", "before_first_measurement")
REASONS = ("missing", "unknown_field", "invalid_type", "invalid_value", "inconsistent", "invalid_json")
_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})", re.ASCII)


def _int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _date_ok(value):
    m = isinstance(value, str) and _DATE.fullmatch(value)
    if not m:
        return False
    try:
        datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return False
    return True


def validate(cfg):
    """[{"field", "reason"}]: üres lista = a konfiguráció érvényes. A `field` pontozott útvonal. Alapértéket nem pótol, típust nem alakít."""
    probs = []

    def add(field, reason):
        probs.append({"field": field, "reason": reason})

    def exact(obj, keys, path):
        if not isinstance(obj, dict):
            add(path, "invalid_type")
            return False
        for k in keys:
            if k not in obj:
                add(f"{path}.{k}", "missing")
        for k in sorted(k for k in obj if k not in keys):
            add(f"{path}.{k}", "unknown_field")
        return all(k in obj for k in keys)

    if not isinstance(cfg, dict):
        return [{"field": None, "reason": "invalid_type"}]
    for k in TOP_KEYS:
        if k not in cfg and k != "_note":
            add(k, "missing")
    for k in sorted(k for k in cfg if k not in TOP_KEYS):
        add(k, "unknown_field")
    if "schema" in cfg and (type(cfg["schema"]) is not int or cfg["schema"] != SCHEMA):
        add("schema", "invalid_value")
    if "status" in cfg and cfg["status"] not in STATUSES:
        add("status", "invalid_value")
    if "frozen_on" in cfg and not _date_ok(cfg["frozen_on"]):
        add("frozen_on", "invalid_value")
    if "approved_by" in cfg and (not isinstance(cfg["approved_by"], str) or not cfg["approved_by"].strip()):
        add("approved_by", "invalid_value")
    if "split_percent" in cfg and exact(cfg["split_percent"], SPLIT_KEYS, "split_percent"):
        sp = cfg["split_percent"]
        for k in SPLIT_KEYS:
            if not _int(sp[k]):
                add(f"split_percent.{k}", "invalid_type")
            elif sp[k] <= 0:
                add(f"split_percent.{k}", "invalid_value")
        if all(_int(sp[k]) for k in SPLIT_KEYS) and sum(sp[k] for k in SPLIT_KEYS) != 100:
            add("split_percent", "inconsistent")
    if "embargo" in cfg and exact(cfg["embargo"], ("rule",), "embargo") and cfg["embargo"]["rule"] != "at_least_max_lookback_bars":
        add("embargo.rule", "invalid_value")
    if "metrics" in cfg and cfg["metrics"] != list(METRICS):
        add("metrics", "invalid_value" if isinstance(cfg["metrics"], list) else "invalid_type")
    if "bootstrap" in cfg and exact(cfg["bootstrap"], ("resamples", "base_confidence_percent"), "bootstrap"):
        for k, lo, hi in (("resamples", 1, 10 ** 7), ("base_confidence_percent", 1, 99)):
            v = cfg["bootstrap"][k]
            if not _int(v):
                add(f"bootstrap.{k}", "invalid_type")
            elif not lo <= v <= hi:
                add(f"bootstrap.{k}", "invalid_value")
    if "min_trades" in cfg:
        if not _int(cfg["min_trades"]):
            add("min_trades", "invalid_type")
        elif cfg["min_trades"] < 1:
            add("min_trades", "invalid_value")
    if "multiple_testing" in cfg and exact(cfg["multiple_testing"], ("method", "trial_log_required", "trials_may_not_decrease"), "multiple_testing"):
        mt = cfg["multiple_testing"]
        if mt["method"] != "bonferroni_by_trials":
            add("multiple_testing.method", "invalid_value")
        for k in ("trial_log_required", "trials_may_not_decrease"):
            if mt[k] is not True:
                add(f"multiple_testing.{k}", "invalid_value" if isinstance(mt[k], bool) else "invalid_type")
    if "states" in cfg and cfg["states"] != list(GATE_STATES):
        add("states", "invalid_value" if isinstance(cfg["states"], list) else "invalid_type")
    pending_open = None
    if "pending" in cfg and exact(cfg["pending"], PENDING_KEYS, "pending"):
        pending_open = []
        for k in PENDING_KEYS:
            v = cfg["pending"][k]
            if v is None:
                pending_open.append(k)
            elif not isinstance(v, dict):
                add(f"pending.{k}", "invalid_type")
            elif not v:
                add(f"pending.{k}", "invalid_value")
    if "changes" in cfg:
        if not isinstance(cfg["changes"], list):
            add("changes", "invalid_type")
        else:
            for i, ch in enumerate(cfg["changes"]):
                if exact(ch, CHANGE_KEYS, f"changes[{i}]"):
                    if not _date_ok(ch["date"]) or not isinstance(ch["what"], str) or not ch["what"].strip() or not isinstance(ch["approved_by"], str) or not ch["approved_by"].strip():
                        add(f"changes[{i}]", "invalid_value")
                    if not isinstance(ch["before_first_measurement"], bool):
                        add(f"changes[{i}].before_first_measurement", "invalid_type")
    if "rules" in cfg and exact(cfg["rules"], RULE_KEYS, "rules"):
        for k in RULE_KEYS:
            if cfg["rules"][k] is not True:
                add(f"rules.{k}", "invalid_value" if isinstance(cfg["rules"][k], bool) else "invalid_type")
    if pending_open is not None and cfg.get("status") in STATUSES:
        if cfg["status"] == "frozen" and pending_open:
            add("status", "inconsistent")
        if cfg["status"] == "protocol_frozen" and not pending_open:
            add("status", "inconsistent")
    return probs


def _no_duplicate_keys(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("ismétlődő kulcs: " + k)
        out[k] = v
    return out


def _reject_constant(name):
    raise ValueError("nem JSON-konstans: " + name)


def load_config(path=CONFIG_PATH):
    """(konfiguráció vagy None, problémák). Szigorú JSON (ismétlődő kulcs, NaN/Infinity, nem UTF-8 bájt és BOM hiba), utána validate. Érvénytelen konfigurációból nem lesz érték."""
    try:
        cfg = json.loads(Path(path).read_bytes().decode("utf-8"), object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError):
        return None, [{"field": None, "reason": "invalid_json"}]
    probs = validate(cfg)
    return (None if probs else cfg), probs


def config_hash(cfg):
    """A tartalom SHA-256 értéke kanonikus alakon (rendezett kulcsok, szóköz nélkül): a fájl formázása nem változtatja, a tartalom bármilyen módosítása igen."""
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def measurement_ready(cfg):
    """(kész, nyitott tételek). A mérés csak `frozen` állapotú, érvényes konfigurációval indulhat, amelyben a költségmodell, a viszonyítási alapok és a küszöbök is rögzítettek."""
    if validate(cfg):
        return False, ["invalid_config"]
    open_items = [k for k in PENDING_KEYS if cfg["pending"][k] is None]
    return (cfg["status"] == "frozen" and not open_items), open_items
