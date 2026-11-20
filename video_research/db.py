"""Adatbázis-réteg SQLAlchemy Core-ral (PostgreSQL élesben, SQLite fejlesztésben/tesztben), egyszerű verziózott migrációkkal.

A feladatfoglalás összehasonlít-és-cserél (CAS) UPDATE-tel történik, amely mindkét adatbázison atomi,
így két worker nem foglalhatja le ugyanazt a feladatot egyszerre.
"""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .models import (Finding, JobStatus, Limits, ResearchJob, ResearchPlan, StepStatus, TERMINAL_STATUSES,
                     Transcript, VideoSource)
from .util import iso, new_id, now, parse_iso

MIGRATIONS = Path(__file__).parent / "migrations"


def make_engine(url: str) -> Engine:
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
    return create_engine(url, **kwargs)


def migrate(engine: Engine) -> list[str]:
    applied: list[str] = []
    with engine.begin() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"))
        done = {r[0] for r in c.execute(text("SELECT name FROM schema_migrations"))}
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.name in done:
                continue
            for stmt in f.read_text(encoding="utf-8").split(";"):
                if "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip():
                    c.execute(text(stmt))
            c.execute(text("INSERT INTO schema_migrations (name, applied_at) VALUES (:n, :t)"), {"n": f.name, "t": iso(now())})
            applied.append(f.name)
    return applied


def _job(row) -> ResearchJob:
    m = row._mapping
    return ResearchJob(
        id=m["id"], request=m["request"], platforms=json.loads(m["platforms"]), languages=json.loads(m["languages"]),
        status=JobStatus(m["status"]), approved_plan=ResearchPlan.model_validate_json(m["approved_plan"]) if m["approved_plan"] else None,
        limits=Limits.model_validate_json(m["limits"]), estimated_cost=m["estimated_cost"], recorded_cost=m["recorded_cost"],
        created_at=parse_iso(m["created_at"]), updated_at=parse_iso(m["updated_at"]))


class Store:
    def __init__(self, engine: Engine):
        self.e = engine

    # ---- feladatok ----
    def create_job(self, request: str, platforms: list[str], languages: list[str], limits: Limits,
                   idempotency_key: str | None = None) -> tuple[ResearchJob, bool]:
        """Idempotens létrehozás. Ugyanazzal a kulccsal és kéréssel a meglévő feladat jön vissza (created=False);
        ugyanazzal a kulccsal más kéréssel ValueError."""
        rh = hashlib.sha256(json.dumps([request, sorted(platforms), sorted(languages), limits.model_dump()], sort_keys=True).encode()).hexdigest()
        jid, t = new_id("job"), iso(now())
        with self.e.begin() as c:
            if idempotency_key:
                row = c.execute(text("SELECT * FROM research_jobs WHERE idempotency_key=:k"), {"k": idempotency_key}).first()
                if row:
                    if row._mapping["request_hash"] != rh:
                        raise ValueError("az Idempotency-Key már más kéréshez tartozik")
                    return _job(row), False
            c.execute(text("""INSERT INTO research_jobs (id, idempotency_key, request_hash, request, platforms, languages, status, limits, created_at, updated_at)
                              VALUES (:id,:k,:rh,:rq,:pl,:lg,'queued',:li,:t,:t)"""),
                      {"id": jid, "k": idempotency_key, "rh": rh, "rq": request, "pl": json.dumps(platforms), "lg": json.dumps(languages),
                       "li": limits.model_dump_json(), "t": t})
        return self.get_job(jid), True

    def get_job(self, jid: str) -> ResearchJob | None:
        with self.e.connect() as c:
            row = c.execute(text("SELECT * FROM research_jobs WHERE id=:i"), {"i": jid}).first()
        return _job(row) if row else None

    def get_field(self, jid: str, name: str):
        assert name in {"plan", "approved_plan", "report", "error", "cancel_requested", "llm_tokens_used", "attempts", "lease_owner", "estimated_cost"}
        with self.e.connect() as c:
            return c.execute(text(f"SELECT {name} FROM research_jobs WHERE id=:i"), {"i": jid}).scalar()

    def set_status(self, jid: str, status: JobStatus, **fields) -> bool:
        """Állapotváltás. Végállapotból nem lehet kilépni (megszakítás/befejezés nem íródik felül)."""
        allowed = {"plan", "approved_plan", "report", "error", "estimated_cost"}
        assert set(fields) <= allowed
        sets = ", ".join(f"{k}=:{k}" for k in fields)
        terminal = ",".join(f"'{s.value}'" for s in TERMINAL_STATUSES)
        with self.e.begin() as c:
            r = c.execute(text(f"UPDATE research_jobs SET status=:s, updated_at=:t{', ' + sets if sets else ''} WHERE id=:i AND status NOT IN ({terminal})"),
                          {"s": status.value, "t": iso(now()), "i": jid, **fields})
            return r.rowcount == 1

    def request_cancel(self, jid: str) -> JobStatus | None:
        """Megszakítás kérése. Nem futó feladat azonnal cancelled; futónál jelzőt állít (a worker a lépések között ellenőrzi)."""
        job = self.get_job(jid)
        if not job:
            return None
        if job.status in TERMINAL_STATUSES:
            return job.status
        with self.e.begin() as c:
            c.execute(text("UPDATE research_jobs SET cancel_requested=1, updated_at=:t WHERE id=:i"), {"t": iso(now()), "i": jid})
        if job.status in (JobStatus.queued, JobStatus.awaiting_approval) and not self.get_field(jid, "lease_owner"):
            self.set_status(jid, JobStatus.cancelled)
        return self.get_job(jid).status

    def add_usage(self, jid: str, cost: float = 0.0, tokens: int = 0) -> None:
        with self.e.begin() as c:
            c.execute(text("UPDATE research_jobs SET recorded_cost=recorded_cost+:c, llm_tokens_used=llm_tokens_used+:k, updated_at=:t WHERE id=:i"),
                      {"c": cost, "k": tokens, "t": iso(now()), "i": jid})

    # ---- lease / heartbeat ----
    def claim_next(self, worker: str, lease_seconds: int, when=None) -> str | None:
        """A következő végrehajtható feladat lefoglalása. Végrehajtható: queued (tervezés vagy jóváhagyott futás),
        vagy planning/running állapotú, de lejárt leasével (összeomlott worker)."""
        t = when or now()
        exp = iso(t + timedelta(seconds=lease_seconds))
        with self.e.begin() as c:
            ids = [r[0] for r in c.execute(text(
                """SELECT id FROM research_jobs WHERE status IN ('queued','planning','running')
                   AND (lease_expires_at IS NULL OR lease_expires_at < :now) ORDER BY created_at LIMIT 10"""), {"now": iso(t)})]
            for jid in ids:
                r = c.execute(text("""UPDATE research_jobs SET lease_owner=:w, lease_expires_at=:e, heartbeat_at=:now, attempts=attempts+1
                                      WHERE id=:i AND (lease_expires_at IS NULL OR lease_expires_at < :now)"""),
                              {"w": worker, "e": exp, "now": iso(t), "i": jid})
                if r.rowcount == 1:
                    return jid
        return None

    def heartbeat(self, jid: str, worker: str, lease_seconds: int, when=None) -> bool:
        t = when or now()
        with self.e.begin() as c:
            r = c.execute(text("UPDATE research_jobs SET lease_expires_at=:e, heartbeat_at=:n WHERE id=:i AND lease_owner=:w"),
                          {"e": iso(t + timedelta(seconds=lease_seconds)), "n": iso(t), "i": jid, "w": worker})
            return r.rowcount == 1

    def release(self, jid: str, worker: str) -> None:
        with self.e.begin() as c:
            c.execute(text("UPDATE research_jobs SET lease_owner=NULL, lease_expires_at=NULL WHERE id=:i AND lease_owner=:w"), {"i": jid, "w": worker})

    # ---- részfolyamatok ----
    def set_step(self, jid: str, step: str, status: StepStatus, detail: dict | None = None) -> None:
        d = json.dumps(detail or {}, ensure_ascii=False)
        with self.e.begin() as c:
            r = c.execute(text("UPDATE job_steps SET status=:s, detail=:d, updated_at=:t WHERE job_id=:j AND step=:p"),
                          {"s": status.value, "d": d, "t": iso(now()), "j": jid, "p": step})
            if r.rowcount == 0:
                c.execute(text("INSERT INTO job_steps (job_id, step, status, detail, updated_at) VALUES (:j,:p,:s,:d,:t)"),
                          {"s": status.value, "d": d, "t": iso(now()), "j": jid, "p": step})

    def get_steps(self, jid: str) -> dict[str, tuple[StepStatus, dict]]:
        with self.e.connect() as c:
            rows = c.execute(text("SELECT step,status,detail FROM job_steps WHERE job_id=:j"), {"j": jid}).fetchall()
        return {r[0]: (StepStatus(r[1]), json.loads(r[2] or "{}")) for r in rows}

    # ---- szolgáltatói futások ----
    def get_provider_run(self, jid: str, request_key: str) -> dict | None:
        with self.e.connect() as c:
            row = c.execute(text("SELECT * FROM provider_runs WHERE job_id=:j AND request_key=:k"), {"j": jid, "k": request_key}).first()
        return dict(row._mapping) if row else None

    def save_provider_run(self, jid: str, step: str, provider: str, capability: str, request_key: str, status: str,
                          provider_run_id: str | None = None, cost_usd: float | None = None) -> None:
        t = iso(now())
        with self.e.begin() as c:
            r = c.execute(text("""UPDATE provider_runs SET status=:s, provider_run_id=COALESCE(:r, provider_run_id), cost_usd=COALESCE(:c, cost_usd),
                                  cost_known=CASE WHEN :c IS NULL THEN cost_known ELSE 1 END, updated_at=:t WHERE job_id=:j AND request_key=:k"""),
                          {"s": status, "r": provider_run_id, "c": cost_usd, "t": t, "j": jid, "k": request_key})
            if r.rowcount == 0:
                c.execute(text("""INSERT INTO provider_runs (id, job_id, step, provider, capability, request_key, provider_run_id, status, cost_usd, cost_known, created_at, updated_at)
                                  VALUES (:id,:j,:st,:p,:cap,:k,:r,:s,:c,:ck,:t,:t)"""),
                          {"id": new_id("run"), "j": jid, "st": step, "p": provider, "cap": capability, "k": request_key, "r": provider_run_id,
                           "s": status, "c": cost_usd, "ck": 0 if cost_usd is None else 1, "t": t})

    def provider_runs(self, jid: str) -> list[dict]:
        with self.e.connect() as c:
            return [dict(r._mapping) for r in c.execute(text("SELECT * FROM provider_runs WHERE job_id=:j ORDER BY created_at"), {"j": jid})]

    # ---- videók, átiratok, megállapítások ----
    def add_video(self, jid: str, v: VideoSource) -> bool:
        with self.e.begin() as c:
            r = c.execute(text("SELECT 1 FROM video_sources WHERE job_id=:j AND platform=:p AND platform_video_id=:v"),
                          {"j": jid, "p": v.platform.value, "v": v.platform_video_id}).first()
            if r:
                return False
            c.execute(text("INSERT INTO video_sources (id, job_id, platform, platform_video_id, data) VALUES (:i,:j,:p,:v,:d)"),
                      {"i": v.id, "j": jid, "p": v.platform.value, "v": v.platform_video_id, "d": v.model_dump_json()})
        return True

    def update_video(self, jid: str, v: VideoSource) -> None:
        with self.e.begin() as c:
            c.execute(text("UPDATE video_sources SET data=:d WHERE id=:i AND job_id=:j"), {"d": v.model_dump_json(), "i": v.id, "j": jid})

    def videos(self, jid: str) -> list[VideoSource]:
        with self.e.connect() as c:
            return [VideoSource.model_validate_json(r[0]) for r in c.execute(text("SELECT data FROM video_sources WHERE job_id=:j ORDER BY id"), {"j": jid})]

    def save_transcript(self, jid: str, t: Transcript) -> None:
        with self.e.begin() as c:
            c.execute(text("DELETE FROM transcripts WHERE job_id=:j AND video_source_id=:v"), {"j": jid, "v": t.video_source_id})
            c.execute(text("INSERT INTO transcripts (id, job_id, video_source_id, content_hash, data) VALUES (:i,:j,:v,:h,:d)"),
                      {"i": t.id, "j": jid, "v": t.video_source_id, "h": t.content_hash, "d": t.model_dump_json()})

    def transcripts(self, jid: str) -> list[Transcript]:
        with self.e.connect() as c:
            return [Transcript.model_validate_json(r[0]) for r in c.execute(text("SELECT data FROM transcripts WHERE job_id=:j ORDER BY id"), {"j": jid})]

    def save_findings(self, jid: str, video_source_id: str, findings: list[Finding]) -> None:
        with self.e.begin() as c:
            c.execute(text("DELETE FROM findings WHERE job_id=:j AND video_source_id=:v"), {"j": jid, "v": video_source_id})
            for f in findings:
                c.execute(text("INSERT INTO findings (id, job_id, video_source_id, data) VALUES (:i,:j,:v,:d)"),
                          {"i": f.id, "j": jid, "v": video_source_id, "d": f.model_dump_json()})

    def findings(self, jid: str) -> list[Finding]:
        with self.e.connect() as c:
            return [Finding.model_validate_json(r[0]) for r in c.execute(text("SELECT data FROM findings WHERE job_id=:j ORDER BY id"), {"j": jid})]

    # ---- törlés és megőrzés ----
    def delete_job(self, jid: str) -> bool:
        """A feladat és minden hozzá tartozó adat törlése. A videók, átiratok és megállapítások jelenleg feladatonként tárolódnak
        (nincs feladatok közti megosztott gyorsítótár), ezért más feladat forrását a törlés nem érinti."""
        with self.e.begin() as c:
            if c.execute(text("DELETE FROM research_jobs WHERE id=:j AND lease_owner IS NULL"), {"j": jid}).rowcount != 1:
                return False                      # lefoglalt (futó) feladat: semmit nem törlünk
            for t in ("findings", "transcripts", "video_sources", "provider_runs", "job_steps"):
                c.execute(text(f"DELETE FROM {t} WHERE job_id=:j"), {"j": jid})
        return True

    def purge_expired(self, retention_days: int, when=None) -> int:
        cutoff = iso((when or now()) - timedelta(days=retention_days))
        terminal = ",".join(f"'{x.value}'" for x in TERMINAL_STATUSES)
        with self.e.connect() as c:
            ids = [r[0] for r in c.execute(text(f"SELECT id FROM research_jobs WHERE status IN ({terminal}) AND updated_at < :c"), {"c": cutoff})]
        return sum(1 for i in ids if self.delete_job(i))
