"""Per-client consent before the upstream login (spec: oauth-client-consent.md)."""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx
import pytest

from asgi_support import (
    CLIENT_REDIRECT,
    Env,
    approve,
    authorize,
    client,
    consent_id_of,
    decide,
    install,
    pkce,
    query_of,
)
from conftest import PUBLIC_BASE_URL
from mcp_bootstrap.application.consent import CSRF_COOKIE, STATE_COOKIE

_HOST = urlsplit(PUBLIC_BASE_URL).hostname or ""
CROSS_SITE = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Env:
    return install(monkeypatch)


async def _register(c: httpx.AsyncClient, client_name: str | None = "Claude") -> str:
    body: dict[str, object] = {"redirect_uris": [CLIENT_REDIRECT]}
    if client_name is not None:
        body["client_name"] = client_name
    resp = await c.post("/register", json=body)
    assert resp.status_code == 201, resp.text
    return str(resp.json()["client_id"])


def _pending_logins(env: Env) -> list[str]:
    return [key for key in env.cache.data if ":authreq:" in key]


def _set_cookie(resp: httpx.Response, name: str) -> str:
    matches = [h for h in resp.headers.get_list("set-cookie") if h.startswith(f"{name}=")]
    assert len(matches) == 1, resp.headers.get_list("set-cookie")
    return matches[0]


class TestConsentScreen:
    async def test_shows_client_destination_and_scopes_without_starting_a_login(
        self, env: Env
    ) -> None:
        async with client() as c:
            page = await authorize(c, await _register(c), pkce()[1])
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        for shown in ("Claude", "https://claude.ai", CLIENT_REDIRECT, "items.read", "items.write"):
            assert shown in page.text
        assert _pending_logins(env) == []

    async def test_csrf_cookie_is_host_only_secure_and_hidden_from_scripts(self, env: Env) -> None:
        async with client() as c:
            page = await authorize(c, await _register(c), pkce()[1])
        cookie = _set_cookie(page, CSRF_COOKIE).lower()
        for attribute in ("secure", "httponly", "samesite=lax", "path=/", "max-age=600"):
            assert attribute in cookie
        assert "domain=" not in cookie

    async def test_page_cannot_be_framed_and_posts_only_to_known_origins(self, env: Env) -> None:
        async with client() as c:
            page = await authorize(c, await _register(c), pkce()[1])
        csp = page.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in csp
        assert "form-action 'self' https://auth.example.com https://claude.ai" in csp
        assert "script-src" not in csp and "default-src 'none'" in csp
        assert page.headers["x-frame-options"] == "DENY"

    async def test_client_name_is_escaped(self, env: Env) -> None:
        async with client() as c:
            page = await authorize(c, await _register(c, "<script>alert(1)</script>"), pkce()[1])
        assert "<script>" not in page.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text

    async def test_unnamed_client_is_labelled(self, env: Env) -> None:
        async with client() as c:
            page = await authorize(c, await _register(c, None), pkce()[1])
        assert "Unnamed client" in page.text


class TestDecision:
    async def test_approve_starts_the_login_bound_to_this_browser(self, env: Env) -> None:
        async with client() as c:
            page = await authorize(c, await _register(c), pkce()[1])
            resp = await decide(c, consent_id_of(page))
        assert resp.status_code == 303
        assert resp.headers["location"].startswith("https://auth.upstream.test/authorize?")
        state = query_of(resp.headers["location"])["state"]
        assert _set_cookie(resp, STATE_COOKIE).startswith(f"{STATE_COOKIE}={state};")
        assert "max-age=0" in _set_cookie(resp, CSRF_COOKIE).lower()
        assert len(_pending_logins(env)) == 1

    async def test_deny_returns_access_denied_to_the_client(self, env: Env) -> None:
        async with client() as c:
            page = await authorize(c, await _register(c), pkce()[1], state="xyz")
            resp = await decide(c, consent_id_of(page), "deny")
        assert resp.status_code == 303
        assert resp.headers["location"].startswith(CLIENT_REDIRECT + "?")
        assert query_of(resp.headers["location"]) == {"error": "access_denied", "state": "xyz"}
        assert _pending_logins(env) == []

    async def test_consent_is_single_use(self, env: Env) -> None:
        async with client() as c:
            page = await authorize(c, await _register(c), pkce()[1])
            consent_id = consent_id_of(page)
            assert (await decide(c, consent_id)).status_code == 303
            c.cookies.set(CSRF_COOKIE, "replayed", domain=_HOST)
            assert (await decide(c, consent_id)).status_code == 400

    @pytest.mark.parametrize(
        "data",
        [{"consent_id": "x", "decision": "maybe"}, {"decision": "approve"}, {"consent_id": ""}],
    )
    async def test_malformed_form_is_400(self, env: Env, data: dict[str, str]) -> None:
        async with client() as c:
            resp = await c.post("/authorize/consent", data=data)
        assert resp.status_code == 400

    async def test_oversized_body_is_400(self, env: Env) -> None:
        async with client() as c:
            resp = await c.post(
                "/authorize/consent", data={"consent_id": "x" * 5000, "decision": "approve"}
            )
        assert resp.status_code == 400


class TestForgedSubmission:
    async def test_submission_without_the_csrf_cookie_is_403(self, env: Env) -> None:
        async with client() as c:
            page = await authorize(c, await _register(c), pkce()[1])
            c.cookies.clear()
            resp = await decide(c, consent_id_of(page))
        assert resp.status_code == 403
        assert _pending_logins(env) == []

    async def test_attacker_consent_id_posted_from_the_victim_browser_is_403(
        self, env: Env
    ) -> None:
        async with client() as attacker, client() as victim:
            client_id = await _register(attacker, "Claude")
            attacker_page = await authorize(attacker, client_id, pkce()[1])
            await authorize(victim, client_id, pkce()[1])  # the victim holds a cookie too
            resp = await decide(victim, consent_id_of(attacker_page))
        assert resp.status_code == 403
        assert _pending_logins(env) == []

    @pytest.mark.parametrize(
        "headers",
        [CROSS_SITE, {"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}],
    )
    async def test_cross_site_submission_is_403(self, env: Env, headers: dict[str, str]) -> None:
        async with client() as c:
            page = await authorize(c, await _register(c), pkce()[1])
            resp = await decide(c, consent_id_of(page), headers=headers)
        assert resp.status_code == 403
        assert _pending_logins(env) == []


class TestStateCookieAtTheCallback:
    async def test_callback_without_the_state_cookie_keeps_the_pending_login(
        self, env: Env
    ) -> None:
        async with client() as c:
            state = await approve(c, await _register(c), pkce()[1])
            env.oauth.codes["up"] = "acct1"
            c.cookies.clear()
            resp = await c.get("/oauth/callback", params={"code": "up", "state": state})
        assert resp.status_code == 400
        assert len(_pending_logins(env)) == 1

    async def test_callback_with_another_state_cookie_is_400(self, env: Env) -> None:
        async with client() as c:
            state = await approve(c, await _register(c), pkce()[1])
            env.oauth.codes["up"] = "acct1"
            c.cookies.clear()  # a browser replaces a same-name cookie for the host
            c.cookies.set(STATE_COOKIE, "someone-elses-state", domain=_HOST)
            resp = await c.get("/oauth/callback", params={"code": "up", "state": state})
        assert resp.status_code == 400
        assert len(_pending_logins(env)) == 1

    async def test_successful_callback_expires_the_state_cookie(self, env: Env) -> None:
        async with client() as c:
            state = await approve(c, await _register(c), pkce()[1])
            env.oauth.codes["up"] = "acct1"
            resp = await c.get("/oauth/callback", params={"code": "up", "state": state})
        assert resp.status_code == 302
        assert "max-age=0" in _set_cookie(resp, STATE_COOKIE).lower()
