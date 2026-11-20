"""Szolgáltatófüggetlen LLM-felület. Az MI csak értelmez, javasol és kinyer: eszközt, titkot, hálózatot nem kap.

A felület nem függ a szolgáltató válaszformátumától: `complete_json` egy már értelmezett dict-et és a tokenszámot adja; a szolgáltatói boríték
feldolgozása az adapter (pl. `llm_gemini.GeminiLLM`) dolga. Az első adapter a projektben már engedélyezett Gemini. Az `anthropic` adapter továbbra sincs
(a `config/guard_policy.json` tiltja a harmadik szolgáltatót). Minden adapter megad `provider`, `model` és `kind` ("ai" | "baseline") jellemzőt."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LLMUnavailable(Exception):
    """Nincs beállított vagy elérhető modell."""


class LLMQuotaExhausted(LLMUnavailable):
    """Napi kvóta vagy számlázási korlát: a futás megáll, a kész eredmények megmaradnak; nincs szolgáltatóváltás és nincs fizetős csomagra váltás."""


class LLMTransient(Exception):
    """Átmeneti hiba (percenkénti kvóta, 5xx, hálózat): korlátozottan újrapróbálható."""

    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


class LLMRejected(Exception):
    """A szolgáltató blokkolta, csonkolta vagy érvénytelen kimenetet adott ehhez a kéréshez: csak az adott videó marad ki, nincs kitalált pótlás."""


@dataclass
class LLMResult:
    data: dict
    tokens: int          # a ténylegesen felhasznált (bemenet+kimenet) tokenek; ismeretlen esetben a hívó becslése, jelölve a naplóban


class LLMClient(Protocol):
    provider: str
    model: str
    kind: str          # "ai" vagy "baseline": a jelentés ez alapján jelöli, hogy AI-elemzés-e

    def complete_json(self, *, system: str, user: str, schema_name: str, max_tokens: int) -> LLMResult: ...


class NullLLM:
    provider, model, kind = "none", "", "none"

    """Nincs beállított modell: minden hívás érthető hibával áll meg, kitalált kimenet nincs."""
    def complete_json(self, *, system: str, user: str, schema_name: str, max_tokens: int) -> LLMResult:
        raise LLMUnavailable("Nincs beállított LLM-szolgáltató. A kinyerés és a jelentés nem készíthető el modell nélkül.")


def estimate_tokens(text: str) -> int:
    """Durva előzetes becslés (kb. 3 karakter/token magyar szövegnél) a keret ELŐZETES ellenőrzéséhez; a tényleges érték az LLMResult.tokens."""
    return max(1, len(text) // 3)


class RetryingLLM:
    """Korlátozott újrapróbálás (exponenciális visszalépés jitterrel) az átmeneti hibákra; a szolgáltató Retry-After jelzését is figyelembe veszi.
    A kvóta- és elutasítási hibákat nem próbálja újra. A burkolt kliens jellemzőit átadja."""

    def __init__(self, inner, *, max_retries: int, base: float, cap: float, sleep, should_stop=lambda: False):
        self.inner, self.max_retries, self.base, self.cap, self.sleep, self.should_stop = inner, max_retries, base, cap, sleep, should_stop
        self.provider, self.model, self.kind = (getattr(inner, "provider", "unknown"), getattr(inner, "model", ""), getattr(inner, "kind", "unknown"))

    def complete_json(self, *, system: str, user: str, schema_name: str, max_tokens: int) -> LLMResult:
        from .util import backoff_delay
        attempt = 0
        while True:
            try:
                return self.inner.complete_json(system=system, user=user, schema_name=schema_name, max_tokens=max_tokens)
            except LLMTransient as exc:
                if attempt >= self.max_retries or self.should_stop():
                    raise
                wait = min(self.cap, exc.retry_after) if exc.retry_after else backoff_delay(attempt, self.base, self.cap)
                self.sleep(wait)
                attempt += 1
