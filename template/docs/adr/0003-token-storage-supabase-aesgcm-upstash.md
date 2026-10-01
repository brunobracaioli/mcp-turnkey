# ADR 0003 — Upstream tokens in Supabase, encrypted (AES-256-GCM), with an Upstash cache

- Status: accepted
- Date: inherited from the template

## Context

Serverless functions share no memory. We must persist each tenant's upstream token, the
ephemeral OAuth state and rate-limit counters.

## Decision

- Supabase (PostgREST over httpx, service-role key) stores tenants, tokens, DCR clients
  and refresh tokens (hash only). RLS is default-deny on every table.
- The sensitive material (access token, refresh token, expiry) is serialized and
  encrypted as one AES-256-GCM blob (96-bit nonce per write, `TOKEN_ENCRYPTION_KEY` only
  in the environment).
- Upstash Redis (REST) holds the ephemeral state (consents, login requests, codes),
  rate-limit counters and a cache of the **encrypted row** (TTL 300 s, invalidated on
  save/clear).
- Every Redis key is prefixed with the server slug.
- One **dedicated** Supabase project per server is the recommended setup.

## Consequences

- A database leak without the encryption key does not expose tokens.
- A database/cache failure while verifying a bearer answers 503 (`backend_unavailable`),
  never 401 — a 401 tells a legitimate client to throw away a good credential.
- **Known limitation:** providers that rotate the refresh token can race when two
  concurrent requests of the same tenant refresh at once; the loser stores a refresh token
  that was already invalidated. Future mitigation: a per-tenant lock in Upstash
  (`SET NX`) around the refresh.
