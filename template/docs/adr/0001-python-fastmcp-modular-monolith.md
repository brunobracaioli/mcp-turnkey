# ADR 0001 — Python + FastMCP, layered modular monolith

- Status: accepted
- Date: inherited from the template

## Context

This server is meant to run in production for many users, live for years and be
changed by people (and coding agents) who did not write it. The official `mcp` SDK
(FastMCP) is the most widely deployed way to expose tools over MCP in Python, and a
serverless deploy (Vercel) keeps operations close to zero for a connector-sized service.

## Decision

- Python ≥3.10 and `mcp[cli]>=1.12,<2` (the 2.x line dropped `mcp.server.fastmcp`; an
  unbounded pin lets a fresh build resolve 2.0 and answer 500 on every route).
- Modular monolith with dependencies pointing inward: `domain/` (models, errors, ports,
  pure rules) ← `application/` (use cases, one module per slice) ← `infrastructure/`
  (adapters) and the presentation (`server.py` with thin tools, `asgi.py`/`middleware.py`
  for HTTP).
- `domain/` imports nothing from outside; `infrastructure/` implements the ports in
  `domain/ports.py`; composition happens only in `container.py` (`Container` for local
  stdio, `ProdContainer` for multi-tenant hosting).

## Consequences

- A new slice = a module in `application/` + tools in `server.py` + tests with fakes.
- Swapping the MCP SDK later only touches the presentation layer.
- `mypy --strict` covers `src/`; tests use duck-typed fakes of the ports, so the whole
  OAuth flow runs without network.
