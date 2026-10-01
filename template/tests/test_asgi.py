"""Production HTTP surface: hardening baseline, OAuth 2.1 AS, transport auth, cron."""

from __future__ import annotations

import httpx
import pytest

from asgi_support import (
    CLIENT_REDIRECT,
    Env,
    approve,
    client,
    install,
    login,
    pkce,
    query_of,
    register,
)
from conftest import PUBLIC_BASE_URL
from fakes import FailingSupabase
from mcp_bootstrap import asgi
from mcp_bootstrap.application import rate_limit
from mcp_bootstrap.application.authserver import tenant_id_for_subject
from mcp_bootstrap.infrastructure.authserver_store import AuthServerStore
from mcp_bootstrap.middleware import SECURITY_HEADERS


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Env:
    return install(monkeypatch)


class TestHardeningBaseline:
    async def test_security_headers_on_every_response(self, env: Env) -> None:
        async with client() as c:
            for resp in (await c.get("/api/health"), await c.post("/api/mcp")):
                for name, value in SECURITY_HEADERS.items():
                    assert resp.headers[name] == value

    async def test_request_id_generated_echoed_or_replaced(self, env: Env) -> None:
        async with client() as c:
            generated = (await c.get("/api/health")).headers["X-Request-ID"]
            assert len(generated) == 32
            echoed = await c.get("/api/health", headers={"X-Request-ID": "trace-123"})
            assert echoed.headers["X-Request-ID"] == "trace-123"
            unsafe = await c.get("/api/health", headers={"X-Request-ID": "bad\nvalue"})
            assert unsafe.headers["X-Request-ID"] != "bad\nvalue"

    @pytest.mark.parametrize("method", ["GET", "DELETE", "PUT"])
    async def test_non_post_on_transport_is_405_before_auth(self, env: Env, method: str) -> None:
        async with client() as c:
            resp = await c.request(method, "/api/mcp")
        assert resp.status_code == 405
        assert resp.headers["Allow"] == "POST"

    async def test_missing_token_is_401_with_resource_metadata(self, env: Env) -> None:
        async with client() as c:
            resp = await c.post("/api/mcp", json={})
        assert resp.status_code == 401
        prm = f"{PUBLIC_BASE_URL}/.well-known/oauth-protected-resource"
        assert resp.headers["WWW-Authenticate"] == f'Bearer resource_metadata="{prm}"'

    async def test_invalid_token_is_401(self, env: Env) -> None:
        async with client() as c:
            resp = await c.post("/api/mcp", headers={"Authorization": "Bearer nope"}, json={})
        assert resp.status_code == 401

    async def test_misconfigured_verifier_is_503_not_401(
        self, env: Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A server-side failure must never tell a client to discard a good credential.
        monkeypatch.setattr(asgi._prod.settings, "mcp_jwt_private_key", None)
        monkeypatch.setattr(asgi._prod, "_issuer", None)
        async with client() as c:
            resp = await c.post("/api/mcp", headers={"Authorization": "Bearer x.y.z"}, json={})
        assert resp.status_code == 503
        assert resp.headers["Retry-After"]


class TestDiscovery:
    async def test_protected_resource_metadata(self, env: Env) -> None:
        async with client() as c:
            for path in (
                "/.well-known/oauth-protected-resource",
                "/.well-known/oauth-protected-resource/api/mcp",
            ):
                body = (await c.get(path)).json()
                assert body["resource"] == f"{PUBLIC_BASE_URL}/api/mcp"
                assert body["authorization_servers"] == [PUBLIC_BASE_URL]

    async def test_authorization_server_metadata_requires_pkce_s256(self, env: Env) -> None:
        async with client() as c:
            body = (await c.get("/.well-known/oauth-authorization-server")).json()
        assert body["code_challenge_methods_supported"] == ["S256"]
        assert body["token_endpoint_auth_methods_supported"] == ["none"]

    async def test_jwks(self, env: Env) -> None:
        async with client() as c:
            assert (await c.get("/.well-known/jwks.json")).json()["keys"][0]["alg"] == "ES256"


class TestDynamicClientRegistration:
    async def test_registers_a_public_client(self, env: Env) -> None:
        async with client() as c:
            resp = await c.post(
                "/register",
                json={
                    "redirect_uris": [CLIENT_REDIRECT],
                    "token_endpoint_auth_method": "client_secret_basic",
                },
            )
        assert resp.status_code == 201
        assert resp.json()["token_endpoint_auth_method"] == "none"

    @pytest.mark.parametrize(
        "payload",
        [
            {"redirect_uris": ["http://evil.example/cb"]},
            {"redirect_uris": [f"https://a.test/{i}" for i in range(11)]},
            # The redirect origin is shown on the consent screen and put in its CSP.
            {"redirect_uris": ["https://a;b.example/cb"]},
            {"redirect_uris": ["https://a b.example/cb"]},
            {"redirect_uris": ["https://a.example:99999/cb"]},
            {},
        ],
    )
    async def test_rejects_unsafe_registrations(self, env: Env, payload: dict[str, object]) -> None:
        async with client() as c:
            assert (await c.post("/register", json=payload)).status_code == 400

    async def test_store_outage_is_503(self, env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            asgi._prod, "_authserver", AuthServerStore(FailingSupabase(), env.cache)
        )  # type: ignore[arg-type]
        async with client() as c:
            resp = await c.post("/register", json={"redirect_uris": [CLIENT_REDIRECT]})
        assert resp.status_code == 503


class TestAuthorizationFlow:
    async def test_full_flow_issues_a_jwt_bound_to_the_tenant(self, env: Env) -> None:
        async with client() as c:
            tokens = await login(c, env)
        identity = asgi._prod.jwt_issuer.verify(tokens["access_token"])
        assert identity.tenant_id == tenant_id_for_subject("acct1")
        assert identity.tenant_id in env.db.tokens  # upstream token captured (encrypted)

    async def test_unknown_client_or_redirect_never_redirects(self, env: Env) -> None:
        async with client() as c:
            client_id = await register(c)
            resp = await c.get(
                "/authorize",
                params={
                    "client_id": client_id,
                    "redirect_uri": "https://evil.example/cb",
                    "response_type": "code",
                    "code_challenge": "x",
                },
            )
        assert resp.status_code == 400

    async def test_missing_pkce_is_rejected(self, env: Env) -> None:
        async with client() as c:
            client_id = await register(c)
            resp = await c.get(
                "/authorize",
                params={
                    "client_id": client_id,
                    "redirect_uri": CLIENT_REDIRECT,
                    "response_type": "code",
                },
            )
        assert resp.status_code == 302
        assert query_of(resp.headers["location"])["error"] == "invalid_request"

    async def _code(self, c: httpx.AsyncClient, env: Env) -> tuple[str, str, str]:
        client_id = await register(c)
        verifier, challenge = pkce()
        state = await approve(c, client_id, challenge)
        env.oauth.codes["up"] = "acct1"
        resp = await c.get("/oauth/callback", params={"code": "up", "state": state})
        return query_of(resp.headers["location"])["code"], verifier, client_id

    async def test_wrong_verifier_is_invalid_grant(self, env: Env) -> None:
        async with client() as c:
            code, _, client_id = await self._code(c, env)
            resp = await c.post(
                "/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": CLIENT_REDIRECT,
                    "code_verifier": "wrong",
                    "client_id": client_id,
                },
            )
        assert resp.json() == {"error": "invalid_grant"}

    async def test_authorization_code_is_single_use(self, env: Env) -> None:
        async with client() as c:
            code, verifier, client_id = await self._code(c, env)
            form = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": CLIENT_REDIRECT,
                "code_verifier": verifier,
                "client_id": client_id,
            }
            assert (await c.post("/token", data=form)).status_code == 200
            assert (await c.post("/token", data=form)).status_code == 400

    async def test_upstream_callback_with_unknown_state_is_rejected(self, env: Env) -> None:
        async with client() as c:
            resp = await c.get("/oauth/callback", params={"code": "x", "state": "forged"})
        assert resp.status_code == 400

    async def test_refresh_rotates_and_the_old_token_dies(self, env: Env) -> None:
        async with client() as c:
            first = await login(c, env)
            form = {"grant_type": "refresh_token", "refresh_token": first["refresh_token"]}
            second = await c.post("/token", data=form)
            assert second.status_code == 200
            assert second.json()["refresh_token"] != first["refresh_token"]
            assert (await c.post("/token", data=form)).status_code == 400

    async def test_suspended_tenant_cannot_refresh(self, env: Env) -> None:
        async with client() as c:
            tokens = await login(c, env)
            for row in env.db.tenants.values():
                row["status"] = "suspended"
            resp = await c.post(
                "/token",
                data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]},
            )
        assert resp.status_code == 400

    async def test_suspended_tenant_cannot_log_in_again(self, env: Env) -> None:
        async with client() as c:
            await login(c, env)
            env.db.tenants[tenant_id_for_subject("acct1")]["status"] = "suspended"
            client_id = await register(c)
            state = await approve(c, client_id, pkce()[1])
            env.oauth.codes["again"] = "acct1"
            resp = await c.get("/oauth/callback", params={"code": "again", "state": state})
        assert resp.status_code == 400
        assert "location" not in resp.headers

    async def test_unsupported_grant(self, env: Env) -> None:
        async with client() as c:
            resp = await c.post("/token", data={"grant_type": "password"})
        assert resp.json() == {"error": "unsupported_grant_type"}

    async def test_jwt_passes_the_transport_auth(self, env: Env) -> None:
        async with client() as c:
            tokens = await login(c, env)
            resolved = await asgi._prod.verify_token(tokens["access_token"])
        assert resolved.tenant_id in env.db.tenants


class TestRateLimit:
    @pytest.mark.parametrize(
        ("bucket", "method", "path"),
        [
            ("token", "POST", "/token"),
            ("register", "POST", "/register"),
            ("authorize", "GET", "/authorize"),
            ("consent", "POST", "/authorize/consent"),
        ],
    )
    async def test_exhausted_bucket_is_429(
        self, env: Env, bucket: str, method: str, path: str
    ) -> None:
        env.cache.data[rate_limit.ip_key(bucket, "203.0.113.9")] = "1000"
        async with client() as c:
            resp = await c.request(method, path, headers={"x-real-ip": "203.0.113.9"})
        assert resp.status_code == 429
        assert resp.headers["Retry-After"] == "60"

    async def test_other_ips_are_unaffected(self, env: Env) -> None:
        env.cache.data[rate_limit.ip_key("token", "203.0.113.9")] = "1000"
        async with client() as c:
            resp = await c.post(
                "/token", data={"grant_type": "x"}, headers={"x-real-ip": "198.51.100.1"}
            )
        assert resp.status_code == 400


class TestCron:
    async def test_requires_the_cron_secret(self, env: Env) -> None:
        async with client() as c:
            assert (await c.get("/api/cron/validate-tokens")).status_code == 401
            wrong = {"Authorization": "Bearer nope"}
            assert (await c.get("/api/cron/validate-tokens", headers=wrong)).status_code == 401

    async def test_validates_every_stored_token(self, env: Env) -> None:
        async with client() as c:
            await login(c, env)
            resp = await c.get(
                "/api/cron/validate-tokens", headers={"Authorization": "Bearer cron-secret-value"}
            )
        assert resp.json() == {"checked": 1, "valid": 1, "failed": 0}

    async def test_unconfigured_secret_is_503(
        self, env: Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(asgi._prod.settings, "cron_secret", None)
        async with client() as c:
            assert (await c.get("/api/cron/validate-tokens")).status_code == 503
