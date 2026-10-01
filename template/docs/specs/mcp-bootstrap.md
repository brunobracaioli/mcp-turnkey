# Spec — MCP Bootstrap

> Status: **draft** · Owner: _fill in_ · Last review: _fill in_
>
> SCAFFOLD: this spec was born from the template. Replace the example slice (`items`)
> with the upstream API's real resources and fill every _fill in_ before coding.

## 1. Goal

Expose the Bootstrap API to MCP clients (Claude Code, Claude Desktop, claude.ai) as a
**multi-tenant** server: each user connects their own upstream account through OAuth
and only ever sees their own data.

_fill in: which user problem this solves; which tasks the model must be able to do;
what is explicitly out of scope._

## 2. Scope

**In:** _fill in (resources, reads, writes)._

**Out:** _fill in (e.g. billing, bulk operations, binary uploads)._

## 3. Contracts

### 3.1 MCP tools

| Tool | Kind | Input | Output |
|---|---|---|---|
| `bootstrap_login` | auth | — | `authorize_url` (local) / connection state (hosted) |
| `bootstrap_submit_callback` | auth | `callback_url` (≤4096) | account + scopes |
| `bootstrap_token_status` | read | — | `authenticated`, account, scopes, expiry |
| `bootstrap_refresh_token` | auth | — | new expiry |
| `list_items` | read | `limit` 1–100 | list of `Item` |
| `get_item` | read | `item_id` (`^[A-Za-z0-9_-]{1,64}$`) | `Item` |
| `create_item` | write | `name` 1–200, `preview` | `WriteResult` |
| `delete_item` | destructive | `item_id`, `confirm` | `WriteResult` |

Rules for every tool: writes accept `preview` (validate and return the payload without
calling the upstream); destructive tools do nothing without `confirm=true`; the tenant
comes from the MCP credential, never from an argument.

### 3.2 HTTP

See [`docs/reference/http-endpoints.md`](../reference/http-endpoints.md).

## 4. Edge cases

- Expired upstream token without a refresh token → error asking to reconnect (never 500).
- Refresh token revoked upstream → `AuthError`; the cron records a failure.
- Upstream 401 in the middle of a call → one forced refresh and one retry.
- Upstream 429 → `RateLimitError` with `retry_after_seconds` when provided.
- Supabase/Upstash down → 503 with `Retry-After`, never 401.
- Ids with `/`, `..` or characters outside the pattern → rejected by the tool schema.
- _fill in: limits and quirks of the upstream API._

## 5. Acceptance criteria

- [ ] Every test in `tests/` passes; `ruff`, `ruff format --check` and `mypy --strict` clean.
- [ ] A full hosted login (DCR → authorize → consent screen → callback → token) yields
      a JWT that opens `/api/mcp` (consent: `oauth-client-consent.md`).
- [ ] A tenant never reads another tenant's data (the tenant comes only from the credential).
- [ ] Upstream tokens exist only encrypted (AES-256-GCM) in the database and the cache.
- [ ] No token, secret or PII appears in logs.
- [ ] _fill in: criteria of the real domain._
