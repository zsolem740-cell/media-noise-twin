"""A feldolgozási folyamat. Minden lépés állapota tárolt, újraindítás után a kész lépések kimaradnak."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from typing import Callable

from .adapters.base import AdapterRegistry, Capability, ProviderNotConfigured, ProviderPermanentError
from .config import Settings
from .db import Store
from .executor import CostBudgetExhausted, Executor, JobStopped, UncertainRun
from .extraction import ExtractionStats, TokenBudgetExceeded, extract_findings, semantic_check
from .llm import LLMClient, LLMQuotaExhausted, LLMRejected, LLMTransient, LLMUnavailable, RetryingLLM
from .merge import merge_findings
from .models import (AccessStatus, FilterEntry, SkipReason, JobStatus, Platform, ResearchPlan, StepStatus, Transcript, TranscriptSegment, VideoSource)
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
                          requested_platforms=[p.value for p in job.platforms] or None,
                          known_information=json.loads(self.store.get_field(jid, "known_information") or "[]"),
                          imported_sources=len(self.store.videos(jid)))
        if (not plan.platforms and not plan.imported_sources) or (not plan.direct_urls and not plan.search_queries and not plan.imported_sources):
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
        self._llm = RetryingLLM(self.llm, max_retries=self.settings.max_retries, base=self.settings.backoff_base_seconds,
                                cap=self.settings.backoff_max_seconds, sleep=self.sleep, should_stop=lambda: ex._stopping())
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
        except LLMQuotaExhausted as exc:
            problems.append(f"A modellszolgáltató kvótája kimerült: {exc}. A futás megállt; a kész videók megmaradtak, folytatás a kvóta visszaállása után (szolgáltatóváltás nincs).")
            stop_reason = "llm_quota"
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
        dropped = 0
        for platform, vid, url in cands:                                  # F. duplikált videók kiszűrése
            if (platform.value, vid) in seen:
                continue
            seen.add((platform.value, vid))
            if added >= plan.limits.max_videos:
                dropped += 1
                continue
            v = VideoSource(id=new_id("vid"), platform=platform, platform_video_id=vid, canonical_url=url, retrieved_at=now(),
                            provider="pending", access_status=AccessStatus.ok)
            if self.store.add_video(jid, v):
                added += 1
        if dropped:
            problems.append(f"A videószám-keret ({plan.limits.max_videos}) miatt {dropped} további találat feldolgozatlan maradt (erőforráskorlát, nem tartalmi szűrés).")
        self.store.set_step(jid, "collect", StepStatus.done, {"videos": added, "dropped_by_max_videos": dropped})

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
            before, n0, k0 = stats.tokens, len(stats.skipped), len(stats.known_matches)
            self.store.set_step(jid, name, StepStatus.running)
            try:
                found = extract_findings(self._llm, jid, plan, v, t, remaining, stats)
                if self.semantic:
                    kept = []
                    for f in found:
                        if semantic_check(self._llm, f, stats):        # kétes jelentésbeli egyezés = kinyerési hiba: nem nyom, kihagyjuk és naplózzuk
                            stats.skipped.append(FilterEntry(video_source_id=v.id, segment_ids=f.source_references[0].transcript_segment_ids,
                                                             snippet=f.source_references[0].supporting_quote[:160], reason_code=SkipReason.extraction_unreliable,
                                                             reason_hu="az idézet és az állítás jelentésbeli egyezése kétes: megbízhatatlan kinyerés, nem publikáljuk (hibakezelés, nem nyom)"))
                        else:
                            kept.append(f)
                    found = kept
            except (LLMRejected, LLMTransient) as exc:
                self.store.set_step(jid, name, StepStatus.failed, {"error": str(exc)})
                problems.append(f"{v.canonical_url}: a modellkérés sikertelen, a videó kimaradt: {exc}")
                continue
            except TokenBudgetExceeded as exc:
                self.store.set_step(jid, name, StepStatus.skipped, {"reason": "token_budget"})
                problems.append(f"{v.canonical_url}: {exc}")
                continue
            self.store.save_findings(jid, v.id, found)
            self.store.add_usage(jid, tokens=stats.tokens - before)
            self.store.set_step(jid, name, StepStatus.done, {"findings": len(found), "segments": len(t.segments),
                                                             "skipped": [e.model_dump(mode="json") for e in stats.skipped[n0:]],
                                                             "known_matches": stats.known_matches[k0:]})

    # ---- lezárás ----
    def _coverage(self, videos, steps, ok, stop_reason) -> dict:
        """Az ERŐFORRÁSKORLÁTOK miatti hiányos lefedettség. Nem tartalmi kvóta: a jelentésbe kerülő tételek számát semmilyen arány nem korlátozza."""
        hit: set[str] = set()
        collect = steps.get("collect")
        dropped = collect[1].get("dropped_by_max_videos", 0) if collect else 0
        if dropped:
            hit.add("max_videos")
        stop_map = {"runtime_limit": "timeout_seconds", "cost_budget": "max_cost_usd", "llm_quota": "llm_quota", "cancelled": "cancelled", "unavailable": "service_unavailable"}
        if stop_reason in stop_map and stop_reason != "cancelled":
            hit.add(stop_map[stop_reason])
        not_done = []
        for v in videos:
            ex_, me, tr = steps.get(f"ex:{v.id}"), steps.get(f"meta:{v.id}"), steps.get(f"tr:{v.id}")
            if ex_ and ex_[0] == StepStatus.done:
                continue
            if me and me[0] == StepStatus.skipped and me[1].get("reason") == "video_minutes_limit":
                reason = "max_total_minutes"
            elif ex_ and ex_[0] == StepStatus.skipped and ex_[1].get("reason") == "token_budget":
                reason = "max_llm_tokens"
            elif v.access_status == AccessStatus.no_transcript:
                reason = "no_transcript"
            elif any(x and x[0] in (StepStatus.failed, StepStatus.uncertain) for x in (me, tr, ex_)):
                reason = "error"
            else:
                reason = stop_map.get(stop_reason or "", "not_reached")
            if reason in ("max_total_minutes", "max_llm_tokens"):
                hit.add(reason)
            not_done.append({"url": v.canonical_url, "reason": reason})
        return {"content_quota": "nincs: a megtartott tételek számát semmilyen arány vagy darabszám nem korlátozza; csak a jóváhagyott erőforráskeretek korlátoznak",
                "videos_identified": len(videos) + dropped, "videos_processed": len(ok), "videos_dropped_by_video_cap": dropped, "not_processed": not_done,
                "limits_hit": sorted(hit), "complete": not not_done and not dropped and not stop_reason}

    def _finish(self, jid, plan, ex: Executor, stats: ExtractionStats, problems, stop_reason) -> JobStatus:
        videos = self.store.videos(jid)
        order = {v.id: i for i, v in enumerate(videos)}

        def pos(f):                                           # determinisztikus sorrend: videó, majd az első szegmens helye az átiratban
            r = f.source_references[0]
            return (order.get(r.video_source_id, 0), int(r.transcript_segment_ids[0].rsplit(":s", 1)[-1]))
        findings, merge_log = merge_findings(sorted(self.store.findings(jid), key=pos), {v.id: v for v in videos})
        steps = self.store.get_steps(jid)
        ok = [v for v in videos if v.access_status == AccessStatus.ok and self._step_done(steps, f"ex:{v.id}")
              and steps[f"ex:{v.id}"][0] == StepStatus.done]
        # a szűrési napló a tárolt lépés-részletekből épül, így újraindítás után is teljes
        skipped, seen, segments = [], set(), 0
        for v in videos:
            st = steps.get(f"ex:{v.id}")
            if st and st[0] == StepStatus.done:
                segments += st[1].get("segments", 0)
                for raw in st[1].get("skipped", []):
                    e = FilterEntry.model_validate(raw)
                    k = (e.video_source_id, e.snippet, e.reason_code)
                    if k not in seen:
                        seen.add(k)
                        skipped.append(e)
        known, kseen = [], set()
        for v in videos:
            st = steps.get(f"ex:{v.id}")
            for m in (st[1].get("known_matches", []) if st and st[0] == StepStatus.done else []):
                if (m["known"], m["quote"]) not in kseen:
                    kseen.add((m["known"], m["quote"]))
                    known.append(m)
        coverage = self._coverage(videos, steps, ok, stop_reason)
        job = self.store.get_job(jid)
        report = build_report(job, plan, videos, findings, self.store.transcripts(jid), problems + ex.notes, stats,
                              provider_runs=self.store.provider_runs(jid), stop_reason=stop_reason,
                              filter_log=skipped + merge_log, segments_total=segments, videos_processed=len(ok),
                              llm=self.llm, coverage=coverage, known_matches=known)
        if stop_reason == "cancelled":
            status = JobStatus.cancelled
        elif not ok:
            status = JobStatus.failed
        elif len(ok) < len(videos) or problems or stop_reason:
            status = JobStatus.partially_completed
        else:
            status = JobStatus.completed                  # üres eredménnyel is: a „nincs találat” érvényes kimenet
        self.store.set_status(jid, status, report=report.model_dump_json(), error="; ".join(problems)[:2000] or None)
        return status


def _dt(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
    except (ValueError, AttributeError):
        return None
