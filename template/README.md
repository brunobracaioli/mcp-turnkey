# MCP Bootstrap

Multi-tenant [MCP](https://modelcontextprotocol.io) server for the Bootstrap API.
Each user connects their own upstream account via OAuth; tools only ever see the data
of the tenant behind the presented credential.

- **Local:** stdio for Claude Code / Claude Desktop, file-backed token, manual login.
- **Hosted:** Vercel serverless; this server is its own OAuth 2.1 Authorization Server
  (DCR + PKCE + per-client consent screen), tokens encrypted at rest in Supabase,
  Upstash for ephemeral state.

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q
cp .env.example .env.local   # fill UPSTREAM_CLIENT_ID / UPSTREAM_CLIENT_SECRET
cp .mcp.json.example .mcp.json
```

## Checks

```bash
ruff check . && ruff format --check . && mypy src && pytest -q
```

## Docs

| | |
|---|---|
| Spec | [`docs/specs/mcp-bootstrap.md`](docs/specs/mcp-bootstrap.md) |
| Decisions | [`docs/adr/`](docs/adr/) |
| Threat model | [`docs/security/threats/mcp-bootstrap.md`](docs/security/threats/mcp-bootstrap.md) |
| Tutorial | [`docs/tutorials/first-run-locally.md`](docs/tutorials/first-run-locally.md) |
| How-to | [`docs/how-to/`](docs/how-to/) (add a tool slice, OAuth, deploy, BYOT) |
| Reference | [`docs/reference/`](docs/reference/) (HTTP endpoints, env vars, tools) |
| Explanation | [`docs/explanation/architecture.md`](docs/explanation/architecture.md) |
