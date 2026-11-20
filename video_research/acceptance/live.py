"""Opcionális, KÉZI valódi-modell mód: `python -m video_research.acceptance.runner --live --max-calls N [--no-semantic]`.

Csak a felhasználó saját gépén, saját kulccsal és jóváhagyással futtatandó (a repó CLAUDE.md-je az ügynöknek tiltja az éles hívást, ezért ezt az ügynök NEM futtatta).
Előfeltétel: GEMINI_API_KEY és VR_GEMINI_MODEL környezeti változó (a kulcs nem kerül kimenetre). A futás előtt kiírja a tervet (hívásszám, becsült tokenek),
és gépelt megerősítést kér; a hívások száma kemény korláttal védett. A pénzbeli költséget nem becsüljük (árat nem találunk ki): tokenszám × a saját csomagod ára."""
from __future__ import annotations

import os
import sys

from ..extraction import SYSTEM, build_user_prompt
from ..llm import LLMUnavailable
from ..llm_gemini import build_gemini
from ..llm import estimate_tokens
from .cases import CASES
from .runner import evaluate, render, run_case


class Capped:
    def __init__(self, inner, max_calls):
        self.inner, self.max_calls, self.n = inner, max_calls, 0
        self.provider, self.model, self.kind = inner.provider, inner.model, inner.kind

    def complete_json(self, **kw):
        if self.n >= self.max_calls:
            raise LLMUnavailable("elérted a --max-calls korlátot: a futás megáll")
        self.n += 1
        return self.inner.complete_json(**kw)


def main_live(argv: list[str]) -> int:
    key, model = os.environ.get("GEMINI_API_KEY"), os.environ.get("VR_GEMINI_MODEL")
    if not key or not model:
        print("Hiányzik a GEMINI_API_KEY vagy a VR_GEMINI_MODEL környezeti változó. Nem indul hívás.")
        return 2
    if "--max-calls" not in argv:
        print("Kötelező a --max-calls N korlát.")
        return 2
    max_calls = int(argv[argv.index("--max-calls") + 1])
    semantic = "--no-semantic" not in argv
    live_cases = [c for c in CASES if c["id"] not in ("B_lossy",)]            # a B_lossy a kiértékelőt próbálja, modellhívás nélkül értelmetlen
    est_calls = len(live_cases) * (2 if semantic else 1)                      # kinyerés + (legalább) egy szemantikai hívás esetenként; több tétel több hívás
    est_tokens = sum(estimate_tokens(SYSTEM + "x" * 200 + "\n".join(c["segments"])) + 800 for c in live_cases)
    print(f"TERV: {len(live_cases)} eset, legalább ~{est_calls} hívás (a szemantikai ellenőrzés tételenként újabb hívás), becsült bemenet ≈ {est_tokens} token + kimenet. "
          f"Modell: {model}. Kemény hívásplafon: {max_calls}. Ár: a saját csomagod szerint (itt nem becsülünk árat).")
    if input("Gépeld be, hogy IGEN a valódi hívások indításához: ").strip() != "IGEN":
        print("Megszakítva, hívás nem történt.")
        return 1
    llm = Capped(build_gemini(model, key), max_calls)
    bad = 0
    for case in live_cases:
        res = run_case(case, llm=llm)
        checks = evaluate(case, res)
        print(render(case, res, checks))
        bad += any(v for v in checks.values())
    print(f"Hívások: {llm.n}; eltérést mutató esetek: {bad}/{len(live_cases)}")
    return 0
