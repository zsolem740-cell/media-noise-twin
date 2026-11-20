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
    """Nincs `verified` érték: független külső tényellenőrzést az 1. verzió nem végez.
    A forrásban ismétlődő állítás nem igazolt: a különböző videók ugyanazt az eredeti forrást is ismételhetik."""
    source_claim = "source_claim"
    repeated_across_sources = "repeated_across_sources"
    unsupported = "unsupported"          # nem ellenőrizhető idézet: soha nem kerül a jelentés megállapításai közé


class FindingCategory(str, Enum):
    tool = "tool"
    product = "product"
    method = "method"
    recommendation = "recommendation"
    claim = "claim"
    warning = "warning"
    other = "other"


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


def compute_plan_hash(plan: "ResearchPlan") -> str:
    """A jóváhagyás ehhez a hashhez kötött: a hash a terv minden mezőjét lefedi a hash mező kivételével."""
    import hashlib
    import json
    data = plan.model_dump(mode="json", exclude={"plan_hash"})
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class ResearchPlan(BaseModel):
    """Strukturált kutatási terv. Csak ellenőrzött, engedélyezett elemeket tartalmazhat."""
    question: str
    platforms: list[Platform]
    languages: list[str] = ["hu", "en"]
    search_queries: list[str] = []
    direct_urls: list[str] = []
    focus_categories: list[FindingCategory] = list(FindingCategory)
    plan_hash: str = ""
    limits: Limits
    estimated_cost_usd: float | None = None
    cost_estimate_note: str = ""
    notes: list[str] = []
    providers: dict[str, str] = {}           # "<platform>:<capability>" -> szolgáltató neve vagy "nincs"
    operations: list[str] = []

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
    auto_generated: bool | None = None       # a platform automatikus (gépi) feliratozása; None = nem ismert
    fetched_at: datetime | None = None


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
    category: FindingCategory
    statement_hu: str
    source_references: list[SourceReference]
    evidence_status: EvidenceStatus = EvidenceStatus.source_claim
    limitations: list[str] = []


class ResearchReport(BaseModel):
    summary: str
    findings: list[Finding]
    repeated_mentions: list[dict]
    contradictions: list[dict]
    missing_information: list[str]
    source_list: list[dict]
    coverage_limitations: list[str]
    unsupported: list[dict] = []             # elutasított, nem alátámasztott javaslatok (állítás + ok); nem megállapítások


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
