# ADR 0001 — A living template plus a scaffold script

- Status: accepted
- Date: 2026-10-01

## Context

MCP servers for different upstream APIs share most of their code: the OAuth 2.1
Authorization Server, the upstream OAuth, encrypted token storage, tenant isolation,
the transport and the hardening. Starting each new server by cloning the previous one
copies the old provider's domain along with it, and fixes discovered later (405 on GET,
503 on backend failures, quoted env vars, httpx logging tokens) reach some servers and
not others. Options considered:

1. **Cookiecutter/Copier** — Jinja templates are not executable; the template itself
   runs no tests, so it rots without anyone noticing.
2. **A shared library** (an `mcp-core` package) — couples every server to a common
   release, against the goal of each server having its own deploy and lifecycle.
3. **A living template + scaffold** — the template is a real MCP server, with tests,
   exercised by CI; a standard-library script copies and renames it.

## Decision

Option 3. `template/` is a complete project (package `mcp_bootstrap`, slug `bootstrap`)
that passes `ruff`, `mypy --strict` and `pytest` on its own. `scripts/scaffold.py`
generates `../mcp-<name>` by replacing tokens, renaming paths, drawing a new tenant
namespace and stamping the migration. CI runs the template's tests **and** an end-to-end
scaffold whose output must pass the same checks.

## Consequences

- The template may only use the word `bootstrap` as an identity token (the scaffold
  exits with 1 if any occurrence survives).
- Template improvements do not flow into already-generated servers by themselves —
  porting is manual (`docs/explanation/production-lessons.md` lists what to port).
- No Jinja/cookiecutter dependency: the scaffold runs before any virtualenv exists.
