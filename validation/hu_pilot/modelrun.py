"""A pilot modellfuttatója: egy szolgáltató, egy cím egy kérésben, közös prompt és séma. HÁLÓZATI KÓD NINCS ITT: az átvitelt kívülről kapja (transport(model, body) -> Raw, vagy TransportTimeout).

Kapuk és szabályok (failover terv v3, MÉRÉSI futás):
- csak érvényes lezárási jegyzékkel indul (freeze.require_freeze), és csak a lezárt cím-azonosítókkal;
- NINCS váltás szolgáltatók között: a modul egyetlen átvitelt ismer, a konfigurációban a failover nem kapcsolható be;
- napi kvóta kimerülésekor a futás megáll, a kész címek megmaradnak, a nem küldöttek függőben maradnak, a folytatás ideje a visszaállás + 5 perc;
- a folytatás kézi vagy a felhasználó által időzített, az első kérés próba, kvótanaponként legfeljebb 3 próba; a kész címeket nem küldi újra;
- a naplóban minden kérésnél látszik a szolgáltató (és a kért/visszaadott modell); kulcs sehol nincs (a kulcs-azonosító csak név)."""
import csv
import json
import time as _time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import prompt as P
from . import providers as V
from . import quota as Q
from .freeze import NotFrozen, require_freeze
from .paths import check_write


class TransportTimeout(Exception):
    pass


@dataclass
class Raw:
    status: int
    text: str
    retry_after: str | None = None
    latency_ms: int = 0


class RunRefused(Exception):
    """A futás (vagy a folytatás) nem indulhat: gyakran az idő, a próbák száma vagy a konfiguráció miatt."""


def _utcnow():
    return datetime.now(timezone.utc)


def check_policy(cfg):
    f, m = cfg["model"]["failover"], cfg["model"]
    if m.get("workload") != "measurement":
        raise RunRefused("a modellfuttató csak mérési (measurement) munkaosztályra való")
    if f.get("enabled") or f.get("measurement_allowed"):
        raise RunRefused("mérési futáson a failover nem engedélyezett (a konfigurációban nem kapcsolható be)")


def load_titles(rdir, cfg):
    """A lezárt 50 cím a pilot-feedekből, a kiválasztás sorrendjében (horgonyok, majd mérési)."""
    f = cfg["files"]
    sel = json.loads((Path(rdir) / f["selection"]).read_text(encoding="utf-8"))
    by = {}
    for k in ("stage1", "stage2"):
        for it in json.loads((Path(rdir) / f[k]).read_text(encoding="utf-8"))["items"]:
            by[it["id"]] = it["title"]
    ids = sel["anchor_ids"] + sel["measured_ids"]
    return [{"id": i, "title": by[i]} for i in ids]


def build_requests(titles, provider, cfg):
    m = cfg["model"]
    return [{"index": n, "id": t["id"], "provider": provider, "body_sha256": V.body_sha256(V.BUILDERS[provider](t["title"], m)),
             "body": V.BUILDERS[provider](t["title"], m)} for n, t in enumerate(titles)]


def verify_requests(rows, titles, provider, cfg):
    errs, m = [], cfg["model"]
    if [r["id"] for r in rows] != [t["id"] for t in titles]:
        errs.append("a kérések azonosítói vagy sorrendje nem egyezik a címekkel")
    for r, t in zip(rows, titles):
        errs += [f"{r['id']}: {e}" for e in V.check_body(provider, r["body"], t["title"], m)]
        if r["body_sha256"] != V.body_sha256(r["body"]):
            errs.append(f"{r['id']}: a hash nem egyezik")
        if r.get("provider") != provider:
            errs.append(f"{r['id']}: a szolgáltató-jelölés hibás")
    return errs


# ---------------------------------------------------------------- állapot és fájlok

def _jl_read(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()] if Path(p).exists() else []


def _jl_append(p, obj):
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _write_state(path, st):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


CSV_FIELDS = ["run_id", "provider", "model", "id", "status", "failure", "total", "scaled"] + [f"{s}_{p}" for s in P.SIGNALS for p in ("score", "reason", "span")]


def _write_results(run_dir, st, titles, scores, final_status):
    rows = []
    for t in titles:
        s = scores.get(t["id"])
        base = {"run_id": st["run_id"], "provider": st["provider"], "model": (s or {}).get("model_returned") or st["model"], "id": t["id"]}
        if s:
            r = {**base, "status": "ok", "failure": "", "total": s["total"], "scaled": s["scaled"]}
            for k, v in s["signals"].items():
                r.update({f"{k}_score": v["score"], f"{k}_reason": v["reason"], f"{k}_span": v["span"]})
        elif t["id"] in st["failed"]:
            r = {**base, "status": st["failed"][t["id"]]["kind"], "failure": st["failed"][t["id"]]["detail"]}
        else:
            r = {**base, "status": "pending", "failure": ""}
        rows.append(r)
    p = run_dir / "results.csv"
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, restval="", extrasaction="raise")
        w.writeheader()
        w.writerows(rows)
    log = _jl_read(run_dir / "log.jsonl")
    tok = {}
    for l in log:
        for k, v in (l.get("usage") or {}).items():
            tok[k] = tok.get(k, 0) + v
    kinds = {}
    for l in log:
        kinds[l["outcome"]] = kinds.get(l["outcome"], 0) + 1
    summary = {"run_id": st["run_id"], "workload": "measurement", "status": final_status, "provider": st["provider"], "providers_used": [st["provider"]], "model_requested": st["model"],
               "models_returned": sorted({l["model_returned"] for l in log if l.get("model_returned")}), "failover_allowed": False, "key_alias": st["key_alias"],
               "prompt_sha256": st["prompt_sha256"], "schema_sha256": st["schema_sha256"], "n_titles": len(titles), "n_ok": len(scores),
               "n_failed": sum(1 for t in titles if t["id"] in st["failed"] and t["id"] not in scores), "n_pending": sum(1 for r in rows if r["status"] == "pending"),
               "requests_total": len(log), "outcomes": kinds, "tokens": tok, "resume_after_utc": st.get("resume_after_utc"), "probes": st["probes"], "quota_stops": st["quota_stops"],
               "invocations": st["invocations"]}
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


# ---------------------------------------------------------------- futtatás

def run_measurement(titles, provider, transport, cfg, rdir, run_name, model, now=_utcnow, sleep=_time.sleep, monotonic=_time.monotonic):
    check_policy(cfg)
    m, run_cfg = cfg["model"], cfg["model"]["run"]
    if provider not in m["providers"]:
        raise RunRefused(f"ismeretlen szolgáltató: {provider}")
    pcfg = m["providers"][provider]
    man = require_freeze(rdir, cfg)                                                  # lezárási kapu: nélküle nem indul
    expected = man["anchor_ids"] + man["measured_ids"]
    if sorted(t["id"] for t in titles) != sorted(expected):
        raise RunRefused("a címek azonosítói nem egyeznek a lezárt jegyzékkel")
    for t in titles:
        V.check_text(t["title"])
    run_dir = Path(rdir) / cfg["files"]["model_runs_dir"] / run_name
    check_write(run_dir / "x", rdir)
    run_dir.mkdir(parents=True, exist_ok=True)
    sp, lp, qp, scp = run_dir / "state.json", run_dir / "log.jsonl", run_dir / "quota_stops.jsonl", run_dir / "scores.jsonl"
    p_sha, s_sha = V.sha256_text(P.SYSTEM_INSTRUCTION), V.sha256_text(P.canonical_json(P.gemini_schema(m["max_points_per_signal"])))
    t0 = now()
    if sp.exists():
        st = json.loads(sp.read_text(encoding="utf-8"))
        if (st["provider"], st["model"], st["prompt_sha256"]) != (provider, model, p_sha) or st["ids"] != [t["id"] for t in titles]:
            raise RunRefused("a folytatás szolgáltatója, modellje, promptja vagy címlistája eltér az induló futásétól")
        if st["status"] == "complete":
            return _write_results(run_dir, st, titles, {s["id"]: s for s in _jl_read(scp)}, "complete")
        ra = st.get("resume_after_utc")
        if ra and Q.as_utc(t0) < Q.parse_iso(ra):
            raise RunRefused(f"a folytatás ideje még nem jött el: {ra}")
        day = Q.quota_day_key(pcfg, t0)
        if sum(1 for p in st["probes"] if p["quota_day"] == day) >= run_cfg["probes_per_quota_day"]:
            raise RunRefused(f"erre a kvótanapra ({day}) elfogyott a napi {run_cfg['probes_per_quota_day']} próba")
        probing = bool(st.get("probe_pending"))
    else:
        st = {"run_id": f"{run_name}", "provider": provider, "model": model, "key_alias": pcfg["key_alias"], "prompt_sha256": p_sha, "schema_sha256": s_sha, "ids": [t["id"] for t in titles],
              "status": "running", "resume_after_utc": None, "probes": [], "quota_stops": 0, "probe_pending": False, "failed": {}, "invocations": 0}
        probing = False
    st["invocations"] += 1
    st["status"], st["resume_after_utc"] = "running", None
    scores = {s["id"]: s for s in _jl_read(scp)}
    terminal = {"invalid", "empty", "truncated", "blocked"}
    queue = [t for t in titles if t["id"] not in scores and not (t["id"] in st["failed"] and st["failed"][t["id"]]["kind"] in terminal)]
    sent, last, consec_fail, pauses, requeued = [0], [None], [0], [0], set()

    def log(t, attempt, out, status, latency, probe):
        _jl_append(lp, {"utc": Q.iso(now()), "run_id": st["run_id"], "workload": "measurement", "provider": provider, "model_requested": model,
                        "model_returned": out.model_returned, "key_alias": pcfg["key_alias"], "id": t["id"], "attempt": attempt, "probe": probe, "http_status": status,
                        "outcome": out.kind, "detail": V.sanitize(out.detail, 200), "usage": out.usage, "latency_ms": latency, "retry_after_s": out.retry_after,
                        "finish_reason": out.finish_reason})

    def stop(status, resume_at=None, evidence=None):
        st["status"], st["resume_after_utc"] = status, (Q.iso(resume_at) if resume_at else None)
        _write_state(sp, st)
        return _write_results(run_dir, st, titles, scores, status)

    def send(t, attempt, probe):
        body = V.BUILDERS[provider](t["title"], m)
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
            out = V.parse_response(provider, raw.status, raw.text, t["title"], m, raw.retry_after)
            status, latency = raw.status, raw.latency_ms or int((monotonic() - started) * 1000)
        except TransportTimeout:
            out, status, latency = V.Outcome("transient", "időtúllépés"), None, None
        except ConnectionError:
            out, status, latency = V.Outcome("transient", "hálózati hiba"), None, None
        log(t, attempt, out, status, latency, probe)
        return out

    i = 0
    while i < len(queue):
        t = queue[i]
        i += 1
        tries = {"invalid": 0, "transient": 0}
        attempt = 0
        while True:
            attempt += 1
            probe = probing
            if probe:
                st["probes"].append({"utc": Q.iso(now()), "quota_day": Q.quota_day_key(pcfg, now())})
            out = send(t, attempt, probe)
            if out is None:
                return stop("stopped_request_cap")
            if out.kind != "quota_day" and probing:
                probing = False
                st["probe_pending"] = False
            if out.kind == "ok":
                rec = {"id": t["id"], "provider": provider, "model_requested": model, "model_returned": out.model_returned, "utc": Q.iso(now()), **out.score}
                _jl_append(scp, rec)
                scores[t["id"]] = rec
                st["failed"].pop(t["id"], None)
                consec_fail[0] = 0
                break
            if out.kind == "quota_day":
                fallback = timedelta(minutes=run_cfg["fallback_probe_wait_min"])
                reset = Q.resume_after_utc(pcfg, now(), run_cfg["resume_margin_min"])
                if probe:                                                              # sikertelen próba: rövid várakozás, legfeljebb a következő visszaállásig
                    wait = timedelta(seconds=out.retry_after) if out.retry_after else fallback
                    resume_at = min(Q.as_utc(now()) + wait + timedelta(minutes=run_cfg["resume_margin_min"]), reset)
                else:
                    resume_at = reset
                st["quota_stops"] += 1
                st["probe_pending"] = True
                _jl_append(qp, {"utc": Q.iso(now()), "run_id": st["run_id"], "provider": provider, "model": model, "probe": probe, "evidence": V.sanitize(out.detail, 200),
                                "provider_hint_s": out.retry_after, "done": len(scores), "pending": len(titles) - len(scores) - sum(1 for k, v in st["failed"].items() if v["kind"] in terminal),
                                "resume_after_utc": Q.iso(resume_at), "failover": "nincs (mérési futás)"})
                return stop("stopped_quota", resume_at)
            if out.kind in ("fatal", "billing"):
                _jl_append(qp, {"utc": Q.iso(now()), "run_id": st["run_id"], "provider": provider, "kind": out.kind, "evidence": V.sanitize(out.detail, 200), "failover": "nincs"})
                return stop("stopped_billing" if out.kind == "billing" else "stopped_fatal")
            if out.kind in ("blocked", "truncated"):
                st["failed"][t["id"]] = {"kind": out.kind, "detail": V.sanitize(out.detail, 200)}
                break
            if out.kind in ("invalid", "empty"):
                tries["invalid"] += 1
                if tries["invalid"] > run_cfg["invalid_retries"]:
                    st["failed"][t["id"]] = {"kind": out.kind, "detail": V.sanitize(out.detail, 200)}
                    break
                continue
            if out.kind == "quota_minute":
                if out.retry_after and out.retry_after > run_cfg["max_wait_s"]:
                    return stop("stopped_long_wait", Q.as_utc(now()) + timedelta(seconds=out.retry_after, minutes=run_cfg["resume_margin_min"]))
                if tries["transient"] >= run_cfg["max_retries"]:
                    st["failed"][t["id"]] = {"kind": "transient_failed", "detail": "percenkénti korlát: az újrapróbák elfogytak"}
                    consec_fail[0] += 1
                    break
                wait = max(out.retry_after or 0.0, run_cfg["backoff_s"][min(tries["transient"], len(run_cfg["backoff_s"]) - 1)])
                tries["transient"] += 1
                sleep(min(wait, run_cfg["max_wait_s"]))
                continue
            if out.kind == "transient":
                if tries["transient"] >= run_cfg["max_retries"]:
                    st["failed"][t["id"]] = {"kind": "transient_failed", "detail": V.sanitize(out.detail, 200)}
                    consec_fail[0] += 1
                    break
                sleep(run_cfg["backoff_s"][min(tries["transient"], len(run_cfg["backoff_s"]) - 1)])
                tries["transient"] += 1
                continue
            raise RuntimeError(f"ismeretlen kimenetel: {out.kind}")
        if t["id"] in st["failed"] and st["failed"][t["id"]]["kind"] == "transient_failed" and t["id"] not in requeued:
            requeued.add(t["id"])
            queue.append(t)                                                            # a végén még egyszer sorra kerül
        if consec_fail[0] >= run_cfg["outage_consecutive"]:
            pauses[0] += 1
            if pauses[0] > run_cfg["outage_pauses_max"]:
                return stop("stopped_outage")
            sleep(run_cfg["transient_pause_s"])
            consec_fail[0] = 0
        _write_state(sp, st)
    pending = [t for t in titles if t["id"] not in scores and t["id"] not in st["failed"]]
    return stop("complete" if not pending and not any(v["kind"] == "transient_failed" for v in st["failed"].values()) else "incomplete")
