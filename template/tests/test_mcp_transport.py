"""End to end: an authenticated JSON-RPC call through the real MCP transport.

The SDK's session manager can be started only once per process, so this module keeps
a single test that exercises the whole stack: OAuth login -> JWT -> tenant middleware
-> stateless streamable-HTTP -> FastMCP tool listing.
"""

from __future__ import annotations

import pytest

from asgi_support import Env, client, install, login
from mcp_bootstrap import asgi
from mcp_bootstrap.config import SERVICE_SLUG


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Env:
    return install(monkeypatch)


async def test_tools_list_over_the_authenticated_transport(env: Env) -> None:
    async with asgi.mcp.session_manager.run(), client() as c:
        tokens = await login(c, env)
        resp = await c.post(
            "/api/mcp",
            headers={
                "Authorization": f"Bearer {tokens['access_token']}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
    assert resp.status_code == 200, resp.text
    names = {tool["name"] for tool in resp.json()["result"]["tools"]}
    assert f"{SERVICE_SLUG}_token_status" in names
    assert resp.headers["X-Request-ID"]
