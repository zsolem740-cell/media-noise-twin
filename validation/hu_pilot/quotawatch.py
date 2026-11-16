"""Kvótafigyelő: csak olvasó. Egy modellfuttatás mappájából (state.json, log.jsonl, scores.jsonl, quota_stops.jsonl) megmondja, hol tart a futás, mikor folytatható,
hány próba maradt a kvótanapra, és megszegett-e a CLAUDE.md valamelyik futási szabályát (szolgáltatóváltás, korai folytatás, nem próbával induló folytatás,
több mint napi 3 próba, kész cím újraküldése, hiányzó naplómező, kulcs a naplóban). Nem indít futást, nem hív hálózatot, nem ír semmit.

Parancssor: python -m validation.hu_pilot.quotawatch RUN_MAPPA [--now 2026-11-15T08:00:00Z] [--json]
Kilépési kód: 0 nincs szabálysértés, 1 szabálysértés van, 2 a futás nem olvasható."""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import quota as Q
from .paths import load_config

REQUIRED_LOG_FIELDS = ("provider", "model_requested", "outcome", "usage")
SECRET_RES = [re.compile(p) for p in (r"AIza[0-9A-Za-z\-_]{20,}", r"gsk_[0-9A-Za-z]{20,}", r"(?<![0-9A-Za-z])sk-[0-9A-Za-z\-_]{20,}", r"gh[pousr]_[0-9A-Za-z]{20,}")]
TERMINAL = {"invalid", "empty", "truncated", "blocked"}


def _jl(path):
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_run(run_dir):
    d = Path(run_dir)
    sp = d / "state.json"
    if not sp.exists():
        raise FileNotFoundError(f"nincs state.json: {d}")
    return {"state": json.loads(sp.read_text(encoding="utf-8")), "scores": _jl(d / "scores.jsonl"), "log": _jl(d / "log.jsonl"), "stops": _jl(d / "quota_stops.jsonl"),
            "log_text": (d / "log.jsonl").read_text(encoding="utf-8") if (d / "log.jsonl").exists() else ""}


def violations(run, run_cfg):
    st, log, stops = run["state"], run["log"], run["stops"]
    out = []

    def bad(rule, msg, where=""):
        out.append({"rule": rule, "where": where, "msg": msg})

    for i, r in enumerate(log, 1):
        miss = [k for k in REQUIRED_LOG_FIELDS if k not in r]
        if miss:
            bad("naplomezo", f"hiányzó kötelező naplómező: {', '.join(miss)}", f"log.jsonl:{i}")
        if r.get("provider") not in (None, st["provider"]):
            bad("szolgaltatovaltas", f"a napló szolgáltatója ({r.get('provider')}) eltér a futásétól ({st['provider']}): mérési futáson tilos", f"log.jsonl:{i}")
    for r in run["scores"]:
        if r.get("provider") not in (None, st["provider"]):
            bad("szolgaltatovaltas", f"a pontszám szolgáltatója eltér a futásétól: {r.get('id')}", "scores.jsonl")
    per_day = {}
    for p in st.get("probes", []):
        per_day[p["quota_day"]] = per_day.get(p["quota_day"], 0) + 1
    for day, n in per_day.items():
        if n > run_cfg["probes_per_quota_day"]:
            bad("probaplafon", f"{day}: {n} próba, a napi plafon {run_cfg['probes_per_quota_day']}", "state.json")
    done = set()
    for i, r in enumerate(log, 1):                                      # kész cím újraküldése tilos
        cid = r.get("id")
        if cid in done:
            bad("ujrakuldes", f"a cím ({cid}) már kész volt, mégis újra ki lett küldve", f"log.jsonl:{i}")
        if r.get("outcome") == "ok":
            done.add(cid)
    for i, r in enumerate(log[:-1], 1):                                 # a kvótamegállás utáni első kérés próba
        if r.get("outcome") == "quota_day" and log[i].get("probe") is not True and log[i].get("outcome") is not None and log[i].get("utc", "") > r.get("utc", ""):
            bad("nem-proba", "a kvótamegállás utáni első kérés nem volt próbakérés", f"log.jsonl:{i + 1}")
    for s in stops:                                                     # korai folytatás
        ra, su = s.get("resume_after_utc"), s.get("utc")
        if not ra or not su:
            continue
        for i, r in enumerate(log, 1):
            if su < r.get("utc", "") < ra:
                bad("korai-folytatas", f"a megállás ({su}) és a folytatási idő ({ra}) között kérés ment ki", f"log.jsonl:{i}")
    if any(p.search(run["log_text"]) for p in SECRET_RES):
        bad("titok", "kulcsszerű minta a naplóban (az érték nincs kiírva)", "log.jsonl")
    return out


def assess(run, cfg, now):
    st = run["state"]
    m = cfg["model"]
    pcfg, run_cfg = m["providers"][st["provider"]], m["run"]
    now = Q.as_utc(now)
    scores = {s["id"] for s in run["scores"]}
    failed_terminal = {i for i, v in st.get("failed", {}).items() if v["kind"] in TERMINAL and i not in scores}
    total, done = len(st["ids"]), len(scores)
    pending = total - done - len(failed_terminal)
    day = Q.quota_day_key(pcfg, now)
    used = sum(1 for p in st.get("probes", []) if p["quota_day"] == day)
    left = max(0, run_cfg["probes_per_quota_day"] - used)
    ra = st.get("resume_after_utc")
    remaining = max(0, int((Q.parse_iso(ra) - now).total_seconds())) if ra else 0
    status = st["status"]
    next_ok = Q.resume_after_utc(pcfg, now, run_cfg["resume_margin_min"])
    advice = []
    if status == "complete":
        advice.append("A futás kész, nincs teendő.")
    elif status == "stopped_quota":
        if remaining > 0:
            advice.append(f"Várj: a folytatás {ra} után lehetséges (még {remaining // 60} perc).")
        elif left == 0:
            advice.append(f"Erre a kvótanapra ({day}) elfogyott a napi {run_cfg['probes_per_quota_day']} próba: a következő kvótanap és +{run_cfg['resume_margin_min']} perc után ({Q.iso(next_ok)}) folytasd.")
        else:
            advice.append(f"Folytatható. Az első kérés próbakérés lesz; ugyanazzal a futásnévvel és szolgáltatóval ({st['provider']}) indítsd; a kész címek nem mennek ki újra. {left} próba maradt ma. A futtatást csak a felhasználó indíthatja.")
    elif status in ("stopped_billing", "stopped_fatal"):
        advice.append("A futás számlázási vagy végzetes hiba miatt állt meg: automatikusan nem folytatható. Szolgáltatót váltani és fizetős csomagra váltani tilos; a felhasználó dönt.")
    elif status == "stopped_request_cap":
        advice.append("A kérésszám-plafon miatt állt meg: a felhasználó döntsön a folytatásról.")
    elif status == "running":
        advice.append("A futás állapota „fut”: ha nem fut valóban (megszakadt), a folytatás előtt ellenőrizd az Actions-futást.")
    else:
        advice.append(f"A futás állapota: {status}.")
    v = violations(run, run_cfg)
    return {"run_id": st["run_id"], "provider": st["provider"], "model": st["model"], "status": status, "total": total, "done": done, "failed_terminal": len(failed_terminal), "pending": pending,
            "resume_after_utc": ra, "remaining_s": remaining, "can_resume_now": status == "stopped_quota" and remaining == 0 and left > 0,
            "quota_day": day, "probes_today": used, "probes_left_today": left, "next_reset_plus_margin_utc": Q.iso(next_ok), "quota_stops": st.get("quota_stops", 0),
            "advice": advice, "violations": v, "verdict": "SZABÁLYSÉRTÉS" if v else "RENDBEN"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir")
    ap.add_argument("--now", help="idő UTC-ben, pl. 2026-11-15T08:00:00Z (alapból most)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        run = load_run(a.run_dir)
    except (FileNotFoundError, ValueError, KeyError) as e:
        print(f"NEM OLVASHATÓ: {e}", file=sys.stderr)
        return 2
    now = Q.parse_iso(a.now) if a.now else datetime.now(timezone.utc)
    rep = assess(run, load_config(), now)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print(f"=== KVÓTAFIGYELŐ: {rep['run_id']} ({rep['provider']}, {rep['model']}) ===")
        print(f"állapot: {rep['status']}; kész {rep['done']} / {rep['total']}, végleg hibás {rep['failed_terminal']}, hátra {rep['pending']}")
        print(f"kvótanap: {rep['quota_day']}; próba ma: {rep['probes_today']}, maradt: {rep['probes_left_today']}; kvótamegállás eddig: {rep['quota_stops']}")
        for t in rep["advice"]:
            print("→", t)
        for x in rep["violations"]:
            print(f"[SZABÁLYSÉRTÉS] {x['rule']} {x['where']}: {x['msg']}")
        print(rep["verdict"])
    return 1 if rep["violations"] else 0


if __name__ == "__main__":
    sys.exit(main())
