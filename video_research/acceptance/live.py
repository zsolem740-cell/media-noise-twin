"""Egyszeri, KORLÁTOZOTT valódi-modell értékelési futás vezérlője: `python -m video_research.acceptance.runner --live ...`.

A repó CLAUDE.md-je az ügynöknek tiltja a valódi Gemini-hívást; ezt a modult csak a tulajdonos kifejezett jóváhagyása után, a keret és az igazolások megadásával szabad futtatni.
Kemény korlátok (átvitel-szinten, MINDEN tényleges hálózati kérésre, az újrapróbálásokat és javító hívásokat is beleértve):
  * legfeljebb --max-requests kérés (alap 45), legfeljebb --max-tokens összes szolgáltatói token (alap 220000, a jelentett gondolkodási tokenekkel), legfeljebb --max-seconds futásidő (alap 1200);
  * minden kérés ELŐTT: maradék-keret ellenőrzés (becsült bemenet + maxOutputTokens ≤ maradék token), különben a futás megáll;
  * nincs modell- vagy szolgáltatóváltás (a visszaadott modellverzió eltérése megállítja a futást); kvótakimerülés, hitelesítési/technikai hiba megállítja a futást;
  * a kérés törzse csak a rendszerprompt + a kézzel írt eset kérdése és átirata: ha a törzsben a kulcs vagy bármely (nem triviális) környezeti változó értéke szerepelne, a futás megáll;
  * a futás előtt lefagyasztott jegyzék (commit SHA, prompt-/eset-/kiértékelő-hash, modellazonosító, keretek); a futás végén a hash-eket újraellenőrizzük: eltérés = érvénytelen futás;
  * nyers modellkimenet és feldolgozott eredmény külön fájlban, titkok nélkül (results/ mappa: a repóba nem kerül).
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import extraction as EX
from ..llm import LLMQuotaExhausted, LLMRejected, LLMRunStopped, LLMTransient, LLMUnavailable
from ..llm_gemini import GeminiLLM
from . import cases as CASES_MOD
from . import runner as RUNNER_MOD
from .cases import CASES

ROOT = Path(__file__).resolve().parents[2]
CONFIG_VERSION = "gen-cfg-2"      # 1: semantic maxOutputTokens=50, nincs thinkingConfig (elvetve: csonkolást/üres választ okozhat); 2: semantic 512 + thinkingLevel MINIMAL
THINKING_LEVELS = {"semantic": "MINIMAL"}                                      # csak a rövid, strukturált ellenőrzésre; a kinyerés a modell alapértelmezett gondolkodásán marad
GENERATION_CONFIG = {
    "endpoint": "generateContent (REST, v1beta)", "temperature": 0.0, "responseMimeType": "application/json",
    "extraction": {"maxOutputTokens": EX.MAX_OUT_TOKENS, "thinkingConfig": "nincs beállítva (modell-alapérték; a dokumentáció szerint gemini-3.6-flash: medium)"},
    "semantic": {"maxOutputTokens": EX.SEMANTIC_MAX_TOKENS, "thinkingConfig": {"thinkingLevel": THINKING_LEVELS["semantic"]}},
}
EXCLUDED = {"B_lossy"}                                          # a kiértékelőt próbálja modellhívás nélkül: nem küldhető ki


RunStopped = LLMRunStopped            # a csővezeték ismeri: a kész eredmények megmaradnak, a hátralévő lépések jelölve maradnak el


class Budget:
    def __init__(self, max_requests=45, max_tokens=220_000, max_seconds=1200, clock=time.monotonic):
        self.max_requests, self.max_tokens, self.max_seconds, self.clock = max_requests, max_tokens, max_seconds, clock
        self.t0 = clock()
        self.requests = self.tokens = self.prompt = self.completion = self.thoughts = 0
        self.errors: list[dict] = []
        self.raw: list[dict] = []
        self.stop: tuple[str, str] | None = None     # az első kényszerű megállás oka (kind, reason)

    def elapsed(self) -> float:
        return self.clock() - self.t0

    def precheck(self, est_input: int, max_out: int) -> None:
        if self.requests >= self.max_requests:
            raise RunStopped(f"elérted a {self.max_requests} kérés keretet", "limit")
        if self.elapsed() >= self.max_seconds:
            raise RunStopped(f"lejárt a {self.max_seconds} s futásidő-keret", "limit")
        if self.tokens + est_input + max_out > self.max_tokens:
            raise RunStopped(f"a következő kérés (becsült bemenet {est_input} + max kimenet {max_out}) nem fér a maradék tokenkeretbe ({self.max_tokens - self.tokens})", "limit")


class BudgetedTransport:
    """Átvitel-burkoló: minden tényleges kérés számolva, keret-ellenőrizve és nyersen naplózva; a modell nem vált."""

    def __init__(self, inner, budget: Budget, model: str, secrets: list[str], case_id_ref):
        self.inner, self.b, self.model, self.secrets, self.case_ref = inner, budget, model, [s for s in secrets if s], case_id_ref

    def __call__(self, model, body):
        try:
            return self._call(model, body)
        except RunStopped as rs:
            self.b.stop = self.b.stop or (rs.kind, rs.reason)
            raise

    def _call(self, model, body):
        text = json.dumps(body, ensure_ascii=False)
        if model != self.model:
            raise RunStopped("modellváltás kísérlete: tiltott", "integrity")
        if any(s in text for s in self.secrets):
            raise RunStopped("a kérés törzse titkot vagy környezeti változó értékét tartalmazná: megállítva, nem küldjük ki", "integrity")
        max_out = int(body.get("generationConfig", {}).get("maxOutputTokens", 4096))
        self.b.precheck(len(text) // 2 + 1, max_out)          # KONSERVATÍV becslés (2 karakter/token): inkább túlfoglal, mint alulbecsül; valódi tokenizálót nem használunk (az újabb kérés lenne)
        self.b.requests += 1
        entry = {"n": self.b.requests, "case": self.case_ref(), "t": round(self.b.elapsed(), 2), "request_chars": len(text), "request_body": body}
        try:
            raw = self.inner(model, body)
        except Exception as exc:                                  # időtúllépés/hálózat: a kérés elment, számoljuk
            entry["transport_error"] = type(exc).__name__
            self.b.raw.append(entry)
            self.b.errors.append({"n": entry["n"], "type": type(exc).__name__})
            raise
        entry.update({"status": raw.status, "response_text": raw.text, "latency_ms": raw.latency_ms})
        try:
            d = json.loads(raw.text)
        except ValueError:
            d = {}
        u = d.get("usageMetadata") or {} if isinstance(d, dict) else {}
        p, c, th, tot = (int(u.get(k) or 0) for k in ("promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount", "totalTokenCount"))
        used = max(tot, p + c + th)                               # a gondolkodási tokeneket mindenképp beszámítjuk
        self.b.prompt, self.b.completion, self.b.thoughts, self.b.tokens = self.b.prompt + p, self.b.completion + c, self.b.thoughts + th, self.b.tokens + used
        entry["usage"] = {"prompt": p, "completion": c, "thoughts": th, "total_reported": tot, "counted": used}
        if raw.status != 200:
            self.b.errors.append({"n": entry["n"], "status": raw.status, "message": str((d.get("error") or {}).get("message", ""))[:200] if isinstance(d, dict) else ""})
        mv = d.get("modelVersion") if isinstance(d, dict) else None
        entry["model_returned"] = mv
        self.b.raw.append(entry)
        if mv and not str(mv).startswith(self.model):
            raise RunStopped(f"a szolgáltató más modellel válaszolt ({mv}) a kértnél ({self.model}): megállítva", "integrity")
        if self.b.tokens > self.b.max_tokens:
            raise RunStopped("az összes token meghaladta a keretet", "limit")
        if raw.status in (401, 403):
            raise RunStopped(f"hitelesítési vagy jogosultsági hiba (HTTP {raw.status}): technikai hiba, megállítva", "technical")
        return raw


# --- esetkészletek: "legacy" (az eredeti, változatlan útvonal) és "trump-v2" (csak lefagyasztott állapotban, a jóváhagyott dokumentum lenyomatának induláskori ellenőrzésével) ---
LEGACY_SET, V2_SET = "legacy", "trump-v2"
CASE_SETS = (LEGACY_SET, V2_SET)
V2_APPROVED_DOC_SHA256 = "2b4596962b7c30465deec0f5ce1bb690667bdc1fc5cc605ab5527e5e03c01158"      # a felhasználó által jóváhagyott 4. átdolgozás lenyomata (a cases_trump_v2-ben is rögzítve: kettős védelem)


class FrozenCaseSetError(ValueError):
    """A lefagyasztott esetkészlet előfeltétele nem teljesül: a futás NEM indul, modellhívás nem történik, kimeneti mappa és manifeszt sem jön létre."""


def _v2():
    from . import cases_trump_v2 as c2, eval_trump_v1 as e1, eval_trump_v2 as e2
    return c2, e1, e2


def v2_doc_path() -> Path:
    return Path(_v2()[0].__file__).resolve().parent / "frozen" / "expectations_trump_v2.md"


def _cases_of(case_set: str) -> list[dict]:
    if case_set == LEGACY_SET:
        return CASES
    if case_set == V2_SET:
        return _v2()[0].CASES
    raise CaseSelectionError(f"ismeretlen esetkészlet: {case_set!r} (legacy vagy {V2_SET})")


def verify_v2_frozen() -> dict:
    """Induláskor, MINDEN modellhívás előtt: approved_frozen státusz, létező lefagyasztott dokumentum, a tényleges SHA-256 egyezik a jóváhagyottal (itt ÉS a cases_trump_v2 konstansában), a bemeneti szöveg sértetlen.
    Bármely eltérés: FrozenCaseSetError (a futás nem indul)."""
    c2 = _v2()[0]
    if c2.APPROVAL_STATUS != "approved_frozen":
        raise FrozenCaseSetError(f"a v2 esetkészlet nem jóváhagyott/lefagyasztott (APPROVAL_STATUS={c2.APPROVAL_STATUS!r}): a futás nem indul")
    path = v2_doc_path()
    if not path.is_file():
        raise FrozenCaseSetError(f"hiányzik a lefagyasztott dokumentum ({path.name}): a futás nem indul")
    actual = _sha(path)
    if actual != V2_APPROVED_DOC_SHA256:
        raise FrozenCaseSetError("a lefagyasztott dokumentum lenyomata eltér a jóváhagyottól: a futás nem indul")
    if c2.EXPECTATIONS_DRAFT_SHA256 != V2_APPROVED_DOC_SHA256:
        raise FrozenCaseSetError("az esetkészlet rögzített elvárás-lenyomata eltér a jóváhagyottól: a futás nem indul")
    if c2.text_sha256() != c2.TEXT_SHA256:
        raise FrozenCaseSetError("a v2 bemeneti szöveg lenyomata eltér a rögzítettől: a futás nem indul")
    return {"path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else path.name, "sha256_actual": actual, "sha256_expected": V2_APPROVED_DOC_SHA256,
            "sha256_in_case_set_constant": c2.EXPECTATIONS_DRAFT_SHA256, "match": True, "approval_status": c2.APPROVAL_STATUS, "input_text_sha256": c2.text_sha256()}


def _frozen_files(case_set: str) -> dict[str, Path]:
    """A futás közben sem változhat fájlok: az esetkészlet szerint. A legacy készlet változatlanul a három eredeti fájl."""
    base = {"cases.py": Path(CASES_MOD.__file__), "evaluator(runner.py)": Path(RUNNER_MOD.__file__), "extraction.py": Path(EX.__file__)}
    if case_set == LEGACY_SET:
        return base
    c2, e1, e2 = _v2()
    return {"extraction.py": Path(EX.__file__), "cases_trump_v2.py": Path(c2.__file__), "evaluator(eval_trump_v2.py)": Path(e2.__file__),
            "evaluator_base(eval_trump_v1.py)": Path(e1.__file__), "controller(live.py)": Path(__file__), "frozen/expectations_trump_v2.md": v2_doc_path()}


def _git_state() -> tuple[str, str]:
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "video_research", "validation", "scripts", "config", "CLAUDE.md"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return sha, dirty


def _modified_vs_head(paths: dict[str, Path]) -> list[str]:
    """Mely rögzített fájlok térnek el a Git HEAD-től (módosított vagy nem követett)? Ha a Git nem kérdezhető le, a fájl a listában szerepel (nem igazolt)."""
    out = []
    for name, path in paths.items():
        r = subprocess.run(["git", "status", "--porcelain", "--", str(path)], cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0 or r.stdout.strip():
            out.append(name)
    return out


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def manifest(model: str, budget_cfg: dict, case_ids: list[str], run_id: str, case_set: str = LEGACY_SET) -> dict:
    sha, dirty = _git_state()
    prompts = EX.SYSTEM + inspect.getsource(EX.semantic_check) + inspect.getsource(EX.extract_findings)
    files = _frozen_files(case_set)
    m = {"commit_sha": sha, "working_tree_clean": not dirty, "dirty_files": dirty.splitlines()[:10], "model_id": model,
         "prompt_version": "sha256:" + hashlib.sha256(prompts.encode()).hexdigest()[:16],
         "hashes": {name: _sha(path) for name, path in files.items()},
         "run_id": run_id, "cases": list(case_ids), "semantic_check_enabled": True, "budget": budget_cfg,
         "config_version": CONFIG_VERSION, "generation_config": GENERATION_CONFIG,
         "generation_config_sha256": hashlib.sha256(json.dumps(GENERATION_CONFIG, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
         "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if case_set != LEGACY_SET:                                  # a v2-höz tartozó többletek; a legacy manifeszt kulcsai változatlanok
        c2 = _v2()[0]
        m.update({"case_set": case_set, "case_set_version": c2.CASE_SET_VERSION, "approval_status": c2.APPROVAL_STATUS,
                  "expectations_doc": {"expected_sha256": V2_APPROVED_DOC_SHA256, "actual_sha256": m["hashes"]["frozen/expectations_trump_v2.md"],
                                       "sha256_in_case_set_constant": c2.EXPECTATIONS_DRAFT_SHA256,
                                       "match": m["hashes"]["frozen/expectations_trump_v2.md"] == V2_APPROVED_DOC_SHA256 == c2.EXPECTATIONS_DRAFT_SHA256},
                  "input_text_sha256": c2.text_sha256(), "pinned_files_modified_vs_head": _modified_vs_head(files)})
    return m


def verify_frozen(m: dict) -> list[str]:
    now = {name: _sha(path) for name, path in _frozen_files(m.get("case_set", LEGACY_SET)).items()}
    return [k for k in now if now[k] != m["hashes"][k]]


class CaseSelectionError(ValueError):
    pass


def parse_case_list(raw: str | None, case_set: str = LEGACY_SET) -> list[str]:
    """Explicit esetlista (vesszővel elválasztva). Üres, hibás, ismeretlen, kizárt vagy ismétlődő elem esetén hiba: NINCS visszaesés a teljes készletre."""
    if raw is None or not raw.strip():
        raise CaseSelectionError("az esetlista üres vagy hiányzik: explicit --cases kell, nincs visszaesés a teljes készletre")
    ids = [x.strip() for x in raw.split(",")]
    if any(not x for x in ids):
        raise CaseSelectionError("hibás esetlista: üres elem (pl. kettős vessző vagy záró vessző)")
    known = {c["id"] for c in _cases_of(case_set)}            # a két esetkészlet nem keverhető: a másik készlet azonosítója "ismeretlen"
    bad = [x for x in ids if x not in known]
    if bad:
        raise CaseSelectionError(f"ismeretlen esetazonosító: {bad}")
    excl = [x for x in ids if x in EXCLUDED] if case_set == LEGACY_SET else []
    if excl:
        raise CaseSelectionError(f"nem küldhető ki valódi modellnek: {excl}")
    if len(set(ids)) != len(ids):
        raise CaseSelectionError("ismétlődő esetazonosító")
    return ids


def ordered_cases(case_ids: list[str], case_set: str = LEGACY_SET) -> list[dict]:
    by = {c["id"]: c for c in _cases_of(case_set)}
    parse_case_list(",".join(case_ids), case_set)               # ugyanaz az ellenőrzés
    return [by[i] for i in case_ids]                            # a megadott sorrendben, csak ezek


def _classify(exc: Exception) -> tuple[str, str]:
    """Technikai/hitelesítési/szabályhiba = megállás; tartalmi (blokkolt, csonka, érvénytelen) = rögzítés és tovább."""
    if isinstance(exc, RunStopped):
        return exc.kind, exc.reason
    if isinstance(exc, LLMQuotaExhausted):
        return "quota", str(exc)
    if isinstance(exc, LLMRejected):
        head = str(exc).split(":", 1)[0]
        if head in ("truncated", "empty"):                           # válaszkeret-/konfigurációs probléma: NEM tartalmi elutasítás, NEM sikeres ellenőrzés
            return "response_limit", str(exc)
        return ("content", str(exc)) if head in ("blocked", "invalid") else ("technical", str(exc))
    if isinstance(exc, (LLMUnavailable, LLMTransient, ConnectionError, TimeoutError)):
        return "technical", f"{type(exc).__name__}: {exc}"
    return "technical", f"{type(exc).__name__}: {exc}"


def execute(model: str, transport, budget: Budget, outdir: Path, case_ids: list[str], run_id: str, run_case_fn=None, clock=time.monotonic,
            min_interval_s: float = 13.0, sleep=time.sleep, case_set: str = LEGACY_SET) -> dict:
    """A teljes futás: indító esetek, majd a többi. A `transport` a nyers (valódi vagy hamis) átvitel; a vezérlő köréje rakja a keretet.
    case_set="trump-v2": csak approved_frozen állapotban; a lefagyasztott dokumentum lenyomatát MINDEN modellhívás (és a kimeneti mappa létrehozása) előtt ellenőrzi; a v2 kiértékelővel értékel."""
    if case_set not in CASE_SETS:
        raise CaseSelectionError(f"ismeretlen esetkészlet: {case_set!r} (legacy vagy {V2_SET})")
    if case_set != LEGACY_SET:
        verify_v2_frozen()                                       # eltérés: FrozenCaseSetError, semmi nem indul
        run_case_fn = run_case_fn or _v2()[2].run_case_v2
        evaluate = _v2()[2].evaluate_trump_v2
    else:
        run_case_fn = run_case_fn or RUNNER_MOD.run_case
        evaluate = RUNNER_MOD.evaluate
    selected = ordered_cases(case_ids) if case_set == LEGACY_SET else ordered_cases(case_ids, case_set)      # hibás lista: kivétel, mielőtt bármi elindulna (a legacy hívás alakja változatlan)
    m = manifest(model, {"max_requests": budget.max_requests, "max_tokens": budget.max_tokens, "max_seconds": budget.max_seconds}, case_ids, run_id, case_set)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    current = {"id": None}
    secrets = [os.environ.get("GEMINI_API_KEY", "")] + [v for k, v in os.environ.items() if len(v) >= 12 and any(w in k.upper() for w in ("KEY", "TOKEN", "SECRET", "PASSWORD"))]
    bt = BudgetedTransport(transport, budget, model, secrets, lambda: current["id"])
    llm = GeminiLLM(model, bt, min_interval_s=min_interval_s, thinking_levels=THINKING_LEVELS, sleep=sleep, clock=clock)
    results, stopped = [], None
    for case in selected:
        current["id"] = case["id"]
        if stopped:
            results.append({"id": case["id"], "ran": False, "reason": f"nem futott: {stopped}"})
            continue
        t_before = (budget.requests, budget.tokens)
        try:
            res = run_case_fn(case, llm=llm)
            checks = evaluate(case, res)
            job_err = res["store"].get_field(res["jid"], "error") or ""
            entry = {"id": case["id"], "ran": True, "status": res["job"].status.value, "checks": checks, "job_error": job_err[:400],
                     "findings": [{"bucket": f.report_bucket, "kind": f.category.value, "statement_hu": f.statement_hu, "quote": f.source_references[0].supporting_quote,
                                   "refs": [{"role": r.role, "segments": r.transcript_segment_ids, "timestamp": r.timestamp} for r in f.source_references],
                                   "verification_question": f.verification_question, "extends_known": f.extends_known} for f in res["report"].findings],
                     "filter_log": [{"reason": e.reason_code.value, "snippet": e.snippet} for e in res["report"].filter_log], "no_result_note": res["report"].no_result_note,
                     "requests_used": budget.requests - t_before[0], "tokens_used": budget.tokens - t_before[1],
                     "unchecked_not_results": res["report"].unchecked_findings, "coverage": res["report"].coverage,
                     "partial": bool(res["report"].unchecked_findings) or not res["report"].coverage.get("complete", True)}
            if case_set != LEGACY_SET:                            # v2: a kiértékelő külön jelzései (a hard_ok NEM tartalmi megfelelés)
                entry["hard_ok"] = not any(checks["hard"].values())
                entry["content_flags"] = checks.get("content_flags", [])
                entry["human_content_judgement"] = checks.get("human_content_judgement")
            if budget.stop:                                       # a vezérlő megállította (keret/technikai/integritás), a csővezeték csak hibaként látta
                stopped = f"{budget.stop[0]}: {budget.stop[1]}"
                entry["stopped"] = stopped
            elif "kvótája kimerült" in job_err:
                stopped = "quota: a modellszolgáltató kvótája kimerült"
                entry["stopped"] = stopped
            results.append(entry)
        except Exception as exc:                                  # RunStopped vagy váratlan
            kind, why = budget.stop if budget.stop else _classify(exc)      # a vezérlő megállási oka az elsődleges (a csővezeték csak mellékes hibát lát)
            results.append({"id": case["id"], "ran": True, "error_kind": kind, "error": why})
            if kind in ("technical", "quota", "integrity", "limit"):
                stopped = f"{kind}: {why}"
        # a futás közbeni bármely technikai kerethiba (a vezérlő RunStopped-ja a csővezetéken belül elnyelődhet): a kérés-/token-/időkeret külön is megállít
        if stopped is None:
            try:
                budget.precheck(0, 0)
            except RunStopped as rs:
                stopped = f"{rs.kind}: {rs.reason}"
    changed = verify_frozen(m)
    unrun = [r["id"] for r in results if not r.get("ran")]
    summary = {"manifest": m, "cases_not_run": unrun, "cases_partial": [r["id"] for r in results if r.get("partial")], "frozen_files_changed_during_run": changed, "valid_run": not changed, "stopped": stopped,
               "requests": budget.requests, "tokens": {"counted_total": budget.tokens, "prompt": budget.prompt, "completion": budget.completion, "thoughts": budget.thoughts},
               "runtime_s": round(budget.elapsed(), 1), "provider_errors": budget.errors, "results": results}
    if case_set != LEGACY_SET:
        summary["case_set"] = case_set
    (outdir / "raw_model_io.json").write_text(json.dumps(budget.raw, ensure_ascii=False, indent=1), encoding="utf-8")      # nyers kérés/válasz, titok nélkül
    (outdir / "processed_results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main_live(argv: list[str]) -> int:
    """Szigorú indítás: minden paraméter explicit (esetlista, futásazonosító, keretek), nincs alapérték és nincs visszaesés."""
    import re
    key, model = os.environ.get("GEMINI_API_KEY"), os.environ.get("VR_GEMINI_MODEL")
    if not key or not model:
        print("Hiányzik a GEMINI_API_KEY vagy a VR_GEMINI_MODEL. Nem indul hívás.")
        return 2
    def val(name):
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else None
    try:
        case_set = val("--case-set") or LEGACY_SET
        if "--case-set" in argv and not val("--case-set"):
            raise CaseSelectionError("a --case-set értéke hiányzik (legacy vagy trump-v2): nincs visszaesés az alapértelmezettre")
        if case_set not in CASE_SETS:
            raise CaseSelectionError(f"ismeretlen --case-set: {case_set!r} (legacy vagy {V2_SET})")
        if case_set != LEGACY_SET:
            verify_v2_frozen()                                   # induláskor, MINDEN modellhívás előtt
        ids = parse_case_list(val("--cases")) if case_set == LEGACY_SET else parse_case_list(val("--cases"), case_set)     # a legacy hívás alakja változatlan
        run_id = val("--run-id") or ""
        if not re.fullmatch(r"[A-Za-z0-9_.-]{6,48}", run_id):
            raise CaseSelectionError("a --run-id kötelező (6–48 karakter: betű, szám, _ . -)")
        raw_budget = [val("--max-requests"), val("--max-tokens"), val("--max-seconds")]
        if any(x is None or not x.isdigit() or int(x) <= 0 for x in raw_budget):
            raise CaseSelectionError("a --max-requests, --max-tokens és --max-seconds kötelező, pozitív egész (nincs alapérték)")
    except (CaseSelectionError, FrozenCaseSetError) as exc:
        print(f"Hibás indítás: {exc}. Nem indul hívás.")
        return 2
    need = ["--attest-free-tier", "--attest-no-billing", "--attest-owner-rule-change"]
    missing = [n for n in need if n not in argv]
    if missing:
        print("Az igazolások hiányoznak (" + ", ".join(missing) + "). A futás csak igazoltan ingyenes projekt/modell és a tulajdonosi szabálymódosítás után indulhat. Nem indul hívás.")
        return 2
    budget = Budget(int(raw_budget[0]), int(raw_budget[1]), int(raw_budget[2]))
    m = manifest(model, {"max_requests": budget.max_requests, "max_tokens": budget.max_tokens, "max_seconds": budget.max_seconds}, ids, run_id, case_set)
    if not m["working_tree_clean"]:
        print("A munkafa nem tiszta (nem commitolt változás): a commit SHA nem azonosítaná a kódot. Nem indul hívás.", m["dirty_files"])
        return 2
    outdir = ROOT / "video_research" / "results" / run_id
    if outdir.exists():
        print(f"A futásazonosító már használt ({outdir}). Nem indul hívás.")
        return 2
    print(json.dumps(m, ensure_ascii=False, indent=2))
    if input("Gépeld be, hogy IGEN a valódi hívások indításához: ").strip() != "IGEN":
        print("Megszakítva, hívás nem történt.")
        return 1
    from validation.hu_pilot.live.transport import HttpTransport
    summary = execute(model, HttpTransport("gemini", key, 60.0), budget, outdir, ids, run_id, case_set=case_set)
    print(json.dumps({k: summary[k] for k in ("valid_run", "stopped", "requests", "tokens", "runtime_s", "provider_errors", "cases_not_run", "cases_partial")}, ensure_ascii=False, indent=2))
    print("Részletek:", outdir)
    return 0
