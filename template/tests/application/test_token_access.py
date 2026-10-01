"""Upstream access-token supply: reuse, refresh, persist, fail closed."""

from __future__ import annotations

import pytest

from fakes import FakeClock, FakeOAuth, FakeTokenStore
from mcp_bootstrap.application.token_access import TokenAccess, validate_token
from mcp_bootstrap.domain.errors import AuthError, ConfigError
from mcp_bootstrap.domain.models import StoredToken


def _expired(clock: FakeClock, refresh: str | None = "rt-acct1-0") -> StoredToken:
    return StoredToken(
        access_token="at-acct1-0", refresh_token=refresh, access_expires_at=int(clock.now()) - 1
    )


async def test_returns_the_stored_token_while_usable() -> None:
    clock, oauth = FakeClock(), FakeOAuth()
    store = FakeTokenStore(
        StoredToken(access_token="at-acct1-0", access_expires_at=int(clock.now()) + 3600)
    )
    assert await TokenAccess(store, oauth, clock).access_token() == "at-acct1-0"
    assert oauth.refresh_calls == []


async def test_refreshes_an_expired_token_and_persists_it() -> None:
    clock, oauth = FakeClock(), FakeOAuth()
    store = FakeTokenStore(_expired(clock))
    access = await TokenAccess(store, oauth, clock).access_token()
    assert access != "at-acct1-0"
    assert store.token is not None and store.token.access_token == access
    assert store.token.refresh_token == "rt-acct1-0"  # kept: provider did not rotate


async def test_a_rotated_refresh_token_is_persisted() -> None:
    clock, oauth = FakeClock(), FakeOAuth()
    oauth.rotate_refresh = True
    store = FakeTokenStore(_expired(clock))
    await TokenAccess(store, oauth, clock).access_token()
    assert store.token is not None and store.token.refresh_token != "rt-acct1-0"


async def test_force_refresh_ignores_a_usable_token() -> None:
    clock, oauth = FakeClock(), FakeOAuth()
    store = FakeTokenStore(
        StoredToken(
            access_token="at-acct1-0",
            refresh_token="rt-acct1-0",
            access_expires_at=int(clock.now()) + 3600,
        )
    )
    await TokenAccess(store, oauth, clock).access_token(force_refresh=True)
    assert oauth.refresh_calls == ["rt-acct1-0"]


async def test_no_refresh_token_requires_reconnect() -> None:
    clock = FakeClock()
    store = FakeTokenStore(_expired(clock, refresh=None))
    with pytest.raises(AuthError):
        await TokenAccess(store, FakeOAuth(), clock).access_token()


async def test_not_connected_is_a_config_error() -> None:
    with pytest.raises(ConfigError):
        await TokenAccess(FakeTokenStore(), FakeOAuth(), FakeClock()).access_token()


async def test_validate_token_proves_the_identity() -> None:
    clock, oauth = FakeClock(), FakeOAuth()
    store = FakeTokenStore(StoredToken(access_token="revoked-token"))
    with pytest.raises(AuthError):
        await validate_token(store, oauth, clock)
