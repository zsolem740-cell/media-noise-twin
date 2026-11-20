"""Szolgáltatói futtatás állapottartással: futásazonosító mentése, költségkeret, megszakítás, bizonytalan kimenetel kezelése."""
from __future__ import annotations

import hashlib
import json
from typing import Callable

from .adapters.base import Capability, ProviderPermanentError, RunState, VideoAdapter
from .config import Settings
from .db import Store
from .models import Platform
from .util import RetryableError, UncertainOutcome, get_logger, with_retry

log = get_logger("video_research.executor")


class JobStopped(Exception):
    """Megszakítás, futásidő-keret vagy elvesztett lease: a feldolgozás a lépések között megáll."""
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class CostBudgetExhausted(Exception):
    pass


class UncertainRun(Exception):
    """Bizonytalan kimenetelű fizetős futás: nem indítunk vakon újat."""


def request_key(capability: Capability, platform: Platform, params: dict) -> str:
    return hashlib.sha256(json.dumps([capability.value, platform.value, params], sort_keys=True).encode()).hexdigest()[:32]


class Executor:
    def __init__(self, store: Store, settings: Settings, check: Callable[[], None], sleep: Callable[[float], None], poll_interval: float = 2.0):
        self.store, self.settings, self.check, self.sleep, self.poll_interval = store, settings, check, sleep, poll_interval
        self.notes: list[str] = []          # figyelmeztetések a jelentéshez (pl. nem azonnali leállítás)

    def run(self, jid: str, step: str, adapter: VideoAdapter, capability: Capability, platform: Platform, params: dict, cost_budget: float):
        key = request_key(capability, platform, params)
        rec = self.store.get_provider_run(jid, key)
        run_id = rec["provider_run_id"] if rec else None
        if rec and not run_id:
            # korábbi indítás kimenetele ismeretlen (nincs futásazonosító): állapot nem kérdezhető le, vakon nem indítunk újat
            self.store.save_provider_run(jid, step, adapter.name, capability.value, key, "uncertain")
            raise UncertainRun(f"{step}: egy korábbi indítás kimenetele bizonytalan, ellenőrizd a szolgáltatónál (kulcs: {key})")
        if not run_id:
            self.check()
            spent = sum((r["cost_usd"] or 0.0) for r in self.store.provider_runs(jid))
            # új költséges lépést csak akkor indítunk, ha a legrosszabb eset (a futás költségplafonja) még belefér a keretbe
            if spent + adapter.max_run_cost(capability, platform) > cost_budget + 1e-9:
                raise CostBudgetExhausted(f"{step}: a szolgáltatói költségkeret kimerült vagy a futás plafonja nem fér bele")
            self.store.save_provider_run(jid, step, adapter.name, capability.value, key, "starting")     # szándék rögzítése az indítás ELŐTT
            try:
                run_id = with_retry(lambda: self._start(adapter, capability, platform, params), max_retries=self.settings.max_retries,
                                    base=self.settings.backoff_base_seconds, cap=self.settings.backoff_max_seconds, sleep=self.sleep, should_stop=self._stopping)
            except UncertainOutcome as exc:
                self.store.save_provider_run(jid, step, adapter.name, capability.value, key, "uncertain")
                raise UncertainRun(f"{step}: {exc}") from exc
            except ProviderPermanentError:
                self.store.save_provider_run(jid, step, adapter.name, capability.value, key, "failed")
                raise
            self.store.save_provider_run(jid, step, adapter.name, capability.value, key, "running", provider_run_id=run_id)
        state = self._wait(adapter, run_id, jid, step, key, capability)
        self.store.save_provider_run(jid, step, adapter.name, capability.value, key, state.status, cost_usd=state.cost_usd)
        if state.status != "succeeded":
            raise ProviderPermanentError(f"{step}: a szolgáltatói futás nem sikerült ({state.status} {state.message})")
        return run_id, adapter.results(capability, platform, run_id, params), state

    def _start(self, adapter, capability, platform, params):
        return adapter.start(capability, platform, params)

    def _stopping(self) -> bool:
        try:
            self.check()
            return False
        except JobStopped:
            return True

    def _wait(self, adapter, run_id, jid, step, key, capability) -> RunState:
        while True:
            try:
                self.check()
            except JobStopped:
                ok = adapter.abort(run_id)
                self.notes.append("A megszakítás best effort: " + ("a szolgáltatói futás leállítását kértük, de a tényleges leállás nem garantált és nem azonnali."
                                                                    if ok else "a szolgáltatói futás leállítása nem sikerült, elképzelhető, hogy tovább fut és költséget okoz."))
                self.store.save_provider_run(jid, step, adapter.name, capability.value, key, "abort_requested")
                raise
            st = with_retry(lambda: adapter.poll(run_id), max_retries=self.settings.max_retries, base=self.settings.backoff_base_seconds,
                            cap=self.settings.backoff_max_seconds, sleep=self.sleep, should_stop=self._stopping)
            if st.status != "running":
                return st
            self.sleep(self.poll_interval)


__all__ = ["Executor", "JobStopped", "CostBudgetExhausted", "UncertainRun", "RetryableError"]
