# Getting started locally

## From source

Use Python 3.12 or newer, uv, and Node/npm. The release rehearsal selects Python
3.13.5, uv 0.11.7 and Node 24.4.1. Run from the repository's `relay/` directory:

```sh
uv sync --locked
cd web
npm ci
npm run build
cd ..
uv run --locked python scripts/build_release.py
uv run --locked relay init
uv run --locked relay serve --port 8000
```

The release script requires an empty `dist/` output directory. Use
`--output dist-next` on a subsequent build. It replaces generated
`src/relay/static/` from the real `web/dist/`; it never synthesizes a dashboard.

In a second terminal, from `relay/`:

```sh
uv run --locked relay worker start --concurrency 2
```

Open <http://127.0.0.1:8000>. `init` prints the token-file **path**, not the token.
Read that file privately on your own machine and enter its contents in the dashboard.
Never put it in a URL, command argument, issue, screenshot, or shared terminal log.
The dashboard keeps it in memory; reload requires authentication again.

By default, data uses the platform's non-roaming application-data directory.
To choose a directory, set `RELAY_DATA_DIR` in **every** terminal before running
`init`, `serve`, or `worker start`. Use a local disk, not a synced or network folder.
`RELAY_DB` can override the database path; keep server and worker on the same file.

## Local wheel (no Node at runtime)

After a successful source build, a wheel is in `dist/`. Install that exact artifact
into an isolated environment, substituting its actual filename:

```sh
pipx install ./dist/relay_jobs-0.1.0-py3-none-any.whl
relay init
relay serve --port 8000
```

Then run `relay worker start --concurrency 2` in another terminal. Wheel dependencies
still need an approved package index or a pre-provisioned offline wheelhouse.
A wheel includes the dashboard, not a Node runtime.

**Do not run `pipx install relay-jobs` from a public index on the assumption it is
this project.** Public ownership and TestPyPI/clean-VM rehearsal are open gates.
The wheel recipe above is a local artifact path, not a publication claim.

## Check before submitting work

`GET /health/live` probes the API process; `GET /health/ready` checks readiness.
Neither proves a worker is running. Inspect workers and queues in the dashboard
or with `relay workers list` / `relay queues list`. Use each command's `--help`
for the current flags; source CLI and API are still evolving.
