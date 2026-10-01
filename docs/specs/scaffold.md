# Spec — the scaffold and the living template

Status: **accepted** · Date: 2026-10-01

## Goal

Building a remote, multi-tenant MCP server is mostly the same work every time: an OAuth
2.1 Authorization Server for MCP clients, the upstream provider's OAuth, encrypted token
storage, tenant isolation, serverless quirks and HTTP hardening. Copying a previous
server to start a new one has three problems:

1. the copy carries the source provider's names and rules (user-id fields, error
   classes, scopes) that must be hunted down by hand;
2. every cross-cutting fix (the `mcp<2` cap, 405 on `GET /api/mcp`, httpx logging
   tokens, 503 instead of 401 on backend failures) has to be ported repo by repo, and
   ends up applied unevenly;
3. the baseline you would want everywhere (CI, security headers, rate limits on the
   public OAuth endpoints, correlation ids) is rarely there in the first place.

This repository solves that with a **living template** (a complete, tested,
provider-agnostic MCP server) and a **scaffold** that copies it with the right names.

## Scope

**In:**

- `template/` is a complete Python project: local FastMCP stdio + a multi-tenant ASGI
  app for Vercel, the server as an OAuth 2.1 Authorization Server with an
  upstream-native (generic OAuth 2.0) login and a per-client consent screen, encrypted
  credentials (AES-256-GCM) in Supabase, ephemeral state in Upstash, a validation cron
  and an example slice (`items`) covering a read, a write with preview and a destructive
  call with confirm.
- `scripts/scaffold.py` generates `../mcp-<name>` from the template, standard library only.
- This repository's CI: the template's checks + an end-to-end scaffold whose output must
  pass its own checks.
- Documentation: ADRs, how-tos, the lessons that shaped the template.

**Out:**

- Product features that only some servers need: billing/licensing gates, mutation
  plan-hashes, background queues, media staging buckets, an admin/provisioning API.
  They belong in the generated server, behind its own spec and threat model.
- Migrating existing servers to the template.
- Publishing to a registry (PyPI, cookiecutter, copier).

## Contracts

### Scaffold (CLI)

```
python scripts/scaffold.py --name <kebab> [--title "<Title>"] [--dest <dir>] [--force]
```

| Input | Rule |
|---|---|
| `--name` | `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`, 2–40 chars, no `mcp-` prefix (it is added), must not contain `bootstrap` |
| `--title` | 1–60 chars: letters, digits, space and `. & + -` (no quotes or `\`, since it becomes a Python/TOML/JSON literal), starting with a letter or digit, must not contain `bootstrap`; default = `--name` in Title Case |
| `--dest` | default `../mcp-<name>` relative to this repository; refuses a non-empty directory without `--force` |

Output: the template tree with its tokens replaced (table below), the
`src/mcp_bootstrap` directory renamed, the migration stamped with a UTC timestamp, a
**new** uuid5 tenant namespace (random uuid4), executable bits preserved (hooks) and a
list of the remaining `SCAFFOLD:` markers (file:line) for the developer to resolve — only
lines that *start* with the marker (after `#`, `>`, `--` or `//`) count; mentions in
prose do not. Exit code `0` on success, `2` on invalid input, `1` if any `bootstrap`
occurrence survives in the result.

| Token in the template | Becomes (e.g. `--name acme-crm --title "Acme CRM"`) |
|---|---|
| `mcp_bootstrap` | `mcp_acme_crm` |
| `mcp-bootstrap` | `mcp-acme-crm` |
| `MCP Bootstrap` | `MCP Acme CRM` |
| `bootstrap` | `acme_crm` (slug: tool prefix, Redis namespace, OAuth scope) |
| `Bootstrap` | `Acme CRM` |
| `00000000-0000-4000-8000-0000b0075742` | a new uuid4 (tenant namespace) |
| `00000000000000_init.sql` | `<YYYYMMDDHHMMSS>_init.sql` |

### Template (the generated server)

HTTP surface (production): see `template/docs/reference/http-endpoints.md`.
Environment variables: see `template/docs/reference/env-vars.md`.

## Edge cases

- `--name` with an `mcp-` prefix, uppercase, `_`, double hyphen: rejected (exit 2).
- A destination that is this repository or inside it: rejected.
- Binary files (icons) are copied without text substitution.
- Local artifacts (`venv/`, `.venv/`, caches, `.env.local`, `.secrets/`) are never
  copied, even if they exist in the template.
- Upstream without refresh tokens (long-lived tokens, BYOT): the credential stores only
  the access token; the client is asked to reconnect when it expires.
- Upstream with rotating refresh tokens: the new token is persisted (encrypted) on every
  refresh. A race between two simultaneous refreshes of the same tenant is a known
  limitation (see the template's ADR 0003).

## Acceptance criteria

1. `pytest` green inside `template/`, with `ruff check`, `ruff format --check` and
   `mypy --strict` clean.
2. `scaffold.py --name acme-crm` generates a project where `pytest`, `ruff` and `mypy`
   pass without any manual edit.
3. The generated project does not contain the string `bootstrap` (case-insensitive).
4. Two scaffolds produce different tenant namespaces.
5. The generated server, in production:
   - answers 405 to GET/DELETE on `/api/mcp` before authenticating;
   - answers 401 with `WWW-Authenticate` (PRM) without a bearer;
   - answers 503 (never 401/500) when the credential store or verifier is unavailable;
   - sends HSTS, `nosniff`, `X-Frame-Options: DENY`, CSP, `Referrer-Policy` and
     `X-Request-ID` on every response;
   - shows a per-client consent screen before the provider and binds `state` to the
     browser with a `__Host-` cookie;
   - rate-limits `/register`, `/authorize`, `/authorize/consent` and `/token` per IP
     (429 + `Retry-After`), failing open if Upstash is down;
   - rejects DCR with a `redirect_uri` outside https/loopback;
   - refuses a new login of a suspended or revoked tenant;
   - never logs a token (httpx/httpcore at WARNING).
6. This repository's CI runs (1) and (2) on every push.
