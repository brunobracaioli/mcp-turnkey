# MCP Turnkey — project instructions

The repository of an MCP server template. Two parts:

- `template/` — a real MCP server (package `mcp_bootstrap`). It has its own `CLAUDE.md`,
  `pyproject.toml`, tests and docs; work in it as in any MCP server.
- `scripts/scaffold.py` + `tests/test_scaffold.py` — the generator (standard library only).

## Rules

- Inside `template/`, the word `bootstrap` only appears as an identity token (package,
  slug, display name). The scaffold fails (exit 1) if any other occurrence survives.
- Every template change keeps `ruff`, `ruff format --check`, `mypy --strict` and
  `pytest` green **and** the end-to-end scaffold green (`pytest` at the root).
- Production lessons go to `docs/explanation/production-lessons.md`.
- Never commit secrets; never read `.env*`, `.secrets/` or `client_secret_*`.

## Commands

```bash
(cd template && ruff check . && ruff format --check . && mypy src && pytest -q)
ruff check . && mypy && pytest -q
python scripts/scaffold.py --name <kebab> [--title "..."] [--dest DIR]
```
