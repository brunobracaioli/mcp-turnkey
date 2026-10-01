"""Local two-step login: PKCE + state, callback parsing, persistence."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from fakes import FakeClock, FakeOAuth, FakeTokenStore
from mcp_bootstrap.application import auth as auth_uc
from mcp_bootstrap.domain.errors import AuthError

REDIRECT = "http://localhost:8765/oauth/callback"


def _callback(code: str, state: str) -> str:
    return f"{REDIRECT}?code={code}&state={state}"


def test_start_login_carries_state_and_pkce_challenge() -> None:
    pending = auth_uc.start_login(FakeOAuth(), REDIRECT)
    query = parse_qs(urlsplit(pending.authorize_url).query)
    assert query["state"] == [pending.state]
    assert query["code_challenge"][0]
    assert pending.code_verifier


async def test_complete_login_persists_the_identified_token() -> None:
    oauth, store = FakeOAuth(), FakeTokenStore()
    oauth.codes["c1"] = "acct1"
    oauth.labels["acct1"] = "owner@example.test"
    pending = auth_uc.start_login(oauth, REDIRECT)
    token = await auth_uc.complete_login(
        store, oauth, FakeClock(), pending=pending, callback=_callback("c1", pending.state)
    )
    assert token.subject == "acct1"
    assert store.token == token
    assert oauth.exchange_calls[0]["code_verifier"] == pending.code_verifier


async def test_state_mismatch_is_rejected() -> None:
    oauth = FakeOAuth()
    oauth.codes["c1"] = "acct1"
    pending = auth_uc.start_login(oauth, REDIRECT)
    with pytest.raises(AuthError):
        await auth_uc.complete_login(
            FakeTokenStore(),
            oauth,
            FakeClock(),
            pending=pending,
            callback=_callback("c1", "forged"),
        )


async def test_a_bare_code_without_state_is_rejected() -> None:
    oauth = FakeOAuth()
    pending = auth_uc.start_login(oauth, REDIRECT)
    with pytest.raises(AuthError):
        await auth_uc.complete_login(
            FakeTokenStore(), oauth, FakeClock(), pending=pending, callback="c1"
        )


def test_parse_callback_surfaces_a_denied_consent() -> None:
    with pytest.raises(AuthError):
        auth_uc.parse_callback(f"{REDIRECT}?error=access_denied&state=s")


async def test_status_when_not_connected() -> None:
    status = await auth_uc.token_status(FakeTokenStore(), FakeOAuth(), FakeClock())
    assert status["authenticated"] is False
