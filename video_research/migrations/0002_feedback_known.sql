ALTER TABLE research_jobs ADD COLUMN known_information TEXT;

CREATE TABLE finding_feedback (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    label TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX ix_feedback_job ON finding_feedback (job_id, finding_id)
