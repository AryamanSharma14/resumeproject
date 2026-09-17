# Security boundary

Relay trusts the local operator, installed package, and registered handler code.
It does not defend against a compromised host or another privileged local process.
Keep the API on loopback; do not put a reverse proxy, tunnel, or public port in front
of it without a separate reviewed authentication/TLS design.

`relay init` creates a random credential in the local data directory and restricts
its permissions (POSIX mode or Windows ACL). The server and CLI read this token
without putting it in argv. The dashboard uses an in-memory token, not a cookie or
persistent browser storage. API and metrics requests require bearer authentication;
health probes do not.

## Operator responsibilities

- Treat queue payloads, results, logs, database backups and token files as sensitive.
- Keep data off synced folders and network shares; limit directory access.
- Do not paste tokens or production payloads into issues, screenshots or logs.
- Do not register untrusted code. Child processes provide operational isolation,
  not a security sandbox.
- Review dependencies and image contents; a checksum detects changes, not trust.

Lockfile SBOM output is an inventory, not a vulnerability scan or license clearance.
Python lock entries do not supply reliable license/notice metadata. Those reviews
and image OS-package inventories remain release gates.

## Reporting vulnerabilities

Do not disclose exploit details in a public issue. Read the repository's
`relay/SECURITY.md` for the maintainer's current private reporting policy. The
private-advisory channel must be enabled and exercised before public launch; this
site does not claim that a public security response service is already operational.
