-- Relay schema v2: cron schedules, job progress, and dependency DAGs
CREATE TABLE IF NOT EXISTS cron_schedules (
    name TEXT PRIMARY KEY,
    expression TEXT NOT NULL,
    handler TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK (length(payload_json) <= 65536),
    queue TEXT NOT NULL DEFAULT 'default' REFERENCES queues(name),
    priority INTEGER NOT NULL DEFAULT 0 CHECK (priority BETWEEN -100 AND 100),
    timeout_ms INTEGER NOT NULL DEFAULT 60000 CHECK (timeout_ms > 0),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 10),
    next_run_at INTEGER NOT NULL,
    last_run_at INTEGER,
    paused INTEGER NOT NULL DEFAULT 0 CHECK (paused IN (0, 1)),
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cron_schedules_due
    ON cron_schedules(paused, next_run_at);

CREATE TABLE IF NOT EXISTS job_dependencies (
    parent_id TEXT NOT NULL REFERENCES jobs(id),
    child_id TEXT NOT NULL REFERENCES jobs(id),
    created_at INTEGER NOT NULL,
    PRIMARY KEY (parent_id, child_id)
);

CREATE INDEX IF NOT EXISTS idx_deps_parent ON job_dependencies(parent_id);
CREATE INDEX IF NOT EXISTS idx_deps_child ON job_dependencies(child_id);

ALTER TABLE jobs ADD COLUMN progress_percent INTEGER CHECK (progress_percent IS NULL OR progress_percent BETWEEN 0 AND 100);
ALTER TABLE jobs ADD COLUMN progress_message TEXT CHECK (progress_message IS NULL OR length(progress_message) <= 500);
ALTER TABLE jobs ADD COLUMN progress_json TEXT CHECK (progress_json IS NULL OR length(progress_json) <= 4096);
ALTER TABLE jobs ADD COLUMN pending_dependencies_count INTEGER NOT NULL DEFAULT 0 CHECK (pending_dependencies_count >= 0);
