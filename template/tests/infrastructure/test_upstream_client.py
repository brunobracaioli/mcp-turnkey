"""Upstream REST client: auth header, retries, one re-auth, error mapping."""

from __future__ import annotations

import httpx
import pytest
import respx

from fakes import FakeClock
from mcp_bootstrap.domain.errors import (
    AuthError,
    NotFoundError,
    RateLimitError,
    TransientError,
    ValidationError,
)
from mcp_bootstrap.infrastructure.upstream_client import UpstreamAPIClient

BASE = "https://api.upstream.test/v1"


class Tokens:
    def __init__(self) -> None:
        self.forced = 0

    async def access_token(self, *, force_refresh: bool = False) -> str:
        if force_refresh:
            self.forced += 1
        return f"tok-{self.forced}"


def _client(tokens: Tokens, clock: FakeClock) -> UpstreamAPIClient:
    return UpstreamAPIClient(BASE, tokens, clock)


@respx.mock
async def test_sends_the_bearer_and_decodes_json() -> None:
    route = respx.get(f"{BASE}/items").mock(return_value=httpx.Response(200, json={"items": []}))
    body = await _client(Tokens(), FakeClock()).get("items", params={"limit": 1})
    assert body == {"items": []}
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok-0"


@respx.mock
async def test_retries_transient_errors_with_backoff() -> None:
    respx.get(f"{BASE}/items").mock(
        side_effect=[httpx.Response(503), httpx.Response(502), httpx.Response(200, json={})]
    )
    clock = FakeClock()
    assert await _client(Tokens(), clock).get("items") == {}
    assert clock.sleeps == [0.5, 1.0]


@respx.mock
async def test_gives_up_after_the_retry_budget() -> None:
    respx.get(f"{BASE}/items").mock(return_value=httpx.Response(500))
    with pytest.raises(TransientError):
        await _client(Tokens(), FakeClock()).get("items")


@respx.mock
async def test_network_errors_become_transient_errors() -> None:
    respx.get(f"{BASE}/items").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(TransientError):
        await _client(Tokens(), FakeClock()).get("items")


@respx.mock
async def test_401_forces_one_refresh_then_succeeds() -> None:
    respx.get(f"{BASE}/items").mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json={"ok": True})]
    )
    tokens = Tokens()
    assert await _client(tokens, FakeClock()).get("items") == {"ok": True}
    assert tokens.forced == 1


@respx.mock
async def test_repeated_401_is_an_auth_error() -> None:
    respx.get(f"{BASE}/items").mock(return_value=httpx.Response(401))
    tokens = Tokens()
    with pytest.raises(AuthError):
        await _client(tokens, FakeClock()).get("items")
    assert tokens.forced == 1


@respx.mock
async def test_404_maps_to_not_found() -> None:
    respx.get(f"{BASE}/items/x").mock(return_value=httpx.Response(404, json={"message": "nope"}))
    with pytest.raises(NotFoundError):
        await _client(Tokens(), FakeClock()).get("items/x")


@respx.mock
async def test_429_carries_retry_after() -> None:
    respx.get(f"{BASE}/items").mock(return_value=httpx.Response(429, headers={"Retry-After": "7"}))
    with pytest.raises(RateLimitError) as caught:
        await _client(Tokens(), FakeClock()).get("items")
    assert caught.value.retry_after_seconds == 7


@respx.mock
async def test_400_message_is_passed_through_but_capped() -> None:
    long = "x" * 1000
    respx.post(f"{BASE}/items").mock(
        return_value=httpx.Response(400, json={"error": {"message": long}})
    )
    with pytest.raises(ValidationError) as caught:
        await _client(Tokens(), FakeClock()).post("items", {"name": ""})
    assert len(caught.value.message) == 300
