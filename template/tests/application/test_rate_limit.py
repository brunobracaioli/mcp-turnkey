"""Fixed-window rate limiting is enforced, and fails open."""

from __future__ import annotations

from fakes import FailingCache, FakeCache
from mcp_bootstrap.application import rate_limit
from mcp_bootstrap.config import SERVICE_SLUG


async def test_allows_up_to_the_limit_then_blocks() -> None:
    cache = FakeCache()
    results = [await rate_limit.allow(cache, "k", limit=2, window_seconds=60) for _ in range(3)]
    assert results == [True, True, False]
    assert cache.ttls["k"] == 60


async def test_fails_open_without_a_cache() -> None:
    assert await rate_limit.allow(None, "k", limit=1, window_seconds=60)


async def test_fails_open_when_the_cache_errors() -> None:
    assert await rate_limit.allow(FailingCache(), "k", limit=1, window_seconds=60)


def test_ip_keys_are_namespaced() -> None:
    assert rate_limit.ip_key("token", "1.2.3.4") == f"{SERVICE_SLUG}:rl:token:1.2.3.4"
