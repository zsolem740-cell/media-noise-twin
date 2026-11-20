"""Apify-adapter az `apify-client` hivatalos csomaggal. Az Actor-azonosító, az input-sablon és a mezőleképezés KONFIGURÁLHATÓ,
nincs beégetett Actor. Telepítés előtt a kezelőnek ellenőriznie kell az Actor létezését, input/output sémáját, árazását,
cookie-/bejelentkezési igényét (lásd docs/ACTORS.md) és a `verified_on` mezőt kitöltenie.

Ellenőrzött SDK-hívások (apify-client 3.5.1): ApifyClient(token), .actor(id).start(run_input=, max_total_charge_usd=, max_items=),
.run(id).get(), .run(id).abort(gracefully=), .dataset(id).iterate_items(). A modell soha nem választ Actort.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from ..config import ActorConfig, SecretStr
from ..models import Platform, TranscriptOrigin
from ..util import UncertainOutcome
from .base import (Capability, ProviderNotConfigured, ProviderPermanentError, RawSegment, RunState, TranscriptResult,
                   VideoCandidate, VideoMetadata)


def _dig(obj: Any, path: str | None):
    if not path:
        return None
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def render_input(template: Any, values: dict) -> Any:
    """Helyettesítők: a teljes sztring pontosan "{kulcs}" -> típusos érték; részsztringben szövegként."""
    if isinstance(template, dict):
        return {k: render_input(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [render_input(v, values) for v in template]
    if isinstance(template, str):
        for k, v in values.items():
            if template == "{" + k + "}":
                return v
        for k, v in values.items():
            template = template.replace("{" + k + "}", str(v))
    return template


class ApifyAdapter:
    name = "apify"
    is_fixture = False

    def __init__(self, token: SecretStr | None, actors: dict[str, ActorConfig], client_factory: Callable[[str], Any] | None = None):
        self.actors = actors
        self._token = token
        self._factory = client_factory
        self._client = None

    def _cfg(self, capability: Capability, platform: Platform) -> ActorConfig:
        cfg = self.actors.get(f"{platform.value}:{capability.value}")
        if not cfg or not cfg.actor_id:
            raise ProviderNotConfigured(f"Nincs beállított Actor: {platform.value}:{capability.value}")
        if not cfg.verified_on:
            raise ProviderNotConfigured(f"Az Actor nincs ellenőrzöttként jelölve (verified_on üres): {cfg.actor_id}")
        if cfg.requires_cookies_or_login:
            raise ProviderNotConfigured("Az 1. verzió nem kér platformjelszót vagy session cookie-t: ez az Actor bejelentkezést igényel")
        return cfg

    @property
    def client(self):
        if self._client is None:
            if not self._token:
                raise ProviderNotConfigured("APIFY_TOKEN nincs beállítva")
            if self._factory:
                self._client = self._factory(self._token.reveal())
            else:
                from apify_client import ApifyClient       # csak itt, késve: az offline tesztek nem igénylik
                self._client = ApifyClient(self._token.reveal())
        return self._client

    def supports(self, capability: Capability, platform: Platform) -> bool:
        cfg = self.actors.get(f"{platform.value}:{capability.value}")
        return bool(cfg and cfg.actor_id)

    def estimate_cost(self, capability, platform, units: int) -> float | None:
        cfg = self.actors.get(f"{platform.value}:{capability.value}")
        if not cfg or cfg.price_per_item_usd is None:
            return None            # nincs megbízható becslés: a hívó ezt jelzi
        return round(cfg.price_per_item_usd * units, 6)

    def max_run_cost(self, capability, platform) -> float:
        return self._cfg(capability, platform).max_cost_per_run_usd

    def start(self, capability: Capability, platform: Platform, params: dict) -> str:
        cfg = self._cfg(capability, platform)
        values = {"query": params.get("query", ""), "url": params.get("url", ""), "max_items": params.get("max_results", 1)}
        run_input = render_input(cfg.input_template, values)
        try:
            run = self.client.actor(cfg.actor_id).start(
                run_input=run_input, max_items=int(values["max_items"]) if capability == Capability.search_videos else None,
                max_total_charge_usd=Decimal(str(cfg.max_cost_per_run_usd)))
        except ProviderNotConfigured:
            raise
        except Exception as exc:                      # a kliens saját kivételei; részletes besorolás alább
            code = getattr(exc, "status_code", None)
            if code is not None and 400 <= int(code) < 500 and int(code) != 429:
                raise ProviderPermanentError(f"az Apify elutasította a kérést (HTTP {code})") from exc
            # hálózati hiba, időtúllépés, 5xx, 429: nem tudni, elindult-e a fizetős futás
            raise UncertainOutcome(f"bizonytalan kimenetel az indításnál: {type(exc).__name__}") from exc
        return run.id

    def poll(self, run_id: str) -> RunState:
        run = self.client.run(run_id).get()
        if run is None:
            raise ProviderPermanentError("a futás nem található")
        status = str(getattr(run.status, "value", run.status)).upper()
        cost = getattr(run, "usage_total_usd", None)
        cost = float(cost) if cost is not None else None
        if status in ("READY", "RUNNING"):
            return RunState("running")
        if status == "SUCCEEDED":
            return RunState("succeeded", cost)
        if status in ("ABORTING", "ABORTED"):
            return RunState("aborted", cost)
        return RunState("failed", cost, status)       # FAILED, TIMING-OUT, TIMED-OUT

    def abort(self, run_id: str) -> bool:
        try:
            self.client.run(run_id).abort(gracefully=True)
            return True
        except Exception:                             # best effort: a leállítás nem garantált
            return False

    def _items(self, run_id: str, limit: int) -> list[dict]:
        run = self.client.run(run_id).get()
        if run is None or not getattr(run, "default_dataset_id", None):
            raise ProviderPermanentError("a futásnak nincs kimeneti adathalmaza")
        return list(self.client.dataset(run.default_dataset_id).iterate_items(limit=limit))

    def results(self, capability: Capability, platform: Platform, run_id: str, params: dict):
        cfg = self._cfg(capability, platform)
        om = cfg.output_map
        items = self._items(run_id, limit=max(1, int(params.get("max_results", 50))) if capability == Capability.search_videos else 5000)
        if capability == Capability.search_videos:
            out = []
            for it in items:
                url = _dig(it, om.get("url"))
                if isinstance(url, str):
                    out.append(VideoCandidate(url, _dig(it, om.get("title"))))
            return out
        if capability == Capability.fetch_video_metadata:
            it = items[0] if items else {}
            dur = _dig(it, om.get("duration_seconds"))
            return VideoMetadata(_dig(it, om.get("title")), _dig(it, om.get("creator")), _dig(it, om.get("published_at")),
                                 float(dur) if isinstance(dur, (int, float)) else None, raw_ref=f"apify:run:{run_id}")
        # fetch_transcript: a szegmenseket a kezelő leképezése adja; nincs találgatás
        segs: list[RawSegment] = []
        raw = _dig(items, om.get("segments")) if om.get("segments") else None
        if isinstance(raw, list):
            for s in raw:
                text = _dig(s, om.get("segment_text", "text"))
                if isinstance(text, str) and text.strip():
                    st, en = _dig(s, om.get("segment_start")), _dig(s, om.get("segment_end"))
                    segs.append(RawSegment(text, float(st) if isinstance(st, (int, float)) else None, float(en) if isinstance(en, (int, float)) else None))
        elif om.get("text"):
            whole = _dig(items, om["text"])
            if isinstance(whole, str) and whole.strip():
                segs.append(RawSegment(whole))
        lang = _dig(items, om.get("language")) if om.get("language") else None
        origin = TranscriptOrigin(cfg.transcript_origin)
        return TranscriptResult(lang if lang in ("hu", "en") else params.get("language", "hu"), origin, segs)
