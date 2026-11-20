"""Vertikális próba egy parancsban: videólink(ek) -> metaadat -> felirat -> magyar kivonat -> forráslink + időbélyeg.
Helyi, átmeneti SQLite adatbázissal, a worker és a pipeline valódi kódjával. Nincs fizetős hívás és nincs modellhívás:
az információkivonat alapból a kulcsszavas baseline (NEM AI); VR_LLM_PROVIDER=gemini + VR_GEMINI_MODEL + GEMINI_API_KEY esetén Gemini (csak a felhasználó saját, jóváhagyott futásához). A terv hash-ét a próba maga hagyja jóvá, mert minden művelet ingyenes.

Használat: python -m video_research.trial "kérdés" LINK [LINK...] [--fixture FÁJL] [--detail]"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from .adapters.base import AdapterRegistry
from .adapters.fixture import FixtureAdapter
from .adapters.tiktok import TikTokAdapter
from .adapters.youtube import YouTubeAdapter
from .config import Settings, load_settings
from .db import Store, make_engine, migrate
from .models import JobStatus, ResearchReport
from .pipeline import Pipeline
from .report import evidence_markdown, filter_log_markdown, to_markdown
from .worker import Worker
from .main import build_llm


def run_trial(question: str, links: list[str], fixture: str | None = None, detail: bool = False, known: list[str] | None = None) -> tuple[str, JobStatus, str]:
    with tempfile.TemporaryDirectory() as d:
        engine = make_engine(f"sqlite:///{Path(d) / 'trial.db'}")
        migrate(engine)
        settings = load_settings({**__import__("os").environ, "VR_MODE": "dev"})
        store = Store(engine)
        reg = AdapterRegistry(production=False)
        if fixture:
            reg.register(FixtureAdapter.from_file(fixture))
        else:
            reg.register(YouTubeAdapter())
            reg.register(TikTokAdapter())
        pipe = Pipeline(store, settings, reg, build_llm(settings), semantic=settings.llm_provider == "gemini", poll_interval=0)
        job, _ = store.create_job("\n".join([question, *links]), [], ["hu", "en"], settings.limits, known_information=known)
        w = Worker(store, pipe, settings, name="trial")
        w.run_once()                                                   # tervezés
        if store.get_job(job.id).status != JobStatus.awaiting_approval:
            return job.id, store.get_job(job.id).status, f"A terv nem készült el: {store.get_field(job.id, 'error')}"
        store.set_status(job.id, JobStatus.queued, approved_plan=store.get_field(job.id, "plan"))
        w.run_once()
        j = store.get_job(job.id)
        raw = store.get_field(job.id, "report")
        rep = ResearchReport.model_validate_json(raw) if raw else None
        text = "(nincs jelentés)" if not rep else to_markdown(rep, j) + ("\n" + evidence_markdown(rep, j) + "\n" + filter_log_markdown(rep) if detail else "")
        err = store.get_field(job.id, "error")
        return job.id, j.status, text + (f"\n\nFeldolgozási hibák/hiányok: {err}\n" if err else "")


if __name__ == "__main__":
    args = sys.argv[1:]
    fx = None
    if "--fixture" in args:
        i = args.index("--fixture")
        fx = args[i + 1]
        args = args[:i] + args[i + 2:]
    if len(args) < 2:
        print(__doc__)
        sys.exit(2)
    detail = "--detail" in args
    args = [a for a in args if a != "--detail"]
    jid, status, out = run_trial(args[0], args[1:], fx, detail)
    print(f"[{status.value}] {jid}\n\n{out}")
