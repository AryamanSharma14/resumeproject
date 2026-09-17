# Relay Security Specification

Status: planning specification. Controls listed here are requirements for v1.0, not claims about existing code. Trust boundary: local-first, trusted-code, single-operator developer tool.

## 1. Assets and trust model
Assets: local SQLite queue DB (job payloads/results/logs), installation API token, host process integrity, local network interface.
Trusted: the machine owner, installed Relay code, registered built-in handlers.
Untrusted: HTTP clients without the token, web content loaded in the dashboard browser context, anything arriving in job payloads (treated as data, never code).
Out of scope for v1: hostile multi-tenant users, sandboxing arbitrary user code, protecting a machine that is already compromised.

## 2. Threats and controls (STRIDE summary)
| Threat | Control |
|---|---|
| Unauthorized job access/cancellation from local processes or LAN | Loopback bind by default; bearer token required for all /api and /metrics routes; explicit allowed Host; no wildcard credentialed CORS |
| Token theft via logs/URLs/argv | Token generated locally, stored with restricted OS permissions, sent only in Authorization header; never logged, never in query strings or argv; redaction in log pipeline |
| XSS via payloads/results/logs | JSON rendered as text in <pre>, HTML never injected; UI framework escaping; static assets served with strict CSP (no inline script, no remote origins) |
| SQL injection | Parameterized statements only; no string-built SQL; no raw-SQL endpoint |
| CSRF on dashboard mutations | Token-in-memory SPA model avoids ambient cookies at v1; any future cookie session requires CSRF tokens, SameSite and logout design (ADR required) |
| Malicious handler execution | Registry of built-in handlers only; no API-supplied import paths, no pickle, no eval, no shell; handler inputs schema-validated and size-capped |
| Resource exhaustion | Bounded payloads/results/logs, request size limits, pagination caps, watchdog timeouts, bounded concurrency, per-connection busy timeouts |
| Supply chain | uv/npm lockfiles committed; CI uses --locked/frozen; GitHub Actions pinned by digest, minimal permissions; SBOM generated per release; artifacts checksummed and Sigstore-signed; Dependabot enabled |
| Stale worker writes across identity changes | Attempt tokens + lease fencing (implementation-plan 6.6); ownership is integrity control, not identity provider |
| Denial of service by local user | Out of scope at v1; documented |

## 3. Authentication design
- `relay init` creates data directory and a 256-bit random token with restrictive file permissions (POSIX 0600; Windows ACL restricted to user).
- CLI reads token from `RELAY_TOKEN` or config file; refuses argv/URL transmission.
- Dashboard: token entered at start, held in memory only (not localStorage); 401 explains this flow; logout clears memory.
- /health/live and /health/ready are unauthenticated but disclose no job data.
- Remote deployment (v1 non-goal): must add TLS + reviewed auth; the server refuses non-loopback bind without an explicit unsupported-override flag, and the docs say the truth about it.

## 4. Data handling
- UTC timestamps; explicit nullable fields; no PII assumptions; redact known sensitive keys in logs/results (best-effort, documented as such).
- Payload/result caps (64 KiB proposed) and error text caps enforced at validation and storage layers.
- Prune is explicit, terminal-jobs-only, dry-run first; documented side effect: expires idempotency protection for pruned jobs.
- Backups via SQLite backup API; backup files inherit restrictive permissions; restore tested (T22).

## 5. Process security
- Children run via explicit spawn context; no inherited DB connections (asserted by test); per-attempt IPC channel disposed after use.
- Watchdog terminates hung children; graceful drain bounded; no arbitrary descendant cleanup promised (documented limitation).
- Children are trusted code: this is isolation against accidents, not adversaries; no general sandbox promised.

## 6. Vulnerability process
SECURITY.md publishes a private reporting channel (GitHub security advisories) and response targets: acknowledge 3 business days, triage 7 days, fix/next-release policy documented. SECURITY.md ships in Phase A; policy is marked as the commitment, and the channel is exercised (test advisory) before v1.0.

## 7. Security acceptance criteria
Auth tests: no-token 401 on every protected route; token in URL rejected; CORS preflight negative cases. Injection tests on every query parameter. Size-limit tests (413). CSP headers asserted in integration tests. Supply-chain: CI fails on unpinned actions or missing lockfile sync; release pipeline publishes SBOM + checksums + signatures; pipx install verified from clean VM. Threat model reviewed at each phase gate; changes require ADR if the boundary moves.
