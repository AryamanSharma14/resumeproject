-- Relay schema v1 (implementation-plan 6.2)
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS queues (
    name TEXT PRIMARY KEY,
    paused INTEGER NOT NULL DEFAULT 0 CHECK (paused IN (0, 1)),
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    handler TEXT NOT NULL,
    handler_version TEXT NOT NULL,
    queue TEXT NOT NULL REFERENCES queues(name),
    payload_json TEXT NOT NULL CHECK (length(payload_json) <= 65536),
    state TEXT NOT NULL CHECK (state IN ('queued','running','retry_wait','succeeded','failed','canceled')),
    priority INTEGER NOT NULL DEFAULT 0 CHECK (priority BETWEEN -100 AND 100),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    available_at INTEGER NOT NULL,
    started_at INTEGER,
    finished_at INTEGER,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL CHECK (max_attempts BETWEEN 1 AND 10),
    timeout_ms INTEGER NOT NULL CHECK (timeout_ms > 0),
    active_attempt_id TEXT,
    owner_token TEXT,
    lease_expires_at INTEGER,
    result_json TEXT CHECK (result_json IS NULL OR length(result_json) <= 65536),
    last_error_code TEXT,
    last_error_summary TEXT,
    rerun_of TEXT REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    number INTEGER NOT NULL,
    owner_token TEXT NOT NULL UNIQUE,
    worker_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('running','succeeded','failed','timed_out','lost')),
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    lease_expires_at INTEGER,
    error_code TEXT,
    error_summary TEXT,
    result_json TEXT,
    UNIQUE (job_id, number)
);

CREATE TABLE IF NOT EXISTS job_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    attempt_id TEXT,
    kind TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    detail_json TEXT CHECK (detail_json IS NULL OR length(detail_json) <= 8192)
);

CREATE TABLE IF NOT EXISTS workers (
    id TEXT PRIMARY KEY,
    hostname TEXT NOT NULL,
    process_id INTEGER NOT NULL,
    started_at INTEGER NOT NULL,
    heartbeat_at INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('online','draining','stale','offline')),
    concurrency INTEGER NOT NULL CHECK (concurrency > 0),
    queues_json TEXT NOT NULL,
    handler_versions_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_records (
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    created_at INTEGER NOT NULL,
    UNIQUE (scope, key)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_attempts_running_per_job
    ON attempts(job_id) WHERE state = 'running';

CREATE INDEX IF NOT EXISTS idx_jobs_claim
    ON jobs(state, available_at, priority DESC, created_at, id);
CREATE INDEX IF NOT EXISTS idx_jobs_queue_claim
    ON jobs(queue, state, available_at);
CREATE INDEX IF NOT EXISTS idx_jobs_lease_expiry
    ON jobs(state, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_jobs_created
    ON jobs(created_at DESC, id);
CREATE INDEX IF NOT EXISTS idx_attempts_job
    ON attempts(job_id, number);
CREATE INDEX IF NOT EXISTS idx_events_job
    ON job_events(job_id, seq);
CREATE INDEX IF NOT EXISTS idx_workers_heartbeat
    ON workers(heartbeat_at);
