export type JobState = 'queued' | 'running' | 'retry_wait' | 'succeeded' | 'failed' | 'canceled';
export interface Page<T> { items: T[]; next_cursor: string | null }
export interface Job { id: string; handler: string; handler_version: string; queue: string; payload: unknown; state: JobState; priority: number; created_at: string; updated_at: string; available_at: string; started_at: string | null; finished_at: string | null; attempt_count: number; max_attempts: number; timeout_ms: number; active_attempt_id: string | null; lease_expires_at: string | null; result: unknown; last_error_code: string | null; last_error_summary: string | null; rerun_of: string | null }
export interface Attempt { id: string; job_id: string; number: number; worker_id: string; state: string; started_at: string; finished_at: string | null; lease_expires_at: string; error_code: string | null; error_summary: string | null; result: unknown }
export interface JobEvent { seq: number; job_id: string; attempt_id: string | null; kind: string; created_at: string; detail: unknown }
export interface Queue { name: string; paused: boolean; created_at: string; due_depth: number; oldest_due_age_ms: number | null; retry_wait_count?: number }
export interface Worker { id: string; hostname: string; process_id: number; started_at: string; heartbeat_at: string; state: string; concurrency: number; queues: string[]; handler_versions: Record<string,string>; heartbeat_age_ms: number; active_attempts: number; available_slots: number; availability: string }
export interface Handler { name: string; version: string; description: string; payload_schema: { properties?: Record<string, { type?: string; minimum?: number; maximum?: number; maxLength?: number; maxItems?: number }>; required?: string[] } }
export interface Overview { as_of: string; window: 'retained'; jobs: Record<JobState, number>; queues: Queue[]; workers: Record<string,number> }
export interface SubmitResult { job_id: string; replayed: boolean }
export interface SystemInfo { version: string; schema_version: number; database_size_bytes: number; maintenance_last_at: string | null; as_of: string }
