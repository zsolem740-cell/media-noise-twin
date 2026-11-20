-- Hordozható séma (PostgreSQL és SQLite). Időpontok: UTC ISO-szöveg. JSON: szöveg (PostgreSQL alatt későbbi migrációval JSONB-re vihető).
CREATE TABLE research_jobs (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE,
    request_hash TEXT,
    request TEXT NOT NULL,
    platforms TEXT NOT NULL,
    languages TEXT NOT NULL,
    status TEXT NOT NULL,
    plan TEXT,
    approved_plan TEXT,
    limits TEXT NOT NULL,
    estimated_cost REAL,
    recorded_cost REAL NOT NULL DEFAULT 0,
    llm_tokens_used INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    report TEXT,
    lease_owner TEXT,
    lease_expires_at TEXT,
    heartbeat_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX ix_jobs_status ON research_jobs (status);

CREATE TABLE job_steps (
    job_id TEXT NOT NULL,
    step TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (job_id, step)
);

CREATE TABLE provider_runs (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    step TEXT NOT NULL,
    provider TEXT NOT NULL,
    capability TEXT NOT NULL,
    request_key TEXT NOT NULL,
    provider_run_id TEXT,
    status TEXT NOT NULL,
    cost_usd REAL,
    cost_known INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (job_id, request_key)
);

CREATE TABLE video_sources (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    platform_video_id TEXT NOT NULL,
    data TEXT NOT NULL,
    UNIQUE (job_id, platform, platform_video_id)
);

CREATE TABLE transcripts (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    video_source_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    data TEXT NOT NULL,
    UNIQUE (job_id, video_source_id)
);

CREATE TABLE findings (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    video_source_id TEXT NOT NULL,
    data TEXT NOT NULL
);
