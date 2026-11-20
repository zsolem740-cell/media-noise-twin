"""Belépési pontok: `python -m video_research.main api|worker|migrate`. Az éles LLM-adapter beadása a README szerint történik."""
from __future__ import annotations

import sys

from .adapters.apify import ApifyAdapter
from .adapters.base import AdapterRegistry
from .adapters.fixture import FixtureAdapter
from .config import load_settings
from .db import Store, make_engine, migrate
from .llm import NullLLM
from .pipeline import Pipeline
from .worker import Worker
import os


def build(settings):
    engine = make_engine(settings.database_url)
    migrate(engine)
    store = Store(engine)
    registry = AdapterRegistry(production=settings.mode == "production")
    if settings.actors:
        registry.register(ApifyAdapter(settings.apify_token, settings.actors))
    if settings.mode == "dev" and os.environ.get("VR_FIXTURE_FILE"):
        registry.register(FixtureAdapter.from_file(os.environ["VR_FIXTURE_FILE"]))
    return store, registry


def app():
    from .api import create_app
    s = load_settings()
    store, _ = build(s)
    return create_app(store, s)


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    s = load_settings()
    store, registry = build(s)
    if cmd == "migrate":
        print("migráció kész")
    elif cmd == "worker":
        Worker(store, Pipeline(store, s, registry, NullLLM()), s).loop()
    elif cmd == "api":
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(store, s), host="0.0.0.0", port=8000)
    else:
        print("használat: python -m video_research.main api|worker|migrate")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
