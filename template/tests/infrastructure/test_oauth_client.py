"""Generic upstream OAuth 2.0 client."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from conftest import make_settings
from mcp_bootstrap.config import OAUTH_TOKEN_URL, OAUTH_USERINFO_URL
from mcp_bootstrap.domain.errors import AuthError, ConfigError
from mcp_bootstrap.infrastructure.oauth_client import OAuth2Client


def test_authorize_url_carries_client_state_and_pkce() -> None:
    url = OAuth2Client(make_settings()).authorize_url(
        "https://mcp.example.test/oauth/callback", "st8", code_challenge="ch"
    )
    query = parse_qs(urlsplit(url).query)
    assert query["client_id"] == ["client-123"]
    assert query["state"] == ["st8"]
    assert query["code_challenge"] == ["ch"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["response_type"] == ["code"]


def test_missing_client_credentials_are_a_config_error() -> None:
    with pytest.raises(ConfigError):
        OAuth2Client(make_settings(UPSTREAM_CLIENT_ID="")).authorize_url("https://x/cb", "s")


@respx.mock
async def test_exchange_posts_the_client_credentials() -> None:
    route = respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "at", "expires_in": 60})
    )
    body = await OAuth2Client(make_settings()).exchange_code("c", "https://x/cb", code_verifier="v")
    assert body["access_token"] == "at"
    form = parse_qs(route.calls.last.request.content.decode())
    assert form["client_secret"] == ["secret-456"]
    assert form["code_verifier"] == ["v"]


@respx.mock
async def test_rejection_never_echoes_the_response_body() -> None:
    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant", "leak": "SECRET-ECHO"})
    )
    with pytest.raises(AuthError) as caught:
        await OAuth2Client(make_settings()).refresh("rt")
    assert "SECRET-ECHO" not in caught.value.message


@respx.mock
async def test_identify_reads_the_configured_fields() -> None:
    respx.get(OAUTH_USERINFO_URL).mock(
        return_value=httpx.Response(200, json={"sub": "acct-9", "email": "o@example.test"})
    )
    identity = await OAuth2Client(make_settings()).identify("at")
    assert identity.subject == "acct-9" and identity.label == "o@example.test"


@respx.mock
async def test_identify_without_subject_fails() -> None:
    respx.get(OAUTH_USERINFO_URL).mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(AuthError):
        await OAuth2Client(make_settings()).identify("at")
