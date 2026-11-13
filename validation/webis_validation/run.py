"""A Webis-validáció parancssora (csak olvasó mód; teljes AI-futtatás nincs benne).

  python -m validation.webis_validation.run verify ARCHÍVUM.zip      MD5 és méret az ismert értékekkel
  python -m validation.webis_validation.run inspect                  mezők, annotátorszám, kizárások, eloszlás (a data/ mappából)
  python -m validation.webis_validation.run sample                   rétegzett minta → results/sample_meta.json, results/model_inputs.jsonl (csak id + cím)
  python -m validation.webis_validation.run evaluate SCORES.jsonl    kiértékelés → results/report.json
  python -m validation.webis_validation.run smoke                    szintetikus adatokon végigfuttatja a láncot próba-pontozóval (tmp mappában)
  python -m validation.webis_validation.run gemini-dryrun            a 20 címes Gemini smoke test kéréseinek előállítása és ellenőrzése, HÁLÓZAT NÉLKÜL (results/smoke_gemini/)
  python -m validation.webis_validation.run groq-dryrun              a Groq-ág 4 csomagja (5 cím/kérés) a MEGLÉVŐ 20 címre, HÁLÓZAT ÉS KULCS NÉLKÜL (results/groq/)
  python -m validation.webis_validation.run groq-dryrun-v2 / groq-run-v2 --go   ugyanez a szigorított (v2) prompttal; külön *_v2 fájlokba ír, a v1 fájlokat nem érinti
  python -m validation.webis_validation.run groq-run --go            a 20 cím valódi Groq-futtatása; kell hozzá a GROQ_API_KEY környezeti változó és az api.groq.com engedélyezése"""
import json
import sys
import tempfile
from pathlib import Path

from . import evaluate as ev
from . import gemini_request, gemini_smoke, groq_request, groq_run, loader, sample, scoring, synthetic
from .isolation import MODULE_DIR, check_read, check_write, load_config


def _dirs(cfg):
    return MODULE_DIR / cfg["paths"]["data_dir"], MODULE_DIR / cfg["paths"]["results_dir"]


def _write_json(path, obj, results_dir):
    p = check_write(path, results_dir)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=list), encoding="utf-8")
    return p


def _load(cfg, data_dir):
    return loader.load(data_dir / cfg["files"]["instances"], data_dir / cfg["files"]["truth"], cfg, data_dir)


def do_sample(cfg, data_dir, results_dir):
    records, lrep = _load(cfg, data_dir)
    picked, srep = sample.stratified_sample(records, cfg)
    srep["corpus_distribution"] = sample.distribution(records, cfg["sample"]["strata"])
    _write_json(results_dir / "sample_meta.json", {"loader": lrep, "sample": srep}, results_dir)
    lines = "\n".join(json.dumps(scoring.build_model_input(r), ensure_ascii=False) for r in picked) + "\n"
    check_write(results_dir / "model_inputs.jsonl", results_dir).write_text(lines, encoding="utf-8")
    return lrep, srep


def do_evaluate(cfg, data_dir, results_dir, scores_path):
    records, _ = _load(cfg, data_dir)
    meta = json.loads(check_read(results_dir / "sample_meta.json", results_dir).read_text(encoding="utf-8"))
    ids = set(meta["sample"]["ids"])
    chosen = [r for r in records if r.id in ids]
    by_id = {r.id: r for r in chosen}
    scores, bad = [], []
    for line in check_read(scores_path, results_dir).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        s = json.loads(line)
        r = by_id.get(s.get("id"))
        errs = scoring.validate_score(s, r.text, cfg) if r else ["ismeretlen azonosító"]
        (bad if errs else scores).append({"id": s.get("id"), "errors": errs} if errs else s)
    rep = ev.evaluate(chosen, scores, cfg)
    rep["invalid_scores"] = bad
    _write_json(results_dir / "report.json", rep, results_dir)
    return rep


def do_gemini_dryrun(cfg, data_dir, results_dir):
    """20 kérés (rétegenként 5) előállítása a 250 elemű mintából, kulcs és hálózat nélkül; a fájlt újraolvasva független ellenőrzés."""
    records, _ = _load(cfg, data_dir)
    meta = json.loads(check_read(results_dir / "sample_meta.json", results_dir).read_text(encoding="utf-8"))
    order, stratum = gemini_smoke.select_smoke(records, meta["sample"]["ids"], cfg)
    by = {r.id: r for r in records}
    inputs = [{"id": rid, "postText": by[rid].text} for rid in order]
    inst = {str(r.get("id")): r for r in loader.read_jsonl(check_read(data_dir / cfg["files"]["instances"], data_dir))}
    truth = {str(r.get("id")): r for r in loader.read_jsonl(check_read(data_dir / cfg["files"]["truth"], data_dir))}
    leaks = {rid: gemini_smoke.leak_strings_for(inst[rid], truth[rid]) for rid in order}
    rows, build_errors = gemini_smoke.build_dryrun(inputs, cfg, leaks)
    out = results_dir / "smoke_gemini"
    report = {"n_selected": len(inputs), "n_requests": len(rows), "build_errors": build_errors, "no_network": True, "api_key_used": False,
              "model": None, "model_note": "a modell neve nincs a kérés törzsében; a modelllista (külön jóváhagyás) után dől el",
              "model_candidates": cfg["gemini"]["model_candidates"], "tier": cfg["gemini"]["tier"],
              "prompt_sha256": gemini_request.text_sha256(gemini_request.SYSTEM_INSTRUCTION),
              "schema_sha256": gemini_request.text_sha256(gemini_request.canonical_json(gemini_request.response_schema(cfg))),
              "thinking_config": cfg["gemini"]["generation"].get("thinking_config"),
              "strata_counts": {name: sum(1 for r in rows if stratum[r["id"]] == name) for name in sorted(set(stratum.values()))}}
    gemini_smoke.write_dryrun(out, inputs, rows, stratum, report, results_dir)
    rows2 = gemini_smoke.read_jsonl_file(out / "requests_dryrun.jsonl", results_dir)
    inputs2 = gemini_smoke.read_jsonl_file(out / "selected_inputs.jsonl", results_dir)
    verification = gemini_smoke.verify_dryrun_rows(rows2, inputs2, cfg, stratum, leaks)
    report["verification_errors"] = verification
    report["status"] = "OK" if not verification and not build_errors else "HIBA"
    check_write(out / "dryrun_check.json", results_dir).write_text(json.dumps({**report, "strata_of": stratum}, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def _groq_inputs(cfg, results_dir):
    """A MEGLÉVŐ 20 cím: a Gemini smoke test kiválasztott bemenete (csak id + postText), csak olvasva; a Gemini-fájlok nem módosulnak."""
    rows = gemini_smoke.read_jsonl_file(results_dir / "smoke_gemini" / "selected_inputs.jsonl", results_dir)
    return [{"id": r["id"], "postText": r["postText"]} for r in rows]


def groq_v2_cfg(cfg):
    """A szigorított prompt (v2) beállítása: csak a prompt és a kimeneti fájlnevek (*_v2) különböznek; a csomagolás, a séma és a hibakezelés ugyanaz."""
    import copy
    c = copy.deepcopy(cfg)
    c["groq"]["prompt_version"] = "v2"
    c["groq"]["paths"] = dict(cfg["groq"]["paths_v2"])
    return c


def do_groq_dryrun(cfg, data_dir, results_dir):
    """4 csomag (5 cím/kérés) kulcs és hálózat nélkül; a fájlt újraolvasva független ellenőrzés."""
    inputs = _groq_inputs(cfg, results_dir)
    inst = {str(r.get("id")): r for r in loader.read_jsonl(check_read(data_dir / cfg["files"]["instances"], data_dir))}
    truth = {str(r.get("id")): r for r in loader.read_jsonl(check_read(data_dir / cfg["files"]["truth"], data_dir))}
    leaks = {x["id"]: gemini_smoke.leak_strings_for(inst[x["id"]], truth[x["id"]]) for x in inputs}
    rows, build_errors = groq_run.build_dryrun(inputs, cfg, leaks)
    out = results_dir / cfg["groq"]["paths"]["subdir"]
    out.mkdir(parents=True, exist_ok=True)
    p = cfg["groq"]["paths"]
    check_write(out / p["dryrun"], results_dir).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    rows2 = gemini_smoke.read_jsonl_file(out / p["dryrun"], results_dir)
    verification = groq_run.verify_dryrun_rows(rows2, inputs, cfg, leaks)
    report = {"n_titles": len(inputs), "n_requests": len(rows), "batch_sizes": [len(r["ids"]) for r in rows2], "model": cfg["groq"]["model"], "no_network": True,
              "api_key_used": False, "build_errors": build_errors, "verification_errors": verification,
              "prompt_version": cfg["groq"].get("prompt_version", "v1"), "prompt_sha256": gemini_request.text_sha256(groq_request.system_prompt(cfg)),
              "gemini_rules_prefix_sha256": gemini_request.text_sha256(gemini_request.SYSTEM_INSTRUCTION),
              "rules_identical_to_gemini": groq_request.system_prompt(cfg).startswith(gemini_request.SYSTEM_INSTRUCTION),
              "schema_sha256": gemini_request.text_sha256(gemini_request.canonical_json(groq_request.response_format(cfg))),
              "generation": cfg["groq"]["generation"], "status": "OK" if not verification and not build_errors else "HIBA"}
    check_write(out / p["dryrun_check"], results_dir).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def do_groq_run(cfg, results_dir):
    """Valódi futás: a hálózati fájl csak itt töltődik be. Kulcs nélkül még a kérés előtt leáll."""
    from . import groq_transport
    inputs = _groq_inputs(cfg, results_dir)
    transport = groq_transport.make_transport(cfg)
    return groq_run.run_groq(inputs, transport, cfg, results_dir / cfg["groq"]["paths"]["subdir"], results_dir)


def do_smoke():
    cfg = load_config()
    cfg["sample"] = dict(cfg["sample"], size=60, strata=[dict(s, target=t) for s, t in zip(cfg["sample"]["strata"], (15, 15, 15, 15))])
    with tempfile.TemporaryDirectory() as tmp:
        data, results = Path(tmp) / "data", Path(tmp) / "results"
        results.mkdir()
        synthetic.write_corpus(data, n=300, seed=3)
        records, lrep = loader.load(data / "instances.jsonl", data / "truth.jsonl", cfg, data)
        picked, srep = sample.stratified_sample(records, cfg)
        scores = [synthetic.mock_score(r.id, r.text) for r in picked]
        bad = [(s["id"], scoring.validate_score(s, r.text, cfg)) for s, r in zip(scores, picked) if scoring.validate_score(s, r.text, cfg)]
        rep = ev.evaluate(picked, scores, cfg)
        _write_json(results / "smoke_report.json", rep, results)
        return {"MOCK": "szabályalapú próba-pontozó, nem AI és nem mérési eredmény", "loaded": lrep["n_kept"], "sampled": srep["size_actual"],
                "invalid_scores": len(bad), "spearman_vs_truthMean": rep["regression_vs_truthMean"]["spearman"], "kendall": rep["regression_vs_truthMean"]["kendall_tau_b"],
                "accuracy_vs_truthClass": rep["classification_vs_truthClass"]["accuracy"]}


def main(argv):
    cfg = load_config()
    data_dir, results_dir = _dirs(cfg)
    cmd = argv[0] if argv else ""
    if cmd == "verify" and len(argv) == 2:
        print(json.dumps(loader.verify_archive(check_read(argv[1], data_dir), cfg["known_archives"]), indent=1))
    elif cmd == "inspect":
        records, rep = _load(cfg, data_dir)
        rep["corpus_distribution"] = sample.distribution(records, cfg["sample"]["strata"])
        print(json.dumps(rep, ensure_ascii=False, indent=1, default=list))
    elif cmd == "sample":
        lrep, srep = do_sample(cfg, data_dir, results_dir)
        print(json.dumps({k: srep[k] for k in ("size_actual", "shortfall", "strata")}, ensure_ascii=False, indent=1))
    elif cmd == "evaluate" and len(argv) == 2:
        print(json.dumps(do_evaluate(cfg, data_dir, results_dir, argv[1]), ensure_ascii=False, indent=1, default=list)[:4000])
    elif cmd == "smoke":
        print(json.dumps(do_smoke(), ensure_ascii=False, indent=1))
    elif cmd == "gemini-dryrun":
        print(json.dumps(do_gemini_dryrun(cfg, data_dir, results_dir), ensure_ascii=False, indent=1))
    elif cmd == "groq-dryrun":
        print(json.dumps(do_groq_dryrun(cfg, data_dir, results_dir), ensure_ascii=False, indent=1))
    elif cmd == "groq-dryrun-v2":
        print(json.dumps(do_groq_dryrun(groq_v2_cfg(cfg), data_dir, results_dir), ensure_ascii=False, indent=1))
    elif cmd == "groq-run-v2" and argv[1:] == ["--go"]:
        print(json.dumps(do_groq_run(groq_v2_cfg(cfg), results_dir), ensure_ascii=False, indent=1))
    elif cmd == "groq-run" and argv[1:] == ["--go"]:
        print(json.dumps(do_groq_run(cfg, results_dir), ensure_ascii=False, indent=1))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
