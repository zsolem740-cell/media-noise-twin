"""Beállítások környezeti változókból. A titkok csak szerveroldali környezetből jönnek, és soha nem kerülnek naplóba."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .models import Limits

HARD_TRIAL_MAX_VIDEOS = 10        # az első valódi próba legfeljebb 10 videó


class SecretStr(str):
    """Titok: repr/str kimenete mindig maszkolt; az értéke csak a .reveal() hívással érhető el."""
    def __repr__(self) -> str:
        return "SecretStr('***')"

    def __str__(self) -> str:
        return "***"

    def reveal(self) -> str:
        return str.__str__(self)


@dataclass
class ActorConfig:
    """Egy engedélyezett Apify Actor beállítása. Az azonosítót és a leképezést a kezelő adja meg, miután ellenőrizte az aktuális sémát."""
    actor_id: str
    capability: str                      # search_videos | fetch_video_metadata | fetch_transcript
    input_template: dict = field(default_factory=dict)   # {"{url}": ..., "{query}": ..., "{max_items}": ...} helyettesítők a sztringekben
    output_map: dict = field(default_factory=dict)       # normalizált mező -> nyers mező (pontozott útvonal)
    requires_cookies_or_login: bool = False
    verified_on: str = ""                # az ellenőrzés dátuma (dokumentációs kötelezettség)
    pricing_note: str = ""
    max_cost_per_run_usd: float = 0.5
    price_per_item_usd: float | None = None   # ismert egységár esetén becslés; különben a becslés "nem megbízható"
    transcript_origin: str = "platform_caption"   # platform_caption | speech_to_text


@dataclass
class Settings:
    database_url: str = "sqlite:///video_research.db"
    mode: str = "dev"                    # dev (fixture engedett) | production (fixture tiltott)
    api_token: SecretStr | None = None
    apify_token: SecretStr | None = None
    limits: Limits = field(default_factory=Limits)
    allowed_platforms: tuple[str, ...] = ("youtube", "tiktok")
    actors: dict[str, ActorConfig] = field(default_factory=dict)   # kulcs: "<platform>:<capability>"
    lease_seconds: int = 60
    max_retries: int = 3
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 30.0
    max_transcript_chars: int = 200_000
    data_retention_days: int = 90
    allow_cloud_transcription: bool = False      # a felhős beszédfelismerés külön engedély; rejtett váltás nincs (jelenleg nincs ilyen útvonal)

    def validate(self) -> None:
        if self.mode not in ("dev", "production"):
            raise ValueError("VR_MODE értéke dev vagy production lehet")
        if self.limits.max_videos > HARD_TRIAL_MAX_VIDEOS and os.environ.get("VR_ALLOW_MORE_THAN_TRIAL") != "1":
            raise ValueError(f"max_videos legfeljebb {HARD_TRIAL_MAX_VIDEOS} lehet az első valódi próbáig (VR_ALLOW_MORE_THAN_TRIAL=1 kiváltja)")
        if self.mode == "production" and not self.api_token:
            raise ValueError("production módban VR_API_TOKEN kötelező")


def load_settings(env: dict | None = None) -> Settings:
    e = os.environ if env is None else env
    alias = {"DATABASE_URL": "VR_DATABASE_URL", "APP_API_KEY": "VR_API_TOKEN", "DEFAULT_MAX_VIDEOS": "VR_MAX_VIDEOS",
             "DEFAULT_MAX_TOTAL_MINUTES": "VR_MAX_VIDEO_MINUTES", "DEFAULT_MAX_COST_USD": "VR_COST_BUDGET_USD"}
    e = {**e, **{new: e[old] for old, new in alias.items() if old in e and new not in e}}
    limits = Limits(
        max_videos=int(e.get("VR_MAX_VIDEOS", 10)),
        max_total_video_minutes=float(e.get("VR_MAX_VIDEO_MINUTES", 120)),
        llm_token_budget=int(e.get("VR_LLM_TOKEN_BUDGET", 200_000)),
        provider_cost_budget_usd=float(e.get("VR_COST_BUDGET_USD", 2.0)),
        max_runtime_seconds=int(e.get("VR_MAX_RUNTIME_SECONDS", 1800)),
        max_parallel_runs=int(e.get("VR_MAX_PARALLEL_RUNS", 2)),
    )
    actors: dict[str, ActorConfig] = {}
    path = e.get("VR_ACTORS_FILE")
    if path:
        for key, raw in json.loads(Path(path).read_text(encoding="utf-8")).items():
            actors[key] = ActorConfig(**raw)
    s = Settings(
        database_url=e.get("VR_DATABASE_URL", "sqlite:///video_research.db"),
        mode=e.get("VR_MODE", "dev"),
        api_token=SecretStr(e["VR_API_TOKEN"]) if e.get("VR_API_TOKEN") else None,
        apify_token=SecretStr(e["APIFY_TOKEN"]) if e.get("APIFY_TOKEN") else None,
        limits=limits,
        actors=actors,
        lease_seconds=int(e.get("VR_LEASE_SECONDS", 60)),
        data_retention_days=int(e.get("DATA_RETENTION_DAYS", 90)),
        allow_cloud_transcription=e.get("ALLOW_CLOUD_TRANSCRIPTION", "false").lower() == "true",
    )
    s.validate()
    return s
