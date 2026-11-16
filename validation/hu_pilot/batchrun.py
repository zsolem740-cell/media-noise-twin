"""Csomagos modellfuttatás (KÍSÉRLET): egy kérésben több cím. HÁLÓZATI KÓD NINCS ITT, az átvitelt kívülről kapja (transport(model, body) -> Raw).

Célja: kiderül, egyezik-e a csomagos eredmény az eddig elfogadott egy cím egy kérésben móddal (compare), mielőtt az éles címkézésben csomagot használnánk.
A pilot mérése MARAD egy cím egy kérésben; ez külön futás, külön névvel, azonos 50 címen.

Szabályok ugyanazok, mint a modelrun.py-ban: lezárási kapu, nincs szolgáltatóváltás, napi kvótánál megáll (a kész címek megmaradnak), folytatás a visszaállás + 5 perc után
(első kérés próba, napi legfeljebb 3), minden kérés naplózva (szolgáltató, modell, kimenetel, tokenek), kulcs sehol.
A csomag-összeállítás determinisztikus (rögzített mag), a cím-hozzárendelés a state.json-ban rögzített, így a folytatás ugyanazokat a csomagokat adja.
Hibakezelés: csonka vagy blokkolt válasznál a csomag felezése (a hibás cím elkülönül), címenkénti érvénytelen válasz egyszer újra csomagba kerül, utána hiba."""
import json
import random
import time as _time
from collections import deque
from datetime import timedelta
from pathlib import Path

from . import prompt as P
from . import providers as V
from . import quota as Q
from .freeze import check_manifest, require_freeze
from .modelrun import (RunRefused, TransportTimeout, _jl_append, _jl_read, _utcnow, _write_results, _write_state, check_policy)
from .paths import check_write


def partition(ids, size, seed):
    """Determinisztikus csomagokra osztás: az azonosítók sorbarendezve, rögzített maggal megkeverve (a szomszéd címek véletlenek, nem a feed sorrendje)."""
    ids = sorted(ids)
    random.Random(seed * 1000 + size).shuffle(ids)
    return [ids[i:i + size] for i in range(0, len(ids), size)]


def build_requests(titles, provider, cfg, size):
    by = {t["id"]: t["title"] for t in titles}
    seed = cfg["seed"]
    batches = partition(by, size, seed)
    return batches, [{"index": n, "ids": b, "provider": provider, "body_sha256": V.body_sha256(V.BATCH_BUILDERS[provider]([by[i] for i in b], cfg["model"])),
                      "body": V.BATCH_BUILDERS[provider]([by[i] for i in b], cfg["model"])} for n, b in enumerate(batches)]


def verify_requests(rows, titles, provider, cfg):
    by, errs = {t["id"]: t["title"] for t in titles}, []
    flat = [i for r in rows for i in r["ids"]]
    if sorted(flat) != sorted(by):
        errs.append("a csomagok együtt nem pontosan az összes cím")
    for r in rows:
        errs += [f"csomag {r['index']}: {e}" for e in V.check_batch_body(provider, r["body"], [by[i] for i in r["ids"]], cfg["model"])]
        if r["body_sha256"] != V.body_sha256(r["body"]):
            errs.append(f"csomag {r['index']}: a hash nem egyezik")
    return errs


def run_batch_measurement(titles, provider, transport, cfg, rdir, run_name, model, size, now=_utcnow, sleep=_time.sleep, monotonic=_time.monotonic, manifest=None):
    check_policy(cfg)
    m, run_cfg, bcfg = cfg["model"], cfg["model"]["run"], cfg["model"]["batch"]
    if provider not in m["providers"]:
        raise RunRefused(f"ismeretlen szolgáltató: {provider}")
    if not isinstance(size, int) or isinstance(size, bool) or not 2 <= size <= bcfg["max_size"]:
        raise RunRefused(f"a csomag mérete 2 és {bcfg['max_size']} között lehet")
    pcfg = m["providers"][provider]
    man = require_freeze(rdir, cfg) if manifest is None else check_manifest(manifest)
    if sorted(t["id"] for t in titles) != sorted(man["anchor_ids"] + man["measured_ids"]):
        raise RunRefused("a címek azonosítói nem egyeznek a lezárt jegyzékkel")
    for t in titles:
        V.check_text(t["title"])
    by = {t["id"]: t["title"] for t in titles}
    run_dir = Path(rdir) / cfg["files"]["model_runs_dir"] / run_name
    check_write(run_dir / "x", rdir)
    run_dir.mkdir(parents=True, exist_ok=True)
    sp, lp, qp, scp = run_dir / "state.json", run_dir / "log.jsonl", run_dir / "quota_stops.jsonl", run_dir / "scores.jsonl"
    p_sha = V.sha256_text(P.SYSTEM_INSTRUCTION)
    s_sha = V.sha256_text(P.canonical_json(P.gemini_batch_schema(m["max_points_per_signal"])))
    t0 = now()
    if sp.exists():
        st = json.loads(sp.read_text(encoding="utf-8"))
        if (st.get("mode"), st["provider"], st["model"], st["prompt_sha256"], st.get("batch_size")) != ("batch", provider, model, p_sha, size) or st["ids"] != [t["id"] for t in titles]:
            raise RunRefused("a folytatás módja, szolgáltatója, modellje, promptja, csomagmérete vagy címlistája eltér az induló futásétól")
        if st["status"] == "complete":
            return _finish(run_dir, st, titles, {s["id"]: s for s in _jl_read(scp)}, "complete", size)
        ra = st.get("resume_after_utc")
        if ra and Q.as_utc(t0) < Q.parse_iso(ra):
            raise RunRefused(f"a folytatás ideje még nem jött el: {ra}")
        day = Q.quota_day_key(pcfg, t0)
        if sum(1 for p in st["probes"] if p["quota_day"] == day) >= run_cfg["probes_per_quota_day"]:
            raise RunRefused(f"erre a kvótanapra ({day}) elfogyott a napi {run_cfg['probes_per_quota_day']} próba")
        probing = bool(st.get("probe_pending"))
    else:
        st = {"run_id": run_name, "mode": "batch", "batch_size": size, "provider": provider, "model": model, "key_alias": pcfg["key_alias"], "prompt_sha256": p_sha, "schema_sha256": s_sha,
              "ids": [t["id"] for t in titles], "batches": partition(by, size, cfg["seed"]), "status": "running", "resume_after_utc": None, "probes": [], "quota_stops": 0,
              "probe_pending": False, "failed": {}, "invalid_counts": {}, "invocations": 0}
        probing = False
    st["invocations"] += 1
    st["status"], st["resume_after_utc"] = "running", None
    scores = {s["id"]: s for s in _jl_read(scp)}
    terminal = {"invalid", "empty", "truncated", "blocked"}
    dead = lambda i: i in st["failed"] and st["failed"][i]["kind"] in terminal
    units = deque(u for u in ([i for i in b if i not in scores and not dead(i)] for b in st["batches"]) if u)
    sent, last, consec_fail, pauses, requeued, pending_retry = [0], [None], [0], [0], set(), []
    second_pass = [False]

    def log(unit, attempt, out, status, latency, probe):
        _jl_append(lp, {"utc": Q.iso(now()), "run_id": st["run_id"], "workload": "measurement_batch", "provider": provider, "model_requested": model, "model_returned": out.model_returned,
                        "key_alias": pcfg["key_alias"], "id": f"batch[{len(unit)}]", "ids": list(unit), "batch_size": len(unit), "attempt": attempt, "probe": probe, "http_status": status,
                        "outcome": out.kind, "detail": V.sanitize(out.detail, 200), "usage": out.usage, "latency_ms": latency, "retry_after_s": out.retry_after, "finish_reason": out.finish_reason})

    def stop(status, resume_at=None):
        st["status"], st["resume_after_utc"] = status, (Q.iso(resume_at) if resume_at else None)
        _write_state(sp, st)
        return _finish(run_dir, st, titles, scores, status, size)

    def send(unit, attempt, probe):
        posts = [by[i] for i in unit]
        body = V.BATCH_BUILDERS[provider](posts, m)
        if sent[0] >= run_cfg["max_requests"]:
            return None
        if last[0] is not None:
            w = pcfg["min_interval_s"] - (monotonic() - last[0])
            if w > 0:
                sleep(w)
        sent[0] += 1
        last[0] = monotonic()
        started = monotonic()
        try:
            raw = transport(model, body)
            out = V.parse_batch_response(provider, raw.status, raw.text, posts, m, raw.retry_after)
            status, latency = raw.status, raw.latency_ms or int((monotonic() - started) * 1000)
        except TransportTimeout:
            out, status, latency = V.BatchOutcome("transient", "időtúllépés"), None, None
        except ConnectionError:
            out, status, latency = V.BatchOutcome("transient", "hálózati hiba"), None, None
        log(unit, attempt, out, status, latency, probe)
        return out

    def fail_titles(unit, kind, detail):
        for i in unit:
            st["failed"][i] = {"kind": kind, "detail": V.sanitize(detail, 200)}

    def split(unit):
        h = len(unit) // 2
        units.appendleft(unit[h:])
        units.appendleft(unit[:h])

    while True:
        if not units:
            if pending_retry and not second_pass[0]:                       # a címenként érvénytelenek még egyszer csomagba kerülnek
                second_pass[0] = True
                units.extend(pending_retry[i:i + size] for i in range(0, len(pending_retry), size))
                pending_retry = []
                continue
            break
        unit = units.popleft()
        tries = {"invalid": 0, "transient": 0}
        attempt = 0
        while True:
            attempt += 1
            probe = probing
            if probe:
                st["probes"].append({"utc": Q.iso(now()), "quota_day": Q.quota_day_key(pcfg, now())})
            out = send(unit, attempt, probe)
            if out is None:
                return stop("stopped_request_cap")
            if out.kind != "quota_day" and probing:
                probing = False
                st["probe_pending"] = False
            if out.kind == "ok":
                for i, it in zip(unit, out.items):
                    if it.kind == "ok":
                        rec = {"id": i, "provider": provider, "model_requested": model, "model_returned": it.model_returned, "utc": Q.iso(now()), "batch_size": len(unit), **it.score}
                        _jl_append(scp, rec)
                        scores[i] = rec
                        st["failed"].pop(i, None)
                    else:
                        c = st["invalid_counts"][i] = st["invalid_counts"].get(i, 0) + 1
                        if c <= run_cfg["invalid_retries"]:
                            pending_retry.append(i)
                        else:
                            fail_titles([i], "invalid", it.detail)
                consec_fail[0] = 0
                break
            if out.kind == "quota_day":
                fallback = timedelta(minutes=run_cfg["fallback_probe_wait_min"])
                reset = Q.resume_after_utc(pcfg, now(), run_cfg["resume_margin_min"])
                if probe:
                    wait = timedelta(seconds=out.retry_after) if out.retry_after else fallback
                    resume_at = min(Q.as_utc(now()) + wait + timedelta(minutes=run_cfg["resume_margin_min"]), reset)
                else:
                    resume_at = reset
                st["quota_stops"] += 1
                st["probe_pending"] = True
                _jl_append(qp, {"utc": Q.iso(now()), "run_id": st["run_id"], "provider": provider, "model": model, "probe": probe, "evidence": V.sanitize(out.detail, 200), "provider_hint_s": out.retry_after,
                                "done": len(scores), "pending": len(titles) - len(scores) - sum(1 for k, v in st["failed"].items() if v["kind"] in terminal),
                                "resume_after_utc": Q.iso(resume_at), "failover": "nincs (mérési futás)"})
                return stop("stopped_quota", resume_at)
            if out.kind in ("fatal", "billing"):
                _jl_append(qp, {"utc": Q.iso(now()), "run_id": st["run_id"], "provider": provider, "kind": out.kind, "evidence": V.sanitize(out.detail, 200), "failover": "nincs"})
                return stop("stopped_billing" if out.kind == "billing" else "stopped_fatal")
            if out.kind in ("blocked", "truncated") or (out.kind in ("invalid", "empty") and tries["invalid"] >= run_cfg["invalid_retries"]):
                if len(unit) > 1:
                    split(unit)                                            # felezés: a hibát okozó cím elkülönül
                else:
                    fail_titles(unit, out.kind, out.detail)
                break
            if out.kind in ("invalid", "empty"):
                tries["invalid"] += 1
                continue
            if out.kind == "quota_minute":
                if out.retry_after and out.retry_after > run_cfg["max_wait_s"]:
                    return stop("stopped_long_wait", Q.as_utc(now()) + timedelta(seconds=out.retry_after, minutes=run_cfg["resume_margin_min"]))
                if tries["transient"] >= run_cfg["max_retries"]:
                    fail_titles(unit, "transient_failed", "percenkénti korlát: az újrapróbák elfogytak")
                    consec_fail[0] += 1
                    break
                wait = max(out.retry_after or 0.0, run_cfg["backoff_s"][min(tries["transient"], len(run_cfg["backoff_s"]) - 1)])
                tries["transient"] += 1
                sleep(min(wait, run_cfg["max_wait_s"]))
                continue
            if out.kind == "transient":
                if tries["transient"] >= run_cfg["max_retries"]:
                    fail_titles(unit, "transient_failed", out.detail)
                    consec_fail[0] += 1
                    break
                sleep(run_cfg["backoff_s"][min(tries["transient"], len(run_cfg["backoff_s"]) - 1)])
                tries["transient"] += 1
                continue
            raise RuntimeError(f"ismeretlen kimenetel: {out.kind}")
        key = tuple(unit)
        if all(i in st["failed"] and st["failed"][i]["kind"] == "transient_failed" for i in unit) and key not in requeued:
            requeued.add(key)
            units.append(list(unit))                                        # a végén még egyszer sorra kerül
        if consec_fail[0] >= run_cfg["outage_consecutive"]:
            pauses[0] += 1
            if pauses[0] > run_cfg["outage_pauses_max"]:
                return stop("stopped_outage")
            sleep(run_cfg["transient_pause_s"])
            consec_fail[0] = 0
        _write_state(sp, st)
    pending = [t for t in titles if t["id"] not in scores and t["id"] not in st["failed"]]
    return stop("complete" if not pending and not any(v["kind"] == "transient_failed" for v in st["failed"].values()) else "incomplete")


def _finish(run_dir, st, titles, scores, status, size):
    summary = _write_results(run_dir, st, titles, scores, status)
    summary.update({"workload": "measurement_batch", "mode": "batch", "batch_size": size, "n_batches": len(st["batches"]), "schema_sha256": st["schema_sha256"]})
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary
