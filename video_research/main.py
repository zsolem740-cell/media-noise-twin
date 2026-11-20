"""Belépési pontok: `python -m video_research.main api|worker|migrate|purge`. Az éles LLM-adapter beadása a README szerint történik."""
from __future__ import annotations

import sys

from .adapters.apify import ApifyAdapter
from .adapters.base import AdapterRegistry
from .adapters.fixture import FixtureAdapter
from .adapters.tiktok import TikTokAdapter
from .adapters.youtube import YouTubeAdapter
from .extractive import ExtractiveBaselineLLM
from .llm import NullLLM
from .llm_gemini import build_gemini
from .config import load_settings
from .db import Store, make_engine, migrate
from .pipeline import Pipeline
from .worker import Worker
import os


def build_llm(settings):
    if settings.llm_provider == "gemini":
        return build_gemini(settings.gemini_model, settings.gemini_api_key.reveal() if settings.gemini_api_key else None)
    if settings.llm_provider == "baseline":
        return ExtractiveBaselineLLM()
    return NullLLM()


def build(settings):
    engine = make_engine(settings.database_url)
    migrate(engine)
    store = Store(engine)
    registry = AdapterRegistry(production=settings.mode == "production")
    registry.register(YouTubeAdapter(tuple(settings.allowed_platforms)))     # ingyenes: nyilvános oEmbed + elérhető felirat
    registry.register(TikTokAdapter(tuple(settings.allowed_platforms)))      # csak metaadat; átirat nincs
    if settings.actors:
        registry.register(ApifyAdapter(settings.apify_token, settings.actors))
    if settings.mode == "dev" and os.environ.get("VR_FIXTURE_FILE"):
        registry.register(FixtureAdapter.from_file(os.environ["VR_FIXTURE_FILE"]))
    return store, registry


def app():
    from .api import create_app
    s = load_settings()
    store, _ = build(s)
    return create_app(store, s, _)


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    s = load_settings()
    store, registry = build(s)
    if cmd == "migrate":
        print("migráció kész")
    elif cmd == "purge":
        print(f"törölt feladatok: {store.purge_expired(s.data_retention_days)}")
    elif cmd == "worker":
        Worker(store, Pipeline(store, s, registry, build_llm(s), semantic=s.llm_provider == "gemini"), s).loop()
    elif cmd == "api":
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(store, s, registry), host="0.0.0.0", port=8000)
    else:
        print("használat: python -m video_research.main api|worker|migrate|purge")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
