"""MCP presentation layer: tool surface, annotations and error translation."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from fakes import FakeUpstream
from mcp_bootstrap import server
from mcp_bootstrap.config import SERVICE_SLUG
from mcp_bootstrap.container import Container
from mcp_bootstrap.domain.errors import NotFoundError
from mcp_bootstrap.domain.ports import UpstreamClient


class FakeHost:
    def __init__(self, api: Any) -> None:
        self._api = api

    @property
    def api(self) -> UpstreamClient:
        return self._api  # type: ignore[no-any-return]

    async def auth_login(self) -> dict[str, Any]:
        return {"connected": True}

    async def auth_submit_callback(self, callback: str) -> dict[str, Any]:
        return {"success": True}

    async def auth_status(self) -> dict[str, Any]:
        raise RuntimeError("internal detail that must not leak")

    async def auth_refresh(self) -> dict[str, Any]:
        return {"success": True}


class Missing(FakeUpstream):
    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotFoundError("The requested upstream object was not found.")


@pytest.fixture
def host() -> Iterator[None]:
    yield
    server.set_container(Container())


async def test_tool_surface_and_annotations() -> None:
    tools = {t.name: t for t in await server.mcp.list_tools()}
    assert {
        f"{SERVICE_SLUG}_login",
        f"{SERVICE_SLUG}_token_status",
        "list_items",
        "delete_item",
    } <= set(tools)
    assert tools["list_items"].annotations.readOnlyHint is True  # type: ignore[union-attr]
    assert tools["delete_item"].annotations.destructiveHint is True  # type: ignore[union-attr]
    assert tools["create_item"].annotations.destructiveHint is False  # type: ignore[union-attr]


async def test_tools_call_the_active_host(host: None) -> None:
    api = FakeUpstream({("GET", "items"): {"items": [{"id": "i1", "name": "One"}]}})
    server.set_container(FakeHost(api))
    assert await server.list_items(limit=3) == [{"id": "i1", "name": "One"}]


async def test_domain_errors_reach_the_model_verbatim(host: None) -> None:
    server.set_container(FakeHost(Missing()))
    with pytest.raises(ToolError, match="not found"):
        await server.get_item("i1")


async def test_unexpected_errors_are_generic(host: None) -> None:
    server.set_container(FakeHost(FakeUpstream()))
    with pytest.raises(ToolError) as caught:
        await server.token_status()
    assert "internal detail" not in str(caught.value)


async def test_input_schema_rejects_path_smuggling_ids() -> None:
    with pytest.raises(ToolError, match="pattern"):
        await server.mcp.call_tool("get_item", {"item_id": "../admin"})
