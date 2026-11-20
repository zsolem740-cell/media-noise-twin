"""Adatmodellek (Pydantic). A nyers szolgáltatói válaszokat az adapterek ezekre normalizálják."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class JobStatus(str, Enum):
    queued = "queued"
    planning = "planning"
    awaiting_approval = "awaiting_approval"
    running = "running"
    completed = "completed"
    partially_completed = "partially_completed"
    failed = "failed"
    cancelled = "cancelled"


TERMINAL_STATUSES = {JobStatus.completed, JobStatus.partially_completed, JobStatus.failed, JobStatus.cancelled}


class Platform(str, Enum):
    youtube = "youtube"
    tiktok = "tiktok"


class AccessStatus(str, Enum):
    ok = "ok"
    no_transcript = "no_transcript"
    unavailable = "unavailable"
    error = "error"


class TranscriptOrigin(str, Enum):
    platform_caption = "platform_caption"
    speech_to_text = "speech_to_text"


class EvidenceStatus(str, Enum):
    """Az `independently_verified` értéket az 1. verzió soha nem állítja elő: külső ellenőrzést nem végez."""
    creator_claim = "creator_claim"
    repeated_across_videos = "repeated_across_videos"
    independently_verified = "independently_verified"


class StepStatus(str, Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
    skipped = "skipped"
    uncertain = "uncertain"       # a kimenetel bizonytalan (pl. hálózati megszakadás): kézi/állapot-ellenőrzés kell, vak újraindítás nincs


class Limits(BaseModel):
    max_videos: int = Field(10, ge=1)
    max_total_video_minutes: float = Field(120.0, gt=0)
    llm_token_budget: int = Field(200_000, ge=1000)
    provider_cost_budget_usd: float = Field(2.0, ge=0)
    max_runtime_seconds: int = Field(1800, ge=30)
    max_parallel_runs: int = Field(2, ge=1)


class ResearchPlan(BaseModel):
    """Strukturált kutatási terv. Csak ellenőrzött, engedélyezett elemeket tartalmazhat."""
    question: str
    platforms: list[Platform]
    languages: list[str] = ["hu", "en"]
    search_queries: list[str] = []
    direct_urls: list[str] = []
    focus_categories: list[str] = ["eszköz", "megoldás", "előny", "probléma"]
    limits: Limits
    estimated_cost_usd: float | None = None
    cost_estimate_note: str = ""
    notes: list[str] = []

    @field_validator("languages")
    @classmethod
    def _langs(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in ("hu", "en")]
        if bad:
            raise ValueError(f"nem támogatott nyelv: {bad}")
        return v


class TranscriptSegment(BaseModel):
    id: str
    start_seconds: float | None = None
    end_seconds: float | None = None
    text: str


class Transcript(BaseModel):
    id: str
    video_source_id: str
    language: str
    origin: TranscriptOrigin
    segments: list[TranscriptSegment]
    timestamps_available: bool
    content_hash: str
    provider: str


class VideoSource(BaseModel):
    id: str
    platform: Platform
    platform_video_id: str
    canonical_url: str
    title: str | None = None
    creator: str | None = None
    published_at: datetime | None = None
    duration_seconds: float | None = None
    retrieved_at: datetime
    provider: str
    provider_run_id: str | None = None
    access_status: AccessStatus = AccessStatus.ok
    raw_metadata_reference: str | None = None
    is_fixture: bool = False


class SourceReference(BaseModel):
    video_source_id: str
    transcript_segment_ids: list[str]
    supporting_quote: str
    timestamp: float | None = None
    semantic_check: str = "not_checked"      # not_checked | consistent | doubtful: heurisztikus, nem tévedhetetlen


class Finding(BaseModel):
    id: str
    research_job_id: str
    category: str
    statement: str
    source_references: list[SourceReference]
    evidence_status: EvidenceStatus = EvidenceStatus.creator_claim
    limitations: list[str] = []


class ResearchReport(BaseModel):
    summary: str
    findings: list[Finding]
    repeated_mentions: list[dict]
    contradictions: list[dict]
    missing_information: list[str]
    source_list: list[dict]
    coverage_limitations: list[str]


class ResearchJob(BaseModel):
    id: str
    request: str
    platforms: list[Platform]
    languages: list[str]
    status: JobStatus
    approved_plan: ResearchPlan | None = None
    limits: Limits
    estimated_cost: float | None = None
    recorded_cost: float = 0.0
    created_at: datetime
    updated_at: datetime
