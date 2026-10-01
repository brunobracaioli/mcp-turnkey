# ADR 0005 — Tenant identity comes from the upstream account; lifecycle via `status`

- Status: accepted
- Date: inherited from the template

## Context

Each user brings their own upstream account. The server needs a tenant id that is stable
across logins, devices and MCP clients, that no tool argument can influence, and that an
operator can switch off without deleting data.

## Decision

- `tenant_id = uuid5(server namespace, upstream subject)`, where the subject is the id
  the upstream returned for the exchanged code (never a client-supplied value). The same
  account always lands in the same tenant; the scaffold draws a fresh namespace per server.
- `tenants.upstream_subject` has a unique index: one account belongs to one tenant.
- The tenant of a request is taken **only** from the validated MCP credential and bound
  to a `ContextVar` (`RequestScope`); no tool accepts a `tenant_id`.
- `tenants.status` (`active` | `suspended` | `revoked`) is an operator switch, changed
  with SQL. A non-active tenant cannot log in again (the callback refuses it) nor refresh
  its MCP token; a JWT already issued lapses within its 8 h TTL. Logins never write
  `status`, so a suspension survives a reconnect.

## Consequences

- A prompt cannot point a tool at another tenant: there is no parameter to abuse.
- Suspending is instant for new sessions and bounded (≤ 8 h) for open ones; making it
  instant everywhere would need a status lookup per request (a cached one is the natural
  extension point in `ProdContainer.verify_token`).
- Provisioning tenants on someone else's behalf (an admin API, API keys) is out of scope;
  it is a separate control plane with its own threat model.
