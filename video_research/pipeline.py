"""A feldolgozási folyamat. Minden lépés állapota tárolt, újraindítás után a kész lépések kimaradnak."""
from __future__ import annotations

import hashlib
import time
from datetime import datetime
from typing import Callable

from .adapters.base import AdapterRegistry, Capability, ProviderNotConfigured, ProviderPermanentError
from .config import Settings
from .db import Store
from .executor import CostBudgetExhausted, Executor, JobStopped, UncertainRun
from .extraction import ExtractionStats, TokenBudgetExceeded, extract_findings, semantic_check
from .llm import LLMClient, LLMUnavailable
from .merge import merge_findings
from .models import (AccessStatus, JobStatus, Platform, ResearchPlan, StepStatus, Transcript, TranscriptSegment, VideoSource)
from .planner import build_plan
from .report import build_report
from .urls import UrlRejected, normalize_video_url
from .util import RetryableError, get_logger, new_id, now, parse_iso

log = get_logger("video_research.pipeline")


class Pipeline:
    def __init__(self, store: Store, settings: Settings, registry: AdapterRegistry, llm: LLMClient, *, semantic: bool = True,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic, poll_interval: float = 2.0):
        self.store, self.settings, self.registry, self.llm, self.semantic = store, settings, registry, llm, semantic
        self.sleep, self.clock, self.poll_interval = sleep, clock, poll_interval

    # ---- tervezés ----
    def plan_job(self, jid: str, requested_platforms: list[str] | None = None) -> None:
        job = self.store.get_job(jid)
        self.store.set_status(jid, JobStatus.planning)
        plan = build_plan(job.request, self.settings, self.registry, llm=self.llm, requested_limits=job.limits,
                          requested_platforms=[p.value for p in job.platforms] or None)
        if not plan.platforms or (not plan.direct_urls and not plan.search_queries):
            self.store.set_status(jid, JobStatus.failed, error="A kérésből nem készíthető érvényes terv (nincs engedélyezett platform vagy kereshető kifejezés/link).")
            return
        self.store.set_status(jid, JobStatus.awaiting_approval, plan=plan.model_dump_json(), estimated_cost=plan.estimated_cost_usd)

    # ---- futtatás ----
    def run_job(self, jid: str, heartbeat: Callable[[], bool]) -> JobStatus:
        job = self.store.get_job(jid)
        plan = job.approved_plan
        started = self.clock()
        limits = plan.limits

        def check() -> None:
            if self.store.get_field(jid, "cancel_requested"):
                raise JobStopped("cancelled")
            if self.clock() - started > limits.max_runtime_seconds:
                raise JobStopped("runtime_limit")
            if not heartbeat():
                raise JobStopped("lease_lost")

        self.store.set_status(jid, JobStatus.running)
        ex = Executor(self.store, self.settings, check, self.sleep, self.poll_interval)
        stats = ExtractionStats()
        stats.tokens = self.store.get_field(jid, "llm_tokens_used") or 0
        problems: list[str] = []
        stop_reason: str | None = None
        try:
            self._search_and_collect(jid, plan, ex, check, problems)
            self._metadata(jid, plan, ex, check, problems)
            self._transcripts(jid, plan, ex, check, problems)
            self._extract(jid, plan, check, stats, problems)
        except JobStopped as s:
            stop_reason = s.reason
            if s.reason == "lease_lost":
                log.warning("lease elveszett, a feldolgozás megáll (egy másik worker folytatja)")
                return JobStatus.running
        except CostBudgetExhausted as exc:
            problems.append(str(exc))
            stop_reason = "cost_budget"
        except UncertainRun as exc:
            problems.append(str(exc))
        except (ProviderNotConfigured, LLMUnavailable) as exc:
            problems.append(f"Szolgáltatás nem elérhető: {exc}")
            stop_reason = "unavailable"
        return self._finish(jid, plan, ex, stats, problems, stop_reason)

    def _step_done(self, steps, name) -> bool:
        return name in steps and steps[name][0] in (StepStatus.done, StepStatus.skipped)

    def _search_and_collect(self, jid, plan: ResearchPlan, ex: Executor, check, problems) -> None:
        steps = self.store.get_steps(jid)
        if self._step_done(steps, "collect"):
            return
        cands: list[tuple[Platform, str, str]] = []                      # (platform, id, canonical_url)
        for u in plan.direct_urls:
            ref = normalize_video_url(u, tuple(self.settings.allowed_platforms))
            cands.append((ref.platform, ref.video_id, ref.canonical_url))
        for platform in plan.platforms:
            for q in plan.search_queries:
                name = f"search:{platform.value}:{hashlib.sha1(q.encode()).hexdigest()[:8]}"
                if self._step_done(steps, name):
                    cands += [(Platform(p), i, c) for p, i, c in steps[name][1].get("found", [])]
                    continue
                check()
                self.store.set_step(jid, name, StepStatus.running)
                try:
                    adapter = self.registry.get(Capability.search_videos, platform)
                    run_id, found, state = ex.run(jid, name, adapter, Capability.search_videos, platform,
                                                  {"query": q, "max_results": plan.limits.max_videos}, plan.limits.provider_cost_budget_usd)
                except (ProviderPermanentError, UncertainRun, RetryableError) as exc:
                    self.store.set_step(jid, name, StepStatus.uncertain if isinstance(exc, UncertainRun) else StepStatus.failed, {"error": str(exc)})
                    problems.append(f"Keresés sikertelen ({platform.value}): {exc}")
                    if isinstance(exc, ProviderNotConfigured):
                        raise
                    continue
                refs = []
                for c in found:
                    try:
                        r = normalize_video_url(c.url, tuple(self.settings.allowed_platforms))
                        refs.append((r.platform.value, r.video_id, r.canonical_url))
                    except UrlRejected:
                        problems.append("A keresés egy nem engedélyezett/értelmezhetetlen linket adott, kihagyva.")
                self._account(jid, state)
                self.store.set_step(jid, name, StepStatus.done, {"found": refs, "provider_run_id": run_id})
                cands += [(Platform(p), i, c) for p, i, c in refs]
        seen: set[tuple[str, str]] = set()
        added = 0
        for platform, vid, url in cands:                                  # F. duplikált videók kiszűrése
            if (platform.value, vid) in seen:
                continue
            seen.add((platform.value, vid))
            if added >= plan.limits.max_videos:
                problems.append(f"A videószám-keret ({plan.limits.max_videos}) miatt további találatok kimaradtak.")
                break
            v = VideoSource(id=new_id("vid"), platform=platform, platform_video_id=vid, canonical_url=url, retrieved_at=now(),
                            provider="pending", access_status=AccessStatus.ok)
            if self.store.add_video(jid, v):
                added += 1
        self.store.set_step(jid, "collect", StepStatus.done, {"videos": added})

    def _account(self, jid, state) -> None:
        if state.cost_usd is not None:
            self.store.add_usage(jid, cost=state.cost_usd)

    def _metadata(self, jid, plan, ex, check, problems) -> None:
        total_minutes = 0.0
        for v in self.store.videos(jid):
            name = f"meta:{v.id}"
            steps = self.store.get_steps(jid)
            if self._step_done(steps, name):
                total_minutes += (v.duration_seconds or 0) / 60
                continue
            check()
            self.store.set_step(jid, name, StepStatus.running)
            adapter = None
            try:
                adapter = self.registry.get(Capability.fetch_video_metadata, v.platform)
                run_id, md, state = ex.run(jid, name, adapter, Capability.fetch_video_metadata, v.platform, {"url": v.canonical_url}, plan.limits.provider_cost_budget_usd)
            except (ProviderPermanentError, UncertainRun, RetryableError) as exc:
                self.store.set_step(jid, name, StepStatus.uncertain if isinstance(exc, UncertainRun) else StepStatus.failed, {"error": str(exc)})
                v.access_status = AccessStatus.error
                v.provider = adapter.name if adapter else v.provider
                self.store.update_video(jid, v)
                problems.append(f"Metaadat nem érhető el ({v.canonical_url}): {exc}")
                continue
            v.title, v.creator, v.duration_seconds = md.title, md.creator, md.duration_seconds
            v.published_at = _dt(md.published_at)
            v.provider, v.provider_run_id, v.raw_metadata_reference, v.is_fixture = adapter.name, run_id, md.raw_ref, adapter.is_fixture
            v.retrieved_at = now()
            if v.duration_seconds is not None and total_minutes + v.duration_seconds / 60 > plan.limits.max_total_video_minutes:
                v.access_status = AccessStatus.unavailable
                self.store.update_video(jid, v)
                self.store.set_step(jid, name, StepStatus.skipped, {"reason": "video_minutes_limit"})
                problems.append(f"A feldolgozandó videóperc-keret miatt kihagyva: {v.canonical_url}")
                continue
            total_minutes += (v.duration_seconds or 0) / 60
            self._account(jid, state)
            self.store.update_video(jid, v)
            self.store.set_step(jid, name, StepStatus.done)

    def _transcripts(self, jid, plan, ex, check, problems) -> None:
        for v in self.store.videos(jid):
            if v.access_status != AccessStatus.ok:
                continue
            name = f"tr:{v.id}"
            if self._step_done(self.store.get_steps(jid), name):
                continue
            check()
            self.store.set_step(jid, name, StepStatus.running)
            try:
                adapter = self.registry.get(Capability.fetch_transcript, v.platform)
                run_id, tr, state = ex.run(jid, name, adapter, Capability.fetch_transcript, v.platform, {"url": v.canonical_url, "language": plan.languages[0]}, plan.limits.provider_cost_budget_usd)
            except (ProviderPermanentError, UncertainRun, RetryableError) as exc:
                self.store.set_step(jid, name, StepStatus.uncertain if isinstance(exc, UncertainRun) else StepStatus.failed, {"error": str(exc)})
                problems.append(f"Átirat nem érhető el ({v.canonical_url}): {exc}")
                continue
            self._account(jid, state)
            segs = [s for s in tr.segments if s.text and s.text.strip()]
            if not segs:
                v.access_status = AccessStatus.no_transcript            # hiányzó átiratot soha nem pótolunk modellből
                self.store.update_video(jid, v)
                self.store.set_step(jid, name, StepStatus.done, {"transcript": False})
                continue
            total = 0
            kept = []
            for i, s in enumerate(segs):
                total += len(s.text)
                if total > self.settings.max_transcript_chars:
                    problems.append(f"Az átirat a méretkorlát miatt csonkolva: {v.canonical_url}")
                    break
                kept.append(TranscriptSegment(id=f"{v.id}:s{i}", start_seconds=s.start, end_seconds=s.end, text=s.text.strip()))
            body = "\n".join(s.text for s in kept)
            self.store.save_transcript(jid, Transcript(
                id=new_id("trn"), video_source_id=v.id, language=tr.language, origin=tr.origin, segments=kept,
                timestamps_available=any(s.start_seconds is not None for s in kept),
                content_hash=hashlib.sha256(body.encode()).hexdigest(), provider=adapter.name, auto_generated=tr.auto_generated, fetched_at=now()))
            self.store.set_step(jid, name, StepStatus.done, {"transcript": True})

    def _extract(self, jid, plan, check, stats: ExtractionStats, problems) -> None:
        transcripts = {t.video_source_id: t for t in self.store.transcripts(jid)}
        for v in self.store.videos(jid):
            t = transcripts.get(v.id)
            name = f"ex:{v.id}"
            if not t or self._step_done(self.store.get_steps(jid), name):
                continue
            check()
            remaining = plan.limits.llm_token_budget - stats.tokens                # új LLM-hívást a keret kimerülése után nem indítunk
            if remaining <= 0:
                problems.append("Az LLM-tokenkeret kimerült, a további videók kinyerése kimaradt.")
                self.store.set_step(jid, name, StepStatus.skipped, {"reason": "token_budget"})
                break
            before = stats.tokens
            self.store.set_step(jid, name, StepStatus.running)
            try:
                found = extract_findings(self.llm, jid, plan, v, t, remaining, stats)
                if self.semantic:
                    for f in found:
                        semantic_check(self.llm, f, stats)
            except TokenBudgetExceeded as exc:
                self.store.set_step(jid, name, StepStatus.skipped, {"reason": "token_budget"})
                problems.append(f"{v.canonical_url}: {exc}")
                continue
            self.store.save_findings(jid, v.id, found)
            self.store.add_usage(jid, tokens=stats.tokens - before)
            self.store.set_step(jid, name, StepStatus.done, {"findings": len(found)})

    # ---- lezárás ----
    def _finish(self, jid, plan, ex: Executor, stats: ExtractionStats, problems, stop_reason) -> JobStatus:
        videos = self.store.videos(jid)
        findings = merge_findings(self.store.findings(jid), {v.id: v for v in videos})
        steps = self.store.get_steps(jid)
        ok = [v for v in videos if v.access_status == AccessStatus.ok and self._step_done(steps, f"ex:{v.id}")
              and steps[f"ex:{v.id}"][0] == StepStatus.done]
        job = self.store.get_job(jid)
        report = build_report(job, plan, videos, findings, self.store.transcripts(jid), problems + ex.notes, stats,
                              rejected=stats.rejected_unverified, provider_runs=self.store.provider_runs(jid), stop_reason=stop_reason)
        if stop_reason == "cancelled":
            status = JobStatus.cancelled
        elif not ok:
            status = JobStatus.failed
        elif len(ok) < len(videos) or problems or stop_reason:
            status = JobStatus.partially_completed
        else:
            status = JobStatus.completed
        self.store.set_status(jid, status, report=report.model_dump_json(), error="; ".join(problems)[:2000] or None)
        return status


def _dt(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
    except (ValueError, AttributeError):
        return None
