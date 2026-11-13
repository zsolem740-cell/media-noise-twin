"""A Gemini-feldolgozás az ÚJ 20 címes ellenőrzőmintán (ugyanazok a címek, mint a Groq v2/v3 ellenőrzésnél). HÁLÓZATI KÓD NINCS ITT.

A meglévő egy-címes Gemini-módot (gemini_request, gemini_smoke.run_smoke) változtatás nélkül használja: egy cím egy kérés, ugyanaz az alap-szabályszöveg, ugyanaz a négy jel,
0–2 pont, ugyanaz a JSON-séma. Az átvitelt kívülről kapja. A kimenet KÜLÖN mappába (results/gemini_check/) megy, a Groq-fájlokhoz nem nyúl, nem keveri velük.
Fájlok: gemini_results_check.csv, gemini_log_check.jsonl, gemini_summary_check.json (+ a futtató nyers fájljai ugyanebben a mappában)."""
import csv
import json
from pathlib import Path

from . import gemini_request as gr
from . import gemini_smoke as gs
from .isolation import check_read, check_write

SIGNALS = ("curiosity_gap", "exaggeration", "emotional_pressure", "formal_noise")
CSV_FIELDS = ["id", "status", "failure", "total", "scaled", "model"] + [f"{s}_{p}" for s in SIGNALS for p in ("score", "reason", "span")]
INTERNAL = ("raw_responses.jsonl", "scores.jsonl", "errors.jsonl", "smoke_report.json")


def load_inputs(cfg, results_dir):
    rows = gs.read_jsonl_file(Path(results_dir) / cfg["gemini"]["check"]["inputs_file"], results_dir)
    return [{"id": r["id"], "postText": r["postText"]} for r in rows]


def build_dryrun(inputs, cfg, leaks=None):
    return gs.build_dryrun(inputs, cfg, leaks)


def verify_dryrun(rows, inputs, cfg, leaks=None):
    return gs.verify_dryrun_rows(rows, inputs, cfg, None, leaks)


def _jl(path):
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()] if Path(path).exists() else []


def run_check(inputs, transport, cfg, results_dir, model, sleep=None, monotonic=None):
    """Futtatás kívülről kapott átvitellel. Létező kimenetet nem ír felül és nem folytat (nehogy összekeveredjen)."""
    c = cfg["gemini"]["check"]
    out_dir = Path(results_dir) / c["subdir"]
    check_write(out_dir / "x", results_dir)
    names = list(c["files"].values())[:3] + list(INTERNAL)
    for n in names:
        if (out_dir / n).exists():
            raise FileExistsError(f"{n} már létezik: a futás nem ír felül és nem folytat")
    kw = {}
    if sleep:
        kw["sleep"] = sleep
    if monotonic:
        kw["monotonic"] = monotonic
    report = gs.run_smoke(inputs, transport, cfg, out_dir, results_dir, model, **kw)
    scores = {s["id"]: s for s in _jl(out_dir / "scores.jsonl")}
    errs = _jl(out_dir / "errors.jsonl")
    raws = _jl(out_dir / "raw_responses.jsonl")
    last_err = {}
    for e in errs:
        last_err[e["id"]] = f"{e['kind']}: {e['detail']}"[:200]
    mv = sorted(report.get("model_versions_seen") or [])
    rows = []
    for x in inputs:
        s = scores.get(x["id"])
        if s:
            r = {"id": x["id"], "status": "ok", "failure": "", "total": s["total"], "scaled": s["scaled"], "model": ",".join(mv) or model}
            for k, v in s["signals"].items():
                r.update({f"{k}_score": v["score"], f"{k}_reason": v["reason"], f"{k}_span": v["span"]})
        else:
            r = {"id": x["id"], "status": "failed" if x["id"] in last_err else "not_run", "failure": last_err.get(x["id"], report.get("stop_reason") or "")}
        rows.append(r)
    p_csv, p_log, p_sum = (check_write(out_dir / c["files"][k], results_dir) for k in ("results_csv", "log", "summary"))
    with p_csv.open("x", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="raise")
        w.writeheader()
        w.writerows(rows)
    with p_log.open("x", encoding="utf-8") as f:
        errs_by = {}
        for e in errs:
            errs_by.setdefault((e["id"], e["attempt"]), e)
        for r in raws:
            e = errs_by.get((r["id"], r["attempt"]))
            f.write(json.dumps({"id": r["id"], "attempt": r["attempt"], "http_status": r.get("http_status"), "timeout": r.get("timeout", False), "latency_ms": r.get("latency_ms"),
                                "finishReason": r.get("finishReason"), "blockReason": r.get("promptFeedback_blockReason"), "usage": r.get("usageMetadata"),
                                "outcome": e["kind"] if e else ("ok" if r["id"] in scores else "unknown"), "detail": e["detail"] if e else ""}, ensure_ascii=False) + "\n")
    summary = {**{k: report.get(k) for k in ("model_requested", "model_versions_seen", "tier", "prompt_sha256", "schema_sha256", "thinking_config", "n_selected", "requests_sent",
                                              "retries", "n_valid", "n_failed", "n_blocked", "n_not_attempted", "stop_reason", "errors_by_kind", "tokens", "cost_usd", "latency_ms", "pass")},
               "mode": "egy cím egy kérésben (a meglévő Gemini-mód)", "keys_used": 1, "weighting": "nincs", "groq_files_touched": False}
    p_sum.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary
