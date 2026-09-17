# CLI and API reference

The executable entry point is `relay`. Defaults are loopback HTTP on port **8000**,
not the older planning document's proposed 8741.

```sh
relay --help
relay init --help
relay serve --help
relay worker start --help
relay jobs --help
relay queues --help
relay workers --help
relay db --help
```

`serve` (also `server`) starts the API, not a worker. It deliberately has no remote
host override. `worker start` connects directly to SQLite and can operate while the
API is down. `jobs`, `queues`, and `workers` commands use the HTTP API.

## Configuration

| Variable | Meaning |
|---|---|
| `RELAY_DATA_DIR` | Local private directory containing `token` and default `relay.db` |
| `RELAY_DB` | Explicit database file; keep server and workers consistent |
| `RELAY_TOKEN` | Optional credential override; prefer the generated restricted file |
| `RELAY_URL` | CLI HTTP origin; default `http://127.0.0.1:8000`, loopback only |

There is no `RELAY_TOKEN_FILE` variable in this snapshot. `init --data-dir` only
selects initialization's directory; set `RELAY_DATA_DIR` for later commands too.

## HTTP

Protected endpoints live beneath `/api/v1/`; `/metrics` also requires bearer auth.
Send credentials only as `Authorization: Bearer …`, never as a query parameter.
Liveness and readiness are unauthenticated and must not expose job payloads.

The running server exposes its authenticated schema at `/api/v1/openapi.json`.
Retrieve it through the installed client so the credential comes from local
configuration rather than shell arguments:

```sh
python -c "import json; from relay.cli.client import request; print(json.dumps(request('GET', 'openapi.json'), indent=2))"
```

The server must be running and `RELAY_DATA_DIR`/`RELAY_URL` must identify the correct
installation. This retrieves the exact installed API schema rather than a static
reference maintained independently of code. Interactive `/docs` and `/redoc` are
disabled in this snapshot.
