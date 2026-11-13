"""A Groq-feldolgozás futtatója és naplózása. HÁLÓZAT NÉLKÜL: az átvitelt kívülről kapja (transport(body_bytes) -> Raw, vagy TransportTimeout).

A kimenet csak results/groq/ alá kerül (groq_results.csv, groq_log.jsonl, groq_summary.json). A Gemini-fájlokhoz nem nyúl, nem ír beléjük és nem olvassa a Gemini-eredményeket.
Nincs automatikus súlyozás, nincs fizetős váltás, nincs több kulcs. Megáll: napi korlátnál, végzetes hibánál, a kérésszám-plafonnál."""
import csv
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import groq_request as rq
from .gemini_request import canonical_json
from .isolation import check_read, check_write

MAX_WAIT_S = 120.0


@dataclass
class Raw:
    status: int
    text: str
    retry_after: str | None = None
    elapsed: float = 0.0


class TransportTimeout(Exception):
    pass


def batches_of(inputs, size):
    return [inputs[i:i + size] for i in range(0, len(inputs), size)]


def build_dryrun(inputs, cfg, leaks=None):
    """A kérések törzse hálózat és kulcs nélkül. inputs = [{"id", "postText"}]. Visszaad: sorok, hibák."""
    rows, errors = [], []
    for n, batch in enumerate(batches_of(inputs, cfg["groq"]["batch_size"]), 1):
        items = [(lid, b["postText"]) for lid, b in zip(rq.local_ids(len(batch)), batch)]
        try:
            body = rq.build_body(items, cfg)
        except rq.RequestError as e:
            errors.append(f"{n}. csomag: {e}")
            continue
        leak = [s for b in batch for s in (leaks or {}).get(b["id"], ())]
        errs = rq.check_request(body, items, cfg, leak)
        errors += [f"{n}. csomag: {e}" for e in errs]
        rows.append({"batch_no": n, "ids": [b["id"] for b in batch], "local_ids": [i for i, _ in items], "body_sha256": _sha(body), "body": body})
    return rows, errors


def _sha(body):
    import hashlib
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def verify_dryrun_rows(rows, inputs, cfg, leaks=None):
    """Független ellenőrzés a fájlból újraolvasott sorokon."""
    errs = []
    size = cfg["groq"]["batch_size"]
    exp = batches_of(inputs, size)
    if len(rows) != len(exp):
        errs.append(f"csomagok száma {len(rows)}, várt {len(exp)}")
    flat = [i for r in rows for i in r["ids"]]
    if flat != [x["id"] for x in inputs]:
        errs.append("a csomagok címei nem pontosan a bemeneti címek, eredeti sorrendben")
    if len(set(flat)) != len(flat):
        errs.append("ismétlődő cím a csomagokban")
    for r, batch in zip(rows, exp):
        items = [(lid, b["postText"]) for lid, b in zip(rq.local_ids(len(batch)), batch)]
        if len(batch) > size:
            errs.append(f"{r['batch_no']}. csomag túl nagy")
        if r["body_sha256"] != _sha(r["body"]):
            errs.append(f"{r['batch_no']}. csomag: a hash nem egyezik")
        leak = [s for b in batch for s in (leaks or {}).get(b["id"], ())]
        errs += [f"{r['batch_no']}. csomag: {e}" for e in rq.check_request(r["body"], items, cfg, leak)]
    return errs


CSV_FIELDS = ["id", "batch_no", "status", "failure", "total", "scaled", "model"] + \
    [f"{s}_{p}" for s in ("curiosity_gap", "exaggeration", "emotional_pressure", "formal_noise") for p in ("score", "reason", "span")]


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_groq(inputs, transport, cfg, out_dir, results_dir, strata_of=None, sleep=time.sleep, monotonic=time.monotonic):
    """A csomagos futtatás. Létező groq_results.csv-t nem ír felül. Kimenetek: CSV, napló, összegzés."""
    g = cfg["groq"]
    run = g["run"]
    p = g["paths"]
    out_dir = Path(out_dir)
    if len(inputs) != g["n_titles"]:
        raise ValueError(f"a Groq-futás fix {g['n_titles']} címre szól, nem {len(inputs)}-re")
    check_write(out_dir / "x", results_dir)
    csv_path, log_path, sum_path = (check_write(out_dir / p[k], results_dir) for k in ("results_csv", "log", "summary"))
    for f in (csv_path, log_path, sum_path):
        if f.exists():
            raise FileExistsError(f"{f.name} már létezik: a futás nem ír felül semmit")
    out_dir.mkdir(parents=True, exist_ok=True)
    log = log_path.open("x", encoding="utf-8")
    state = {"requests": 0, "last_start": None, "stop": None, "tok": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0}}
    kinds = {}
    rows = []

    def pace():
        if state["last_start"] is not None:
            wait = run["min_interval_s"] - (monotonic() - state["last_start"])
            if wait > 0:
                sleep(wait)

    def call(batch_no, attempt, items):
        """Egy csomag elküldése átmeneti hibák és percenkénti korlát esetén legfeljebb max_retries újrapróbával. Visszaad: BatchOutcome."""
        try:
            body = rq.build_body(items, cfg)
            errs = rq.check_request(body, items, cfg)
        except rq.RequestError as e:
            errs = [str(e)]
        if errs:
            state["stop"] = "a kimenő kérés ellenőrzése sikertelen"          # semmi nem megy ki; a már kész címek megmaradnak a CSV-ben
            return rq.BatchOutcome("fatal", ("a kimenő kérés ellenőrzése sikertelen: " + "; ".join(errs))[:300])
        raw_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        tries = 0
        while True:
            if state["requests"] >= run["max_requests"]:
                state["stop"] = "kérésszám-plafon"
                return rq.BatchOutcome("fatal", "elérte a kérésszám-plafont")
            pace()
            state["requests"] += 1
            state["last_start"] = monotonic()
            t0 = monotonic()
            try:
                raw = transport(raw_body)
                out = rq.parse_response(raw.status, raw.text, items, cfg, raw.retry_after)
                status = raw.status
            except TransportTimeout:
                out, status = rq.BatchOutcome("transient", "időtúllépés"), None
            except ConnectionError as e:
                out, status = rq.BatchOutcome("transient", str(e)), None
            except Exception as e:                                           # váratlan átviteli hiba: megáll, de a CSV és az összegzés elkészül
                out, status = rq.BatchOutcome("fatal", f"váratlan átviteli hiba: {type(e).__name__}"), None   # az üzenet szándékosan kimarad
            kinds[out.kind] = kinds.get(out.kind, 0) + 1
            for k in state["tok"]:
                state["tok"][k] += out.usage.get(k, 0) or 0
            log.write(json.dumps({"utc": _now(), "request_no": state["requests"], "batch_no": batch_no, "attempt": attempt, "try": tries, "n_titles": len(items),
                                  "http_status": status, "outcome": out.kind, "detail": out.detail, "elapsed_s": round(monotonic() - t0, 2),
                                  "usage": out.usage, "finish_reason": out.finish_reason, "model": out.model, "retry_after_s": out.retry_after,
                                  "n_valid": len(out.results), "item_errors": out.item_errors, "stray_items": out.stray}, ensure_ascii=False) + "\n")
            log.flush()
            if out.kind == "quota_day":
                state["stop"] = "napi korlát"
                return out
            if out.kind == "fatal":
                state["stop"] = "váratlan átviteli hiba" if status is None else "végzetes hiba"
                return out
            if out.kind in ("transient", "quota_minute") and tries < run["max_retries"]:
                wait = max(out.retry_after or 0.0, run["backoff_s"][min(tries, len(run["backoff_s"]) - 1)])
                if wait > MAX_WAIT_S:
                    state["stop"] = "a várakozás túl hosszú: felhasználói döntés kell"
                    return out
                tries += 1
                sleep(wait)
                continue
            return out

    try:
        for batch_no, batch in enumerate(batches_of(inputs, g["batch_size"]), 1):
            if state["stop"]:
                for b in batch:
                    rows.append({"id": b["id"], "batch_no": batch_no, "status": "not_run", "failure": state["stop"]})
                continue
            done, failure = {}, {}
            unresolved = list(batch)
            for attempt in range(1 + run["invalid_retries"]):
                if not unresolved or state["stop"]:
                    break
                items = [(lid, b["postText"]) for lid, b in zip(rq.local_ids(len(unresolved)), unresolved)]
                lmap = {lid: b for (lid, _), b in zip(items, unresolved)}
                out = call(batch_no, attempt, items)
                for lid, sc in out.results.items():
                    done[lmap[lid]["id"]] = ({**sc, "id": lmap[lid]["id"]}, out.model)
                if out.kind == "ok":
                    failure = {lmap[l]["id"]: e for l, e in out.item_errors.items()}
                else:
                    failure = {b["id"]: f"{out.kind}: {out.detail}"[:200] for b in unresolved}
                unresolved = [b for b in unresolved if b["id"] not in done]
                if out.kind in ("transient", "quota_minute", "truncated"):
                    break                                          # az újrapróbák már elfogytak; a csonkolt kimenet ugyanazzal a kéréssel újra csonkolódna (mint a Gemini-ág MAX_TOKENS esete); újrapróba csak invalid/empty esetén van
            for b in batch:
                if b["id"] in done:
                    sc, model = done[b["id"]]
                    r = {"id": b["id"], "batch_no": batch_no, "status": "ok", "failure": "", "total": sc["total"], "scaled": sc["scaled"], "model": model or ""}
                    for s, v in sc["signals"].items():
                        r.update({f"{s}_score": v["score"], f"{s}_reason": v["reason"], f"{s}_span": v["span"]})
                else:
                    r = {"id": b["id"], "batch_no": batch_no, "status": "failed", "failure": failure.get(b["id"], state["stop"] or "ismeretlen")}
                rows.append(r)
    finally:
        log.close()
    with csv_path.open("x", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="raise")
        w.writeheader()
        w.writerows(rows)
    nb = {}
    for r in rows:
        nb.setdefault(r["batch_no"], []).append(r["status"])
    summary = {"model": g["model"], "tier": "free (nincs automatikus váltás fizetősre)", "key_env_var": g["env_var"], "keys_used": 1,
               "requests_sent": state["requests"], "request_cap": run["max_requests"], "tokens": state["tok"], "outcomes": kinds,
               "batches_total": len(nb), "batches_ok": sum(1 for v in nb.values() if all(s == "ok" for s in v)),
               "batches_failed": sum(1 for v in nb.values() if any(s != "ok" for s in v)),
               "titles_ok": sum(1 for r in rows if r["status"] == "ok"), "titles_failed": sum(1 for r in rows if r["status"] == "failed"),
               "titles_not_run": sum(1 for r in rows if r["status"] == "not_run"), "pass_min_valid": run["pass_min_valid"],
               "passed": sum(1 for r in rows if r["status"] == "ok") >= run["pass_min_valid"], "stopped_because": state["stop"],
               "weighting": "nincs", "gemini_files_touched": False}
    sum_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary
