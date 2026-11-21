"""Gemini-adapter az `LLMClient` felülethez. A kérés- és válaszformátum (generateContent: systemInstruction, contents, generationConfig,
x-goog-api-key fejléc, candidates/usageMetadata) a projekt meglévő, ellenőrzött `validation/hu_pilot` kódjából származik; az átvitelt
(`live.transport.HttpTransport`: csak https, nincs átirányítás-követés, a kulcs csak fejlécben, kulcsmentes kivételek) és a borítékfeldolgozást
(`providers._envelope`) újrahasznosítjuk, nem másoljuk.

Szabályok (CLAUDE.md): a modellnév KONFIGURÁLHATÓ, nincs beégetett alapérték; a kulcs csak környezeti változóból jön (GEMINI_API_KEY), soha nem kerül
naplóba vagy kimenetbe; kvótakimerülésnél a futás megáll (nincs szolgáltatóváltás, nincs fizetős csomagra váltás); minden kérésnél naplózzuk a szolgáltatót,
a modellt, a kimenetelt és a tokenszámot. Valódi hívást ez a repó tesztjei és az ügynök nem indítanak: csak hamis átvitellel tesztelt.
"""
from __future__ import annotations

import json
import time
from typing import Callable

from validation.hu_pilot.modelrun import Raw, TransportTimeout
from validation.hu_pilot.providers import Outcome, _envelope

from .llm import LLMQuotaExhausted, LLMRejected, LLMResult, LLMTransient, LLMUnavailable
from .util import get_logger

log = get_logger("video_research.llm.gemini")

Transport = Callable[[str, dict], Raw]          # (modellnév, kérés-törzs) -> nyers válasz


class GeminiLLM:
    provider = "gemini"
    kind = "ai"

    def __init__(self, model: str, transport: Transport, temperature: float = 0.0, min_interval_s: float = 0.0, thinking_levels: dict[str, str] | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        if not isinstance(model, str) or not model.strip():
            raise LLMUnavailable("A Gemini modellneve nincs beállítva (VR_GEMINI_MODEL): nincs beégetett alapérték.")
        self.model, self._transport, self.temperature = model.strip(), transport, temperature
        # schema_name -> thinkingConfig.thinkingLevel (dokumentált enum: MINIMAL|LOW|MEDIUM|HIGH|XHIGH; gemini-3.6-flash: minimal/low/medium/high). Alapból NINCS beállítva (a modell alapértéke).
        self.thinking_levels = dict(thinking_levels or {})
        self.min_interval_s, self._sleep, self._clock, self._last = float(min_interval_s), sleep, clock, None     # kérések közti minimális idő (ingyenes szint percenkénti korlátja)
        self.calls: list[dict] = []              # kérésenként: szolgáltató, modell, kimenetel, tokenek (kulcs/szöveg nélkül)

    def __repr__(self) -> str:
        return f"GeminiLLM(model={self.model!r})"

    def _record(self, outcome: str, tokens: int | None) -> None:
        self.calls.append({"provider": self.provider, "model": self.model, "outcome": outcome, "tokens": tokens})
        log.info("llm kérés: provider=%s model=%s outcome=%s tokens=%s", self.provider, self.model, outcome, tokens)

    def complete_json(self, *, system: str, user: str, schema_name: str, max_tokens: int) -> LLMResult:
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": self.temperature, "maxOutputTokens": int(max_tokens)}}
        if self._last is not None and self.min_interval_s > 0:
            wait = self.min_interval_s - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()
        level = self.thinking_levels.get(schema_name)
        if level:
            body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": level}
        try:
            raw = self._transport(self.model, body)
        except TransportTimeout:
            self._record("timeout", None)
            raise LLMTransient("időtúllépés") from None
        except ConnectionError:
            self._record("network_error", None)
            raise LLMTransient("hálózati hiba") from None
        env = _envelope("gemini", raw.status, raw.text, raw.retry_after)
        if isinstance(env, Outcome):
            self._record(env.kind, (env.usage or {}).get("total_tokens"))
            if env.kind in ("quota_day", "billing"):
                raise LLMQuotaExhausted(f"{env.kind}: {env.detail}")         # a futás megáll; a kész videók megmaradnak
            if env.kind in ("quota_minute", "transient"):
                raise LLMTransient(env.detail, env.retry_after)
            raise LLMRejected(f"{env.kind}: {env.detail}")                   # blocked, truncated, empty, invalid, fatal
        text, usage, _finish, returned_model = env
        try:
            data = json.loads(text)
        except ValueError:
            self._record("invalid_json", usage.get("total_tokens"))
            raise LLMRejected("invalid: a modell kimenete nem érvényes JSON") from None
        if not isinstance(data, dict):
            self._record("invalid_shape", usage.get("total_tokens"))
            raise LLMRejected("invalid: a kimenet nem JSON-objektum")
        tokens = usage.get("total_tokens")
        if tokens is None:                                                   # ismeretlen tokenszám: nem hallgatjuk el, durva becslés, jelölve a naplóban
            tokens = max(1, (len(system) + len(user) + len(text)) // 3)
            self._record("ok_tokens_estimated", tokens)
        else:
            self._record("ok", tokens)
        return LLMResult(data, tokens)


def build_gemini(model: str | None, api_key: str | None, timeout_s: float = 60.0, base_url: str | None = None, min_interval_s: float = 13.0,
                 thinking_levels: dict[str, str] | None = None) -> GeminiLLM:
    """Valódi átvitellel összerakott adapter (a kulcsot csak a HttpTransport tartja). Hívni csak a felhasználó saját, jóváhagyott futásához szabad."""
    from validation.hu_pilot.live.transport import HttpTransport
    if not api_key:
        raise LLMUnavailable("GEMINI_API_KEY nincs beállítva a környezetben.")
    return GeminiLLM(model or "", HttpTransport("gemini", api_key, timeout_s, base_url), min_interval_s=min_interval_s, thinking_levels=thinking_levels)   # 13 s: a projekt pilot-konfigurációjának értéke (min_interval_s)
