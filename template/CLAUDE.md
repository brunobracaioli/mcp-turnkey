# MCP Bootstrap — project instructions

Multi-tenant MCP server (Python 3.10+, FastMCP, Vercel), generated from an MCP server
template. Spec-driven, layered, strictly typed and tested.

## Before any feature

1. Update `docs/specs/mcp-bootstrap.md` (tool contract, edge cases, acceptance).
2. Surface change (route, destructive write, provider) → update
   `docs/security/threats/mcp-bootstrap.md`.
3. Structural decision → new ADR in `docs/adr/` (Nygard format).

## Layout and dependency rules

- `domain/` imports nothing from outside. `application/` only knows the ports in
  `domain/ports.py`. `infrastructure/` implements the ports. Composition only in
  `container.py`.
- Tools in `server.py` are thin: validate (schema) → use case → `_fail` on error.
- The tenant comes **only** from the credential (`RequestScope`); no tool takes a
  `tenant_id`.
- `SCAFFOLD:` markers flag provider-specific decisions still to be made.

## Commands

```bash
ruff check . && ruff format --check . && mypy src && pytest -q
python -m mcp_bootstrap            # stdio
python -m mcp_bootstrap --http     # Inspector at http://127.0.0.1:8000/mcp
python scripts/gen_keys.py         # FRESH production keys (never reuse)
```

## Pitfalls already paid for in production

- `mcp` stays `<2` (2.x removed `mcp.server.fastmcp`).
- `vercel.json` needs `"framework": "python"` + the root `app.py`, otherwise 404.
- Vercel variables **without quotes**; never copy secrets from another server.
- A database/cache error during authentication → 503, never 401.
- `httpx`/`httpcore` stay at WARNING (they leak tokens carried in URLs).
- After a deploy that changes tools, reconnect the connector in claude.ai (schema cache).
- The post-edit hook runs `ruff check --fix`: add an import together with its first use.
- Never read or print `.env*`, `.secrets/` or `client_secret_*.json`.
