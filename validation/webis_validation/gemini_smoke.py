"""A 20 címes Gemini smoke test: kiválasztás, modellválasztás, száraz próba és futtató. HÁLÓZATI KÓD NINCS ITT.

A futtató (run_smoke) a kérés elküldését egy KÍVÜLRŐL kapott átviteli függvényre bízza; a modulban valódi átvitel nincs, ezért a
smoke test jóváhagyás nélkül nem tud elindulni. A 250 elemű és a 3000 címes futtatáshoz itt semmi nincs: a darabszám fix 20."""
import json
import re
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import random

from . import evaluate as ev
from . import gemini_request as gr
from . import sample as samp
from .isolation import check_read, check_write, has_hungarian_chars


class NeedUserDecision(Exception):
    """A folytatáshoz a felhasználó döntése kell (például nincs engedélyezett modell). A futás ilyenkor megáll."""


class TransportTimeout(Exception):
    pass


@dataclass
class Raw:
    status: int
    text: str
    latency_ms: int = 0


# ---------------------------------------------------------------- modellválasztás

NON_TEXT_MARKERS = ("tts", "image", "audio", "live", "embedding", "native", "robotics", "computer")


def choose_model(payload, cfg):
    """A models.list válaszából a megengedett jelölt (Flash-Lite). Ha csak a korlátozott (3.6 / 3.8 Flash) érhető el, vagy semmi, NeedUserDecision."""
    g = cfg["gemini"]
    usable = {}
    for m in (payload or {}).get("models", []):
        name = str(m.get("name", "")).removeprefix("models/")
        if "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue
        if any(x in name for x in NON_TEXT_MARKERS):
            continue
        usable[name] = m
    for cand in g["model_candidates"]:
        hits = sorted((n for n in usable if n == cand or n.startswith(cand + "-")), key=lambda n: (n != cand, len(n), n))
        if hits:
            return hits[0]
    restricted = sorted(n for n in usable if any(re.match(p, n) for p in g["restricted_model_patterns"]))
    if restricted:
        raise NeedUserDecision("A megengedett Flash-Lite modell nem érhető el, csak: " + ", ".join(restricted)
                               + ". Ingyenes szinten ezek napi kerete kb. 20 kérés, ezért a 20 hívás nem indul el. Állj meg és kérdezz.")
    raise NeedUserDecision("A modelllistában nincs generateContent-et támogató megengedett modell (jelöltek: " + ", ".join(g["model_candidates"]) + "). Állj meg és kérdezz.")


def check_model_allowed(model, cfg):
    cands = cfg["gemini"]["model_candidates"]
    if not any(model == c or model.startswith(c + "-") for c in cands):
        raise NeedUserDecision(f"A {model} nem a megengedett smoke-modellek közül való ({', '.join(cands)}). Állj meg és kérdezz.")


# ---------------------------------------------------------------- kiválasztás

def select_smoke(records, sample_ids, cfg):
    """20 cím a 250 elemű mintából, rétegenként 5. A kérések sorrendje rétegek szerint váltakozik, így korai leállásnál is minden réteg szerepel."""
    s = cfg["gemini"]["smoke"]
    strata = cfg["sample"]["strata"]
    by = {r.id: r for r in records}
    groups = [[] for _ in strata]
    for rid in sorted(sample_ids):
        if rid in by:
            groups[samp.stratum_of(by[rid].human_mean, strata)].append(rid)
    rng = random.Random(s["seed"])
    picked = []
    for i, g in enumerate(groups):
        if len(g) < s["per_stratum"]:
            raise samp.SampleError(f"a(z) {strata[i]['name']} rétegben csak {len(g)} elem van, {s['per_stratum']} kell")
        picked.append(rng.sample(g, s["per_stratum"]))
    order = [picked[i][k] for k in range(s["per_stratum"]) for i in range(len(strata))]
    if len(order) != s["n_titles"]:
        raise samp.SampleError("a kiválasztott címek száma nem egyezik a smoke test darabszámával")
    stratum = {rid: strata[samp.stratum_of(by[rid].human_mean, strata)]["name"] for rid in order}
    return order, stratum


# ---------------------------------------------------------------- száraz próba

def leak_strings_for(inst_row, truth_row):
    """A kérésben nem szerepelhető szövegek egy rekordhoz: a cikk mezői és az emberi ítélet."""
    out = []
    for k in ("targetTitle", "targetDescription", "targetKeywords", "targetCaptions"):
        v = inst_row.get(k)
        out += [v] if isinstance(v, str) else [x for x in (v or []) if isinstance(x, str)]
    out += [p for p in (inst_row.get("targetParagraphs") or []) if isinstance(p, str)]
    for k in ("truthMean", "truthMedian", "truthMode"):
        if isinstance(truth_row.get(k), (int, float)):
            out += [repr(truth_row[k]), f"{truth_row[k]:.4f}"]
    out += [str(truth_row.get("truthJudgments", ""))]
    return out


def build_dryrun(inputs, cfg, leaks=None):
    """inputs: [{id, postText}] a kérések sorrendjében. Visszaad: (sorok, hibák). Hibás kérés nem kerül a sorok közé."""
    rows, errors = [], []
    for i, item in enumerate(inputs):
        try:
            body = gr.build_body(item["postText"], cfg)
        except gr.RequestError as e:
            errors.append({"id": item["id"], "error": str(e)})
            continue
        errs = gr.check_request(body, item["postText"], cfg, (leaks or {}).get(item["id"], ()))
        if errs:
            errors.append({"id": item["id"], "error": "; ".join(errs)})
            continue
        rows.append({"index": i, "id": item["id"], "body_sha256": gr.body_sha256(body), "body": body})
    return rows, errors


def verify_dryrun_rows(rows, inputs, cfg, strata_of=None, leaks=None):
    """A (fájlból újraolvasott) száraz próba független ellenőrzése. Üres lista = minden feltétel teljesül."""
    s = cfg["gemini"]["smoke"]
    errs = []
    if len(rows) != s["n_titles"]:
        errs.append(f"a kérések száma {len(rows)}, nem {s['n_titles']}")
    by_text = {x["id"]: x["postText"] for x in inputs}
    if [r.get("id") for r in rows] != [x["id"] for x in inputs]:
        errs.append("a kérések azonosítói vagy sorrendje nem egyezik a kiválasztott bemenettel")
    for r in rows:
        if set(r) != {"index", "id", "body_sha256", "body"}:
            errs.append(f"{r.get('id')}: a sor mezői nem pontosan index, id, body_sha256, body")
            continue
        text = by_text.get(r["id"])
        if text is None:
            errs.append(f"{r['id']}: ismeretlen azonosító")
            continue
        for e in gr.check_request(r["body"], text, cfg, (leaks or {}).get(r["id"], ())):
            errs.append(f"{r['id']}: {e}")
        try:
            if gr.body_sha256(r["body"]) != r["body_sha256"]:
                errs.append(f"{r['id']}: a body_sha256 nem egyezik a törzzsel")
        except TypeError:
            errs.append(f"{r['id']}: a body_sha256 nem számítható")
        if has_hungarian_chars(json.dumps(r, ensure_ascii=False)):
            errs.append(f"{r['id']}: magyar-specifikus karakter a sorban")
    if strata_of is not None:
        counts = {}
        for r in rows:
            counts[strata_of.get(r["id"])] = counts.get(strata_of.get(r["id"]), 0) + 1
        want = {st["name"]: s["per_stratum"] for st in cfg["sample"]["strata"]}
        if counts != want:
            errs.append(f"a rétegenkénti darabszám {counts}, kellene: {want}")
    return errs


def write_dryrun(out_dir, inputs, rows, strata_of, report, results_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    check_write(out_dir / "x", results_dir)
    lines = lambda items: "\n".join(json.dumps(x, ensure_ascii=False) for x in items) + "\n"
    check_write(out_dir / "selected_inputs.jsonl", results_dir).write_text(lines(inputs), encoding="utf-8")
    check_write(out_dir / "requests_dryrun.jsonl", results_dir).write_text(lines(rows), encoding="utf-8")
    check_write(out_dir / "dryrun_check.json", results_dir).write_text(json.dumps({**report, "strata_of": strata_of}, ensure_ascii=False, indent=1), encoding="utf-8")


def read_jsonl_file(path, base):
    return [json.loads(l) for l in check_read(path, base).read_text(encoding="utf-8").splitlines() if l.strip()]


# ---------------------------------------------------------------- futtató (átvitel kívülről)

def run_smoke(inputs, transport, cfg, out_dir, results_dir, model, reference=None, sleep=time.sleep, monotonic=time.monotonic):
    """A smoke test futtatása KÍVÜLRŐL kapott átvitellel: transport(model, body) -> Raw, vagy TransportTimeout.
    Megáll a napi kvótánál, végzetes hibánál és a kérésszám-plafonnál; a 250 elemű futás nem létezik."""
    s = cfg["gemini"]["smoke"]
    check_model_allowed(model, cfg)
    if len(inputs) != s["n_titles"]:
        raise ValueError(f"a smoke test fix {s['n_titles']} címre szól, nem {len(inputs)}-re")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {k: check_write(out_dir / f, results_dir) for k, f in (("raw", "raw_responses.jsonl"), ("scores", "scores.jsonl"), ("errors", "errors.jsonl"), ("report", "smoke_report.json"))}
    done = {}
    if paths["scores"].exists():                                  # folytatható: a kész címek nem mennek ki újra
        done = {x["id"]: x for x in (json.loads(l) for l in paths["scores"].read_text(encoding="utf-8").splitlines() if l.strip())}

    def append(key, obj):
        with open(paths[key], "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    st = {"sent": 0, "retries": 0, "ok": len(done), "failed": 0, "blocked": 0, "not_attempted": 0, "stop_reason": None,
          "tokens": {"promptTokenCount": 0, "candidatesTokenCount": 0, "thoughtsTokenCount": 0, "totalTokenCount": 0},
          "latencies": [], "model_versions": set(), "errors_by_kind": {}}
    last = [None]

    def pace():
        if last[0] is not None:
            wait = s["min_interval_s"] - (monotonic() - last[0])
            if wait > 0:
                sleep(wait)

    stop = False
    for item in inputs:
        rid, text = item["id"], item["postText"]
        if rid in done:
            continue
        if stop:
            st["not_attempted"] += 1
            continue
        body = gr.build_body(text, cfg)
        tries = {"invalid": 0, "transient": 0}
        attempt = 0
        while True:
            attempt += 1
            if st["sent"] >= s["max_requests"]:
                st["stop_reason"], stop = "request_cap", True
                st["not_attempted"] += 1
                break
            pace()
            last[0] = monotonic()
            st["sent"] += 1
            try:
                raw = transport(model, body)
                out = gr.parse_response(raw.status, raw.text, text, rid, cfg)
                append("raw", {"id": rid, "attempt": attempt, "http_status": raw.status, "latency_ms": raw.latency_ms, "finishReason": out.finish_reason,
                               "promptFeedback_blockReason": out.block_reason, "usageMetadata": out.usage, "text": raw.text})
                st["latencies"].append(raw.latency_ms)
            except TransportTimeout:
                out = gr.Outcome("transient", "időtúllépés")
                append("raw", {"id": rid, "attempt": attempt, "http_status": None, "timeout": True})
            for k in st["tokens"]:
                st["tokens"][k] += out.usage.get(k, 0) or 0
            if out.model_version:
                st["model_versions"].add(out.model_version)
            if out.kind == "ok":
                append("scores", out.score)
                st["ok"] += 1
                break
            st["errors_by_kind"][out.kind] = st["errors_by_kind"].get(out.kind, 0) + 1
            append("errors", {"id": rid, "attempt": attempt, "kind": out.kind, "detail": out.detail})
            if out.kind == "blocked":
                st["blocked"] += 1
                break
            if out.kind in ("quota_day", "fatal"):
                st["stop_reason"], stop = out.kind, True
                st["not_attempted"] += 1
                break
            if out.kind == "truncated":
                st["failed"] += 1
                break
            if out.kind in ("invalid", "empty"):
                tries["invalid"] += 1
                if tries["invalid"] > s["invalid_retries"]:
                    st["failed"] += 1
                    break
                st["retries"] += 1
                continue
            if out.kind in ("transient", "quota_minute"):
                if tries["transient"] >= s["max_retries"]:
                    st["failed"] += 1
                    break
                wait = out.retry_after if out.kind == "quota_minute" and out.retry_after else (s["backoff_s"][min(tries["transient"], len(s["backoff_s"]) - 1)] if out.kind == "transient" else s["min_interval_s"])
                tries["transient"] += 1
                st["retries"] += 1
                sleep(wait)
                continue
            st["failed"] += 1
            break
    scores = [json.loads(l) for l in paths["scores"].read_text(encoding="utf-8").splitlines() if l.strip()] if paths["scores"].exists() else []
    report = _report(inputs, scores, st, cfg, model, reference)
    paths["report"].write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def _report(inputs, scores, st, cfg, model, reference):
    s, pr = cfg["gemini"]["smoke"], cfg["gemini"]["prices_usd_per_million"]
    tok = st["tokens"]
    cost = None
    if pr.get("input") is not None and pr.get("output") is not None:
        cost = round((tok["promptTokenCount"] * pr["input"] + (tok["candidatesTokenCount"] + tok["thoughtsTokenCount"]) * pr["output"]) / 1e6, 6)
    lat = st["latencies"]
    rep = {"model_requested": model, "model_versions_seen": sorted(st["model_versions"]), "tier": cfg["gemini"]["tier"],
           "thinking_config": cfg["gemini"]["generation"].get("thinking_config"), "prompt_sha256": gr.text_sha256(gr.SYSTEM_INSTRUCTION),
           "schema_sha256": gr.text_sha256(gr.canonical_json(gr.response_schema(cfg))),
           "n_selected": len(inputs), "requests_sent": st["sent"], "retries": st["retries"], "n_valid": len(scores), "n_failed": st["failed"],
           "n_blocked": st["blocked"], "n_not_attempted": st["not_attempted"], "stop_reason": st["stop_reason"], "errors_by_kind": st["errors_by_kind"],
           "tokens": tok, "cost_usd": 0.0 if cfg["gemini"]["tier"] == "free" else cost,
           "cost_if_paid_usd": cost, "cost_note": pr.get("note"),
           "latency_ms": {"min": min(lat), "median": statistics.median(lat), "max": max(lat)} if lat else None,
           "pass": len(scores) >= s["pass_min_valid"] and st["stop_reason"] is None, "pass_min_valid": s["pass_min_valid"]}
    if reference and len(scores) >= 5:
        pairs = [(reference[x["id"]], x["scaled"]) for x in scores if x["id"] in reference]
        rep["descriptive_vs_truthMean"] = {"n": len(pairs), "spearman": ev.spearman([a for a, _ in pairs], [b for _, b in pairs]),
                                           "note": "n=20, csak a csővezeték ellenőrzése, következtetésre nem alkalmas"}
    return rep
