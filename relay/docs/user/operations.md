# Operations runbook

These commands track the current CLI contract. Complete clean Windows/Linux restore,
upgrade and rollback drills remain **open release gates**, not completed exercises.
Use `uv run --locked relay` instead of `relay` when working from source.

## Shutdown and backups

Stop submission, drain/stop workers, then stop the API before replacing an installation.
Worker shutdown is bounded by its grace setting; a terminated attempt may later retry.

```sh
relay db backup ./relay-backup.db
```

Backup uses SQLite's backup API, not a raw copy of an active WAL database. Choose
a new destination; protect the backup as sensitive data and retain it outside the
installation's data directory. Check the actual command with `relay db backup --help`.

For a restore drill, stop **all** API/worker processes and preserve the original data
directory. Restore the backup into a separate private data directory, with the token
stored separately and access restricted. Do not overlay a restored file on live
`-wal`/`-shm` files. Configure `RELAY_DATA_DIR`/`RELAY_DB` consistently and validate
history, idempotency, integrity, readiness and worker behavior before admitting work.
There is no automated restore command claimed here.

## Upgrade and rollback

1. Save the exact old wheel and a consistent pre-upgrade backup.
2. Stop API and workers. Install the new local wheel in an isolated environment.
3. Run `relay db migrate --db /absolute/path/to/relay.db` using the new version.
4. Start API and workers; inspect readiness and real queued work.
5. If rollback is necessary, stop both processes. Use the old wheel and a compatible
   pre-upgrade backup in a separate directory. Do not run old code against an unknown
   newer schema or assume a migration can be reversed.

## Retention

Use an explicit UTC cutoff. First inspect the default dry run:

```sh
relay db prune --before 2026-01-01T00:00:00Z --dry-run
```

Only after review and backup:

```sh
relay db prune --before 2026-01-01T00:00:00Z --execute --yes
```

Prune removes old terminal jobs and their idempotency protection. Reusing an old
submission key after pruning can create new work. Referenced historical lineage may
no longer be available. There is no automatic retention policy.

## Diagnosis

| Symptom | First checks |
|---|---|
| Jobs stay queued | Worker process/heartbeat, queue pause, supported handler, due time |
| 401 | Correct data directory and token, no stale dashboard credential |
| Readiness fails | Database path, migrations, disk space, local permissions |
| SQLite busy | Other writers, long transactions, local disk health |
| API healthy but no work | Liveness is not worker readiness; inspect worker state |

Keep process output under an operator-managed rotation policy. Systemd units and
Windows service-wrapper installation have not been shipped or VM-tested; do not
infer service hardening from the foreground instructions.
