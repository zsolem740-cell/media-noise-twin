"""Helyi próbakiszolgáló a BÖNGÉSZŐS működési próbához (e2e/ui_probe.js). Csak 127.0.0.1-en hallgat, dev módban, teszt-fixture videókkal és FORGATÓKÖNYVES hamisító modellel
(nincs valódi modellhívás, nincs külső hálózat). Indítás: python -m video_research.e2e.probe_server [port]"""
from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

import uvicorn

from ..acceptance.runner import Scripted
from ..adapters.base import AdapterRegistry
from ..adapters.fixture import FixtureAdapter
from ..api import create_app
from ..config import SecretStr, Settings
from ..db import Store, make_engine, migrate
from ..models import Limits
from ..pipeline import Pipeline
from ..worker import Worker

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "videos.json"
TOKEN = "probe-token-DUMMY-not-a-secret"
ITEMS = [  # a fixture AAAAAAAAAAA videó szegmensei: 0 bevezető, 1 AutoDroid, 2 előny, 3 hiba
    {"seg": 1, "kind": "tool", "statement_hu": "Az AutoDroid nevű eszköz a telefon felületét vezérli.", "why_relevant": "a kérdezett eszköz", "relevance": "direct", "concrete": True},
    {"seg": 3, "kind": "limitation", "statement_hu": "Gyakran elakad a felugró ablakoknál.", "why_relevant": "elhangzott hiba", "relevance": "direct", "concrete": True},
    {"seg": 2, "kind": "claim", "statement_hu": "Az eszköz root hozzáférés nélkül is használható, a szerző szerint.", "why_relevant": "előfeltétel", "relevance": "partial", "concrete": True,
     "needs_check": "csak a készítő állítása", "verification_question": "Megerősíti-e a hivatalos dokumentáció, hogy root nélkül is működik?"},
    {"seg": 0, "kind": "other", "statement_hu": "Bevezető köszöntés", "relevance": "none", "concrete": False},
]


def build_app():
    engine = make_engine(f"sqlite:///{Path(tempfile.mkdtemp()) / 'probe.db'}")
    migrate(engine)
    store, settings = Store(engine), Settings(mode="dev", limits=Limits(), api_token=SecretStr(TOKEN))
    reg = AdapterRegistry(production=False)
    reg.register(FixtureAdapter.from_file(FIXTURE))
    pipe = Pipeline(store, settings, reg, Scripted(ITEMS), semantic=True, poll_interval=0)
    w = Worker(store, pipe, settings, name="probe-worker")
    threading.Thread(target=w.loop, kwargs={"idle_sleep": 0.3}, daemon=True).start()
    return create_app(store, settings, reg)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    uvicorn.run(build_app(), host="127.0.0.1", port=port, log_level="warning")
