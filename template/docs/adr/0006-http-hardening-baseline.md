# ADR 0006 — HTTP hardening baseline

- Status: accepted
- Date: inherited from the template

## Context

A remote MCP server is a public web service with an OAuth surface. Typical MCP server
examples ship without security headers, correlation ids or rate limits on the public
OAuth endpoints, and accept any Dynamic Client Registration payload.

## Decision

- `SecurityHeadersMiddleware`: HSTS (2 years, preload), `nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy`, CSP `default-src 'none'; frame-ancestors 'none'; …`,
  `Permissions-Policy` and `Cache-Control: no-store` on every response that does not set
  its own.
- `CorrelationIdMiddleware`: accepts a safe `X-Request-ID` (≤128, `[A-Za-z0-9._:-]`) or
  `x-vercel-id`, otherwise generates a uuid4. Echoes it on the response and injects it in
  every JSON log line.
- Per-IP rate limit (fixed window in Upstash, fail-open) on `/register`, `/authorize`,
  `/authorize/consent` and `/token` → 429 + `Retry-After`.
- DCR validated by a Pydantic schema (https redirects, or http on loopback; ≤ 10 URIs).
- `httpx`/`httpcore` loggers at WARNING (at INFO they log URLs that can carry tokens).

## Consequences

- HTML responses (consent screen, login error pages) cannot use scripts or inline CSS.
- Fail-open rate limiting: an Upstash blip does not take logins down; authentication
  remains the real barrier.
