"""Supabase and Upstash adapters: failures become BackendError without leaking bodies."""

from __future__ import annotations

import httpx
import pytest
import respx

from mcp_bootstrap.domain.errors import BackendError, ConfigError
from mcp_bootstrap.infrastructure.supabase_client import SupabaseClient
from mcp_bootstrap.infrastructure.upstash_cache import UpstashCache

SUPABASE = "https://db.supabase.test"
UPSTASH = "https://cache.upstash.test"


@respx.mock
async def test_supabase_error_does_not_echo_the_body() -> None:
    respx.get(f"{SUPABASE}/rest/v1/tenants").mock(
        return_value=httpx.Response(500, json={"message": "ROW-DATA-LEAK"})
    )
    with pytest.raises(BackendError) as caught:
        await SupabaseClient(SUPABASE, "service-key").get_tenant_row("t1")
    assert "ROW-DATA-LEAK" not in caught.value.message


@respx.mock
async def test_supabase_network_failure_is_a_backend_error() -> None:
    respx.get(f"{SUPABASE}/rest/v1/tenants").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(BackendError):
        await SupabaseClient(SUPABASE, "service-key").get_tenant_row("t1")


def test_supabase_requires_configuration() -> None:
    with pytest.raises(ConfigError):
        SupabaseClient("", "")


@respx.mock
async def test_upstash_incr_arms_the_ttl_only_on_the_first_hit() -> None:
    route = respx.post(UPSTASH).mock(
        side_effect=[
            httpx.Response(200, json={"result": 1}),
            httpx.Response(200, json={"result": 1}),
            httpx.Response(200, json={"result": 2}),
        ]
    )
    cache = UpstashCache(UPSTASH, "tok")
    assert await cache.incr("k", ttl_seconds=60) == 1
    assert await cache.incr("k", ttl_seconds=60) == 2
    commands = [call.request.content for call in route.calls]
    assert b"EXPIRE" in commands[1] and len(commands) == 3


@respx.mock
async def test_upstash_command_error_is_a_backend_error() -> None:
    respx.post(UPSTASH).mock(return_value=httpx.Response(200, json={"error": "WRONGTYPE"}))
    with pytest.raises(BackendError):
        await UpstashCache(UPSTASH, "tok").get("k")
