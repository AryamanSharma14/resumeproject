# Security Policy

## Supported versions

Security fixes land on the default branch (`main`) and are released from
tags. Only the latest tagged release is supported.

## Reporting a vulnerability

Do not report vulnerabilities through public GitHub issues.

Use GitHub's private security advisory reporting for this repository.
Response targets: acknowledgment within 3 business days, triage decision
within 7 days, fix or explicit mitigation plan in the next release.

## Scope

Relay is a local-first, single-operator developer tool. The trust model,
assets and STRIDE summary are documented in the repository's security
specification. Out of scope for v1: hostile multi-tenant users, sandboxing
arbitrary user code, and post-compromise scenarios on an already-controlled
machine.

Please include: affected version/commit, environment, reproduction steps and
any logs with secrets already redacted.
