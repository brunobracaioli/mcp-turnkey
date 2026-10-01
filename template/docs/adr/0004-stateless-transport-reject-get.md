# ADR 0004 — Stateless streamable-HTTP transport; GET/DELETE answer 405

- Status: accepted
- Date: inherited from the template

## Context

On Vercel every request may land on a different instance, so a stateful
`Mcp-Session-Id` is lost between instances. A GET on `/api/mcp` opens an SSE stream that
idles until the function's `maxDuration` — and idle function time is billed. In
production this has cost tens of GB-hours per day on a single connector.

## Decision

- `stateless_http=True` and `json_response=True`: every POST is self-contained.
- `TenantAuthMiddleware` answers **405 (`Allow: POST`) before authentication** to any
  method other than POST on the MCP path (the spec allows 405 when the server offers no
  SSE stream).
- The SDK's DNS-rebinding protection is off: it targets localhost servers and would
  answer 421 to every remote `Host`.

## Consequences

- No server→client notifications (not used).
- No billed idle connections.
