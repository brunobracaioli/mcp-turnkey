"""Vercel ASGI entrypoint.

Vercel's ``@vercel/python`` runtime (``"framework": "python"`` in vercel.json) detects
the module-level ``app`` here and serves it, running its lifespan (the MCP session
manager). The application lives in ``src/mcp_bootstrap/asgi.py``; this shim only puts
``src`` on the path. Do not replace it with an ``api/index.py`` + catch-all rewrite:
without a root ``app.py`` Starlette receives the literal ``/api/index`` path and every
route 404s (a production failure mode, not a hypothetical).
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "src"))

from mcp_bootstrap.asgi import app  # noqa: F401  (path set above; re-exported for Vercel)
