"""A pilot teljes láncának egybefüggő próbája HAMIS átvitellel: választás, csomagolás, szavazás, elemzés, lezárás, modellkérések ellenőrzése, mérési futás (kvótamegállással és folytatással).
Hálózat, kulcs és modell nélkül. Ez az illesztési hibákat fogja meg, amelyeket a részenkénti tesztek nem látnak."""
import csv
import json
from pathlib import Path
from datetime import datetime, timezone

import pytest

from validation.hu_pilot import modelrun as mr
from validation.hu_pilot import run
from validation.hu_pilot.freeze import NotFrozen
from .test_hu_pilot import write_exports, KIND
from .test_modelrun import CANARY, Clock, GEM, GRQ, Script, jl, ok_raw, post_of, quota_day
from .test_packaging import make_app

UTC = timezone.utc


@pytest.fixture
def chain(tmp_path, cfg, feed_path):
    """A lánc előkészítő fele, lépésenként, ahogy a runbook írja: select -> package 1/2 -> szavazás -> analyze -> adjudication -> freeze -> dryrun."""
    res = tmp_path / "res"
    log = {}
    log["select"] = run.do_select(cfg, feed_path, base=res)
    sel = json.loads((res / "selection.json").read_text(encoding="utf-8"))
    app = make_app(tmp_path)
    log["package"] = [run.do_package(cfg, app, s, "abc123", base=res) for s in (1, 2)]
    ids = sel["anchor_ids"] + sel["measured_ids"]
    a = [KIND[(n * 7) % 3] for n in range(len(ids))]
    exp = write_exports(tmp_path, {"A": list(zip(ids, a)), "B": list(zip(ids, a)), "C": list(zip(ids, a))})
    log["analyze"] = run.do_analyze(cfg, [exp], base=res)
    log["adjudication"] = run.do_adjudication(cfg, [exp], feed_path, base=res)
    with pytest.raises(NotFrozen):                                            # a lezárás előtt a modell nem indulhat
        mr.run_measurement(mr.load_titles(res, cfg), "gemini", Script("gemini"), cfg, res, "korai", GEM)
    log["freeze"] = run.do_freeze(cfg, [exp], base=res)
    log["dryrun"] = {p: run.do_model_dryrun(cfg, p, base=res) for p in ("gemini", "groq")}
    return res, sel, log, mr.load_titles(res, cfg)


def run_model(chain, cfg, provider, steps, name, t):
    res, sel, log, titles = chain
    tr = Script(provider)
    tr.steps = list(steps)
    clock = Clock(t)
    model = GEM if provider == "gemini" else GRQ
    rep = mr.run_measurement(titles, provider, tr, cfg, res, name, model, now=clock.now, sleep=clock.sleep, monotonic=clock.monotonic)
    return rep, tr


def test_the_preparation_chain_hands_consistent_data_from_step_to_step(chain):
    res, sel, log, titles = chain
    assert log["select"]["anchors"] == 20 and log["select"]["measured"] == 30
    assert [p["status"] for p in log["package"]] == ["OK", "OK"] and [p["titles"] for p in log["package"]] == [20, 30]
    assert log["analyze"]["gate"]["decision"] == "atment" and log["adjudication"] == {"adjudication_titles": 0}
    assert log["freeze"]["anchor_ids"] == sorted(sel["anchor_ids"]) and log["freeze"]["measured_ids"] == sorted(sel["measured_ids"])
    assert [t["id"] for t in titles] == sel["anchor_ids"] + sel["measured_ids"]
    for p in ("gemini", "groq"):
        assert log["dryrun"][p]["status"] == "OK" and log["dryrun"][p]["n_requests"] == 50 and log["dryrun"][p]["errors"] == []
    # a csomagok és a modell ugyanazt az 50 címet használják, szövegre is
    pk = {i["title"] for s in (1, 2) for i in json.loads((res / "deploy" / f"stage{s}" / "atm_history.json").read_text(encoding="utf-8"))["items"]}
    assert pk == {t["title"] for t in titles}
    # a referencia pontosan a 30 mérési címre szól, és mind szerepel a lezárt jegyzékben
    ref = list(csv.DictReader((res / "human_reference.csv").open(encoding="utf-8", newline="")))
    assert len(ref) == 30 and {r["id"] for r in ref} == set(sel["measured_ids"])


def test_both_providers_measure_the_same_titles_with_the_same_prompt_and_the_run_is_reproducible(chain, cfg):
    t = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)
    rg, tg = run_model(chain, cfg, "gemini", [], "g1", t)
    rq, tq = run_model(chain, cfg, "groq", [], "q1", t)
    assert rg["status"] == rq["status"] == "complete" and rg["n_ok"] == rq["n_ok"] == 50
    assert rg["prompt_sha256"] == rq["prompt_sha256"] and rg["schema_sha256"] == rq["schema_sha256"]
    assert [post_of(b) for _, b in tg.calls] == [post_of(b) for _, b in tq.calls] == [x["title"] for x in chain[3]]
    assert rg["providers_used"] == ["gemini"] and rq["providers_used"] == ["groq"] and rg["failover_allowed"] is False
    again, _ = run_model(chain, cfg, "gemini", [], "g2", t)
    a = (chain[0] / "model_runs/g1/results.csv").read_text(encoding="utf-8").replace("g1", "X")
    b = (chain[0] / "model_runs/g2/results.csv").read_text(encoding="utf-8").replace("g2", "X")
    assert a == b


def test_daily_quota_stop_and_resume_over_the_whole_chain(chain, cfg):
    res, sel, log, titles = chain
    t0 = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)
    first, tr1 = run_model(chain, cfg, "gemini", [lambda b: ok_raw("gemini", b)] * 12 + [quota_day()], "kv", t0)
    assert first["status"] == "stopped_quota" and first["n_ok"] == 12 and first["n_pending"] == 38 and first["resume_after_utc"] == "2026-11-15T08:05:00Z"
    sent = [post_of(b) for _, b in tr1.calls[:12]]
    # a folytatás a visszaállás + 5 perc előtt tilos, a másik szolgáltató nem veszi át a munkát
    with pytest.raises(mr.RunRefused, match="még nem jött el"):
        run_model(chain, cfg, "gemini", [], "kv", datetime(2026, 11, 15, 8, 4, 59, tzinfo=UTC))
    with pytest.raises(mr.RunRefused, match="eltér"):
        run_model(chain, cfg, "groq", [], "kv", datetime(2026, 11, 15, 8, 5, tzinfo=UTC))
    second, tr2 = run_model(chain, cfg, "gemini", [], "kv", datetime(2026, 11, 15, 8, 5, tzinfo=UTC))
    assert second["status"] == "complete" and second["n_ok"] == 50 and len(tr2.calls) == 38
    assert not set(sent) & {post_of(b) for _, b in tr2.calls}
    assert len(second["probes"]) == 1 and second["quota_stops"] == 1
    rows = list(csv.DictReader((res / "model_runs/kv/results.csv").open(encoding="utf-8", newline="")))
    assert [r["id"] for r in rows] == [x["id"] for x in titles] and {r["status"] for r in rows} == {"ok"}
    # a modell eredménye és az emberi referencia ugyanazokra a mérési azonosítókra illeszthető
    ref_ids = {r["id"] for r in csv.DictReader((res / "human_reference.csv").open(encoding="utf-8", newline=""))}
    assert ref_ids <= {r["id"] for r in rows if r["status"] == "ok"}
    # minden naplósor mutatja a szolgáltatót, a modellt, a kimenetelt és a tokeneket
    for l in jl(res / "model_runs/kv/log.jsonl"):
        assert l["provider"] == "gemini" and l["model_requested"] == GEM and l["outcome"] and "usage" in l


def test_no_secret_and_the_real_results_dir_untouched_after_the_whole_chain(chain, cfg):
    res, sel, log, titles = chain
    real = Path(run.__file__).resolve().parent / cfg["results_dir"]
    before = sorted(str(p) for p in real.rglob("*")) if real.exists() else []
    t0 = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)
    run_model(chain, cfg, "gemini", [lambda b: ok_raw("gemini", b)] * 3 + [quota_day()], "titok", t0)
    blob = "".join(p.read_text(encoding="utf-8", errors="replace") for p in res.rglob("*") if p.is_file() and p.suffix not in (".zip", ".png"))
    assert CANARY not in blob and "AIza" not in blob
    assert (sorted(str(p) for p in real.rglob("*")) if real.exists() else []) == before
