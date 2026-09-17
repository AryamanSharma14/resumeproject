# Relay Operations Runbook

Status: operating requirements/templates for v1.0. Commands marked *planned* are specified by the CLI contract (implementation-plan 8.2) and must exist and be tested before this doc ships in the release.

## 1. Install and start (single host)
```text
pipx install relay-jobs          # planned
relay init                       # creates data dir + token; prints nothing secret
relay serve                      # 127.0.0.1:8741 (planned default)
relay worker start --concurrency 2
```
Upgrade: stop workers → `relay db backup` → install new version → `relay db migrate` → start → verify `/health/ready`. Rollback: restore previous package; DB schema unknown to older binary is refused (T01) — restore backup if migration applied.

## 2. Service installation
### Linux systemd (template to be shipped as `packaging/systemd/relay.service`)
User-dedicated account, `ExecStart=/usr/bin/relay serve`, `Environment=RELAY_TOKEN_FILE=/etc/relay/token`, Restart=on-failure, hardening: NoNewPrivileges, ProtectSystem=strict, ProtectHome, PrivateTmp; separate unit for worker. Docs require testing the unit in a VM, not copy-paste trust.
### Windows
NSSM service or Task Scheduler for `relay serve` and `relay worker start`; document token via environment, log location, and auto-start ordering (serve before worker is not required — workers retry API absence, T14).

## 3. Backup and restore
- Backup: `relay db backup --output FILE` uses the SQLite backup API (never raw copy of live WAL files).
- Restore drill (required before v1): create instance, submit demo jobs, backup, destroy dir, restore, verify history/idempotency (T22).
- Schedule via cron/Task Scheduler; backup file permissions restricted; retention policy left to operator, documented.

## 4. Retention / pruning
`relay db prune --older-than 30d --dry-run` → review → run without dry-run. Documented: terminal jobs only; removes their idempotency protection; lineage events of reruns may lose referenced originals (behavior documented, T23).

## 5. Monitoring
- `/metrics` for Prometheus: relay_jobs{state,queue}, relay_queue_oldest_due_age_seconds{queue}, relay_workers{state}.
- Suggested alert rules (operator tunes thresholds): oldest_due_age > N minutes with zero available workers; workers{state=offline} persisting; recovery-loop staleness; DB busy-exhaustion counter increasing; disk free low.
- Log locations and rotation documented per platform; request_id in every API error for correlation.

## 6. Common incidents
| Symptom | First checks | Action |
|---|---|---|
| Jobs stuck queued | workers list (planned) — heartbeats? compatible handlers? queue paused? | start/upgrade worker; resume queue |
| Running but lease expired shown | worker process alive? watchdog logs? | wait one recovery interval; inspect events |
| DATABASE_BUSY errors | disk health; other SQLite writers on same file | verify single-install usage; tune busy timeout (documented) |
| 401 from CLI | token env/file set for the right instance | re-run `relay init` guidance; never paste tokens in argv |
| Disk near full | prune dry-run; WAL size | prune terminal jobs; checkpoint via backup; expand disk |

## 7. Runbook acceptance
Every command above executes as written in the release VM test (Windows + Linux); tables match real command output; no instruction exists that has not been run by the release checklist.
