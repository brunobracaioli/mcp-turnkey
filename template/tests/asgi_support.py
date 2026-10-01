"""Wires the module-level production app to in-memory fakes for HTTP tests."""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from conftest import PUBLIC_BASE_URL, encryption_key_b64, jwt_key_b64, make_settings
from fakes import FakeCache, FakeClock, FakeOAuth, FakeSupabase
from mcp_bootstrap import asgi
from mcp_bootstrap.infrastructure.authserver_store import AuthServerStore

CLIENT_REDIRECT = "https://claude.ai/api/mcp/auth_callback"
# What a browser sends when it posts the consent form served by this server.
SAME_ORIGIN = {"Origin": PUBLIC_BASE_URL, "Sec-Fetch-Site": "same-origin"}
_CONSENT_ID = re.compile(r'name="consent_id" value="([^"]+)"')


@dataclass
class Env:
    db: FakeSupabase
    cache: FakeCache
    oauth: FakeOAuth
    clock: FakeClock


def install(monkeypatch: Any, **settings_overrides: Any) -> Env:
    settings = make_settings(
        UPSTASH_REDIS_REST_URL="https://cache.upstash.test",
        UPSTASH_REDIS_REST_TOKEN="fake-token",
        SUPABASE_URL="https://db.supabase.test",
        SUPABASE_SECRET_KEY="service-key",
        TOKEN_ENCRYPTION_KEY=encryption_key_b64(),
        MCP_JWT_PRIVATE_KEY=jwt_key_b64(),
        CRON_SECRET="cron-secret-value",
        **settings_overrides,
    )
    env = Env(db=FakeSupabase(), cache=FakeCache(), oauth=FakeOAuth(), clock=FakeClock())
    prod = asgi._prod
    monkeypatch.setattr(prod, "_settings", settings)
    monkeypatch.setattr(prod, "_supabase", env.db)
    monkeypatch.setattr(prod, "_cache", env.cache)
    monkeypatch.setattr(prod, "_oauth", env.oauth)
    monkeypatch.setattr(prod, "_clock", env.clock)
    monkeypatch.setattr(prod, "_crypto", None)  # rebuilt from the test key
    monkeypatch.setattr(prod, "_issuer", None)
    monkeypatch.setattr(prod, "_authserver", AuthServerStore(env.db, env.cache))  # type: ignore[arg-type]
    # Wall-clock start: PyJWT validates `exp` against time.time().
    env.clock.current = time.time()
    return env


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=asgi.app), base_url=PUBLIC_BASE_URL)


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def query_of(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


async def register(c: httpx.AsyncClient) -> str:
    resp = await c.post("/register", json={"redirect_uris": [CLIENT_REDIRECT]})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["client_id"])


async def authorize(
    c: httpx.AsyncClient, client_id: str, challenge: str, state: str = "client-state"
) -> httpx.Response:
    """GET /authorize as an MCP client's browser would."""
    return await c.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": CLIENT_REDIRECT,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        },
    )


def consent_id_of(page: httpx.Response) -> str:
    match = _CONSENT_ID.search(page.text)
    assert match, page.text
    return match.group(1)


async def decide(
    c: httpx.AsyncClient,
    consent_id: str,
    decision: str = "approve",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """POST the consent form (same-origin headers unless overridden)."""
    return await c.post(
        "/authorize/consent",
        data={"consent_id": consent_id, "decision": decision},
        headers=SAME_ORIGIN if headers is None else headers,
    )


async def approve(
    c: httpx.AsyncClient, client_id: str, challenge: str, state: str = "client-state"
) -> str:
    """Consent screen -> Allow; returns the upstream ``state`` of the login leg."""
    page = await authorize(c, client_id, challenge, state)
    assert page.status_code == 200, page.text
    resp = await decide(c, consent_id_of(page))
    assert resp.status_code == 303, resp.text
    return query_of(resp.headers["location"])["state"]


async def login(c: httpx.AsyncClient, env: Env, subject: str = "acct1") -> dict[str, Any]:
    """Full MCP OAuth dance through the consent screen; returns the /token body."""
    client_id = await register(c)
    verifier, challenge = pkce()
    upstream_state = await approve(c, client_id, challenge)
    env.oauth.codes["upstream-code"] = subject
    resp = await c.get("/oauth/callback", params={"code": "upstream-code", "state": upstream_state})
    assert resp.status_code == 302, resp.text
    back = query_of(resp.headers["location"])
    assert back["state"] == "client-state"
    resp = await c.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": back["code"],
            "redirect_uri": CLIENT_REDIRECT,
            "code_verifier": verifier,
            "client_id": client_id,
        },
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body
