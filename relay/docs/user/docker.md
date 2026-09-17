# Docker: Linux-only, unverified recipe

**Docker was unavailable in the implementation environment.** The Dockerfile and
Compose file have been content-reviewed, not built or run. Treat every command below
as a rehearsal recipe pending validation, not a production deployment endorsement.

From `relay/`, on a Linux host with Docker Engine and Compose v2:

```sh
docker compose config
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail 100 api worker
```

Open <http://127.0.0.1:8000> **on that same host**. The API deliberately binds only
127.0.0.1. Compose uses Linux `network_mode: host` so the bind remains local; it does
not publish a wildcard port and does not bypass the CLI with a remote-bind wrapper.
Host networking gives the API container access to host networking and is not a
network sandbox. Do not expose port 8000 via firewall forwarding or a public proxy.
Docker Desktop/Windows/macOS behavior is unverified; use the source install there.

The init service generates credentials and migrates a named local volume; it must
complete before API and worker start. Both processes run as UID/GID 10001 with a
read-only root filesystem, dropped capabilities, no-new-privileges and writable
`/tmp`. Worker accesses SQLite directly and has networking disabled. No token,
DB, private key or `.env` is copied into the image. The named volume must remain
on local storage and accessible only to the intended operator.

The API healthcheck uses Python's standard library to query `/health/live`.
Readiness is `/health/ready`; worker status must be checked separately. Worker and
init HTTP healthchecks are disabled because they are not HTTP servers.

Retrieve the token file only through a private local operator session; never add a
literal secret to Compose environment declarations or build arguments. To inspect
the generated token path, use `docker compose exec api relay init` (does not print
the token). Follow the [security guidance](security.md) before handling the file.

```sh
docker compose stop worker api
# Keep the volume; do NOT use down -v unless intentionally destroying all data.
docker compose down
```

The [backup/restore procedure](operations.md) still applies inside containers. Copy
backups out securely before deleting volumes. Do not raw-copy a running SQLite WAL.

## Remaining container gates

- Build and startup with the exact current CLI, non-root volume initialization,
  read-only execution, health probes and graceful drain.
- Linux amd64 and arm64 smoke/restore/upgrade drills.
- Digest-pin verified base images; version tags currently remain mutable.
- Measure image size, scan OS packages, generate image SBOM and signed provenance.
- No GHCR image is published and no multi-arch support is claimed.
