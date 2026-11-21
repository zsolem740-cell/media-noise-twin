"""Adatmodellek (Pydantic). A nyers szolgáltatói válaszokat az adapterek ezekre normalizálják."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, computed_field, field_validator


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
    manual = "manual"            # felhasználói átiratimport link nélkül: nem platformintegráció


class AccessStatus(str, Enum):
    ok = "ok"
    no_transcript = "no_transcript"
    unavailable = "unavailable"
    error = "error"


class TranscriptOrigin(str, Enum):
    platform_caption = "platform_caption"
    speech_to_text = "speech_to_text"
    user_provided_transcript = "user_provided_transcript"      # explicit felhasználói import; nem igazolja az átirat–videó egyezést


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
    step = "step"                        # konkrét lépés
    prerequisite = "prerequisite"        # előfeltétel
    cost = "cost"                        # elhangzott költség
    experience = "experience"            # egyedi tapasztalat
    limitation = "limitation"            # hiba, korlát
    other = "other"


class Relevance(str, Enum):
    """HASZNOSSÁG-tengely (a kutatási kérdéshez): nem azonos az alátámasztottsággal (EvidenceStatus, szemantikai ellenőrzés)."""
    direct = "direct"
    partial = "partial"


class Disposition(str, Enum):
    keep = "keep"        # megtartandó információ
    lead = "lead"        # ellenőrizendő nyom


class Stance(str, Enum):
    supports = "supports"
    counterexample = "counterexample"
    neutral = "neutral"


class SkipReason(str, Enum):
    irrelevant = "irrelevant"
    not_concrete = "not_concrete"
    unverified_quote = "unverified_quote"
    already_known = "already_known"                      # a felhasználó által megadott, már rögzített információ
    duplicate_source_attached = "duplicate_source_attached"   # ismétlés: az új forrás a meglévő megállapításhoz csatolva
    malformed = "malformed"
    lead_without_check = "lead_without_check"            # részben releváns/kétes, de nem nevezhető meg a hiányzó ellenőrzés: nem nyom, kihagyva
    extraction_unreliable = "extraction_unreliable"      # a kinyerés megbízhatatlan (pl. kétes jelentésbeli egyezés): hibakezelés, NEM nyom
    suspected_injection = "suspected_injection"          # a forrásszöveg utasításnak látszó részlete: nem információ


class FeedbackLabel(str, Enum):
    useful = "useful"
    not_relevant = "not_relevant"
    already_known = "already_known"          # NEM hamis és NEM értéktelen: csak a felhasználó számára nem új
    extracted_wrong = "extracted_wrong"
    needs_check = "needs_check"


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
    imported_sources: int = 0                  # felhasználói átiratimport: a videó–átirat egyezést nem ellenőrizzük
    known_information: list[str] = []          # a felhasználó által már rögzített információ: ennek puszta ismétlése nem kerül a megtartandók közé
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
    transcript_link_status: str = "not_applicable"   # user_asserted_unverified: a felhasználó állítja, hogy az átirat ehhez a videóhoz tartozik; nem ellenőriztük


class SourceReference(BaseModel):
    video_source_id: str
    transcript_segment_ids: list[str]
    supporting_quote: str
    timestamp: float | None = None
    semantic_check: str = "not_checked"      # not_checked | consistent | doubtful: heurisztikus, nem tévedhetetlen
    quote_language: str | None = None        # az idézet NYELVE (az átirat nyelve): az idézet mindig az eredeti nyelvű szöveg
    role: str = "support"                    # support | qualifier: a „minősítő” hivatkozás a következő mondatban álló feltételt/cáfolatot őrzi meg


class Finding(BaseModel):
    id: str
    research_job_id: str
    category: FindingCategory
    statement_hu: str
    source_references: list[SourceReference]
    evidence_status: EvidenceStatus = EvidenceStatus.source_claim
    limitations: list[str] = []
    # --- hasznosság (külön az alátámasztottságtól) ---
    relevance: Relevance = Relevance.direct
    concrete: bool = True
    disposition: Disposition = Disposition.keep
    lead_reasons: list[str] = []
    verification_question: str | None = None   # KÖTELEZŐ nyomnál: megnevezi a hiányzó ellenőrzést; megtartottnál nincs
    extends_known: str | None = None           # a felhasználó ismert információja, amelyhez ez új feltételt/ellenpéldát/verziót ad
    # --- feltétel / ellenpélda / verzió: nem mosható össze az általános állítással ---
    condition: str | None = None
    stance: Stance = Stance.supports
    version: str | None = None
    related_ids: list[str] = []
    why_relevant: str | None = None          # rövid, magyar besorolási indok a kérdéshez viszonyítva (megtartott tételnél)
    statement_is_translation: bool = False   # a statement_hu az eredeti nyelvű forrás magyar tartalmi összefoglalása/fordítása, NEM idézet

    @computed_field  # type: ignore[prop-decorator]
    @property
    def report_bucket(self) -> str:
        """keep | lead (a kihagyott részletek nem Finding, hanem FilterEntry: report_bucket = skipped)."""
        return self.disposition.value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def source_support_status(self) -> str:
        checks = [r.semantic_check for r in self.source_references]
        if not self.source_references:
            return "unsupported"
        if "doubtful" in checks:
            return "support_doubtful"
        if checks and all(c == "consistent" for c in checks):
            return "supported_by_passage"
        return "quote_found_support_unchecked"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def verification_status(self) -> str:
        return "not_externally_verified"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def source_refs(self) -> list[dict]:
        return [{"video_source_id": r.video_source_id, "segment_ids": r.transcript_segment_ids, "timestamp": r.timestamp,
                 "quote": r.supporting_quote, "quote_language": r.quote_language} for r in self.source_references]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def classification_reason(self) -> str:
        if self.disposition == Disposition.lead:
            return "; ".join(self.lead_reasons) or "ellenőrzés szükséges"
        return self.why_relevant or "releváns, konkrét, programozottan igazolt idézettel"


# ---- Leképezés a megbeszélt tengelyekre (levezetett nézetek, nem külön tárolt állapot) ----
class SourceSupport(str, Enum):
    """source_support_status: a hivatkozott forrásrészlet és az állítás viszonya. NEM az igazság és NEM az ismétlődés."""
    supported_by_passage = "supported_by_passage"                  # az idézet megvan, és a külön (heurisztikus) szemantikai ellenőrzés egyezőnek ítélte
    quote_found_support_unchecked = "quote_found_support_unchecked"  # az idézet programozottan megvan; a jelentésbeli egyezést nem ellenőriztük
    support_doubtful = "support_doubtful"                          # az idézet megvan, de a szemantikai ellenőrzés kétesnek ítélte
    unsupported = "unsupported"                                    # nincs ellenőrizhető idézet (soha nem megtartott tétel)


class VerificationStatus(str, Enum):
    """verification_status: FÜGGETLEN KÜLSŐ ellenőrzés. Az 1. verzió nem végez ilyet: az érték mindig not_externally_verified."""
    not_externally_verified = "not_externally_verified"
    externally_verified = "externally_verified"                    # fenntartva; ez a kód soha nem állítja elő


class FilterEntry(BaseModel):
    """Szűrési naplóbejegyzés: a KIHAGYOTT (vagy ismétlésként csatolt) részlet rövid indokkal. Nem minden szegmens kap bejegyzést,
    csak a javaslatba került jelöltek; a javaslatba sem került szegmensek számát a `filter_stats` összesíti."""
    video_source_id: str
    segment_ids: list[str] = []
    snippet: str
    reason_code: SkipReason
    reason_hu: str
    finding_id: str | None = None


class ResearchReport(BaseModel):
    summary: str
    findings: list[Finding]
    repeated_mentions: list[dict]
    contradictions: list[dict]
    missing_information: list[str]
    source_list: list[dict]
    coverage_limitations: list[str]
    unchecked_findings: list[dict] = []      # kinyert, de a szemantikai ellenőrzésen NEM átesett tételek (keret/hiba miatt): nem eredmény, nem megállapítás
    coverage: dict = {}                      # erőforráskorlátok miatti lefedettség (nem tartalmi kvóta): lásd report.build_report
    known_information_matches: list[dict] = []   # a felhasználó ismert információihoz talált újabb források (nem növelik a fő jelentést, nem független megerősítés)
    no_result_note: str | None = None        # pl. „Nem találtam a feltételeknek megfelelő információt.”
    filter_log: list[FilterEntry] = []
    filter_stats: dict = {}
    analysis_method: str = "unknown"         # ai_semantic | keyword_baseline | none: a jelentés megmondja, mi állította elő
    analysis_model: dict = {}                # {"provider":…, "model":…}; baseline esetén üres
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
