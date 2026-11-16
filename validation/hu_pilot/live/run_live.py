"""Az éles modellfuttatás parancssora (Gemini vagy Groq, egyszerre egy szolgáltató, MÉRÉSI futás: nincs szolgáltatóváltás).

  python -m validation.hu_pilot.live.run_live --provider gemini --out-dir DIR --run-name NÉV --model MODELL --mode check
  python -m validation.hu_pilot.live.run_live --provider gemini --out-dir DIR --run-name NÉV --model MODELL --mode run --live --confirm INDITSD

check: hálózat nélkül ellenőriz (csomag, kérések, kulcs megléte), nem hív semmit.
run:   valódi hívások; csak --live ÉS --confirm INDITSD mellett, csak lezárt (kapun átment) csomaggal, a kulcs a környezetből (a név a konfigurációban van).
Kilépési kód: 0 kész, 1 hibás ellenőrzés, 2 elutasítva (kapu, megerősítés, kulcs), 3 megállt (kvóta, számlázás, hiba: a kész címek megmaradnak, folytatható), 4 nem teljes."""
import argparse
import json
import os
import sys
from pathlib import Path

from .. import bundle as B
from .. import modelrun, providers as V
from ..freeze import NotFrozen
from ..paths import load_config
from .transport import HttpTransport

CONFIRM = "INDITSD"


def _model_for(cfg, provider, model):
    cfgm = cfg["model"]["providers"][provider].get("model")
    if provider == "groq":
        if model and model != cfgm:
            raise modelrun.RunRefused(f"a Groq modellje a konfigurációban rögzített ({cfgm}); eltérő modell nem engedett")
        return cfgm
    if not model or not str(model).strip():
        raise modelrun.RunRefused("a Gemini modelljét meg kell adni (--model)")
    return str(model).strip()


def check(b, cfg, provider, model, key_present):
    rows = modelrun.build_requests(b["titles"], provider, cfg)
    errs = modelrun.verify_requests(rows, b["titles"], provider, cfg)
    return {"mode": "check", "provider": provider, "model": model, "n_requests": len(rows), "prompt_sha256": b["prompt_sha256"], "schema_sha256": b["schema_sha256"],
            "bundle_sha256": b["sha256"], "freeze_decision": b["freeze"]["gate"]["decision"], "key_present": bool(key_present), "network_used": False,
            "errors": errs, "status": "OK" if not errs else "HIBA"}


def run(b, cfg, provider, model, api_key, out_dir, run_name, base_url=None, **inject):
    """Valódi futás. A base_url csak a helyi hamis szerveres tesztnek való; az éles hívás az alapértelmezett https címre megy."""
    tr = HttpTransport(provider, api_key, cfg["model"]["providers"][provider]["timeout_s"], base_url=base_url)
    return modelrun.run_measurement(b["titles"], provider, tr, cfg, Path(out_dir), run_name, model, manifest=b["freeze"], **inject)


def _args(argv):
    ap = argparse.ArgumentParser(prog="run_live", add_help=True)
    ap.add_argument("--provider", required=True, choices=["gemini", "groq"])
    ap.add_argument("--bundle", default=str(B.DEFAULT_PATH))
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--model", default="")
    ap.add_argument("--mode", choices=["check", "run"], default="check")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--confirm", default="")
    return ap.parse_args(argv)


def main(argv=None):
    a = _args(argv if argv is not None else sys.argv[1:])
    cfg = load_config()
    key = ""
    try:
        b = B.load_bundle(a.bundle, cfg)
        model = _model_for(cfg, a.provider, a.model)
        alias = cfg["model"]["providers"][a.provider]["key_alias"]
        key = os.environ.get(alias, "").strip()
        if a.mode == "check":
            out = check(b, cfg, a.provider, model, key)
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return 0 if out["status"] == "OK" else 1
        if not a.live or a.confirm != CONFIRM:
            raise modelrun.RunRefused(f"éles futtatáshoz kell: --live és --confirm {CONFIRM}")
        if not key:
            raise modelrun.RunRefused(f"hiányzik a kulcs a környezetből ({alias})")
        rep = run(b, cfg, a.provider, model, key, a.out_dir, a.run_name)
    except (B.BundleError, NotFrozen, modelrun.RunRefused, ValueError) as e:
        msg = str(e)[:300].replace(key, "[REDACTED]") if key else str(e)[:300]          # a saját üzenetek a kulcs NEVÉT mondják (alias), értékét soha; ha mégis megjelenne, kicseréljük
        print(json.dumps({"status": "ELUTASÍTVA", "ok": False, "reason": msg}, ensure_ascii=False))
        return 2
    keep = ("run_id", "status", "provider", "model_requested", "models_returned", "failover_allowed", "n_titles", "n_ok", "n_failed", "n_pending", "requests_total", "outcomes", "tokens",
            "resume_after_utc", "probes", "quota_stops", "invocations", "prompt_sha256", "schema_sha256")
    print(json.dumps({k: rep.get(k) for k in keep}, ensure_ascii=False, indent=1))
    return 0 if rep["status"] == "complete" else (3 if rep["status"].startswith("stopped") else 4)


if __name__ == "__main__":
    sys.exit(main())
