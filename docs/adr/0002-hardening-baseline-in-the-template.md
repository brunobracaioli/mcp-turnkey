# ADR 0002 — The template carries the full hardening baseline

- Status: accepted
- Date: 2026-10-01

## Context

Typical MCP server code — examples, quick starts, and servers grown from them — tends to
share the same gaps: no security headers or correlation id, no CI, a DCR endpoint that
only checks that some redirect URI exists, no rate limit on the public OAuth routes. The
fixes that do exist are learned one incident at a time and end up in some servers only.

## Decision

The template adopts every fix already proven in production **plus** a baseline that a
public OAuth-facing service should have from day one: security headers, per-IP rate
limits, structured logs with a correlation id, a per-client consent screen, and CI with
`ruff`/`mypy --strict`/`pytest`/`pip-audit`/`gitleaks`. Product-specific features
(billing or licensing gates, mutation plan-hashes, background queues, media staging,
admin/provisioning APIs) stay out: they are decisions of each server, not of the base.

## Consequences

- New servers start above the level a hand-rolled server usually reaches.
- More tests in the template (~190) — a cost paid once and reused by every scaffold.
- The template is opinionated about its stack (Vercel, Supabase, Upstash); the ports in
  `domain/ports.py` keep replacing any of them an adapter-sized change.
