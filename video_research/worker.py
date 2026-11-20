"""Háttér-worker: adatbázis-alapú tartós feladatsor lease/heartbeat foglalással. Összeomlás után a lejárt lease-ű feladatot átveszi egy másik worker."""
from __future__ import annotations

import os
import socket
import time

from .config import Settings
from .db import Store
from .models import JobStatus
from .pipeline import Pipeline
from .util import get_logger, new_id, redact

log = get_logger("video_research.worker")


class Worker:
    def __init__(self, store: Store, pipeline: Pipeline, settings: Settings, name: str | None = None):
        self.store, self.pipeline, self.settings = store, pipeline, settings
        self.name = name or f"{socket.gethostname()}-{os.getpid()}-{new_id('w')[:6]}"

    def run_once(self) -> str | None:
        jid = self.store.claim_next(self.name, self.settings.lease_seconds)
        if not jid:
            return None
        try:
            job = self.store.get_job(jid)
            if self.store.get_field(jid, "cancel_requested"):
                self.store.set_status(jid, JobStatus.cancelled)
            elif job.approved_plan is None:
                self.pipeline.plan_job(jid)
            else:
                self.pipeline.run_job(jid, heartbeat=lambda: self.store.heartbeat(jid, self.name, self.settings.lease_seconds))
        except Exception as exc:                      # a worker nem állhat le egyetlen feladat hibája miatt; a hiba redaktálva tárolódik
            log.error("feladat hiba: %s %s", jid, type(exc).__name__)
            self.store.set_status(jid, JobStatus.failed, error=redact(f"{type(exc).__name__}: {exc}")[:1000])
        finally:
            self.store.release(jid, self.name)
        return jid

    def loop(self, idle_sleep: float = 2.0) -> None:
        while True:
            if not self.run_once():
                time.sleep(idle_sleep)
