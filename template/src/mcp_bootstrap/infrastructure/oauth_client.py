"""Generic OAuth 2.0 client for the upstream login provider.

Covers the variations seen across real providers through the constants in
``config``: scope separator, extra authorize params, token-endpoint client auth and
the userinfo fields that carry the account id and label. These endpoints are the
upstream's, distinct from our own Authorization Server. Failures are auth problems
by definition and the raw response body is never surfaced (it can echo secrets).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from ..config import (
    OAUTH_AUTHORIZE_URL,
    OAUTH_EXTRA_AUTHORIZE_PARAMS,
    OAUTH_LABEL_FIELD,
    OAUTH_SCOPE_SEPARATOR,
    OAUTH_SCOPES,
    OAUTH_SUBJECT_FIELD,
    OAUTH_TOKEN_AUTH_METHOD,
    OAUTH_TOKEN_URL,
    OAUTH_USERINFO_URL,
    Settings,
)
from ..domain.errors import AuthError, ConfigError
from ..domain.models import UpstreamIdentity

_TIMEOUT_SECONDS = 30.0


class OAuth2Client:
    """Concrete :class:`~mcp_bootstrap.domain.ports.OAuthProvider` adapter."""

    def __init__(self, settings: Settings, *, http: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._http = http or httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)

    async def aclose(self) -> None:
        await self._http.aclose()

    def _client_pair(self) -> tuple[str, str]:
        client_id = self._settings.upstream_client_id
        client_secret = self._settings.upstream_client_secret
        if not client_id or not client_secret:
            raise ConfigError("UPSTREAM_CLIENT_ID / UPSTREAM_CLIENT_SECRET are not configured.")
        return client_id, client_secret

    def authorize_url(
        self, redirect_uri: str, state: str, *, code_challenge: str | None = None
    ) -> str:
        client_id, _ = self._client_pair()
        params: dict[str, str] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": OAUTH_SCOPE_SEPARATOR.join(OAUTH_SCOPES),
            "state": state,
            **OAUTH_EXTRA_AUTHORIZE_PARAMS,
        }
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        return f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(
        self, code: str, redirect_uri: str, *, code_verifier: str | None = None
    ) -> dict[str, Any]:
        data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
        if code_verifier:
            data["code_verifier"] = code_verifier
        return await self._post_token(data)

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        return await self._post_token(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )

    async def identify(self, access_token: str) -> UpstreamIdentity:
        try:
            response = await self._http.get(
                OAUTH_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
            )
        except httpx.TransportError as exc:
            raise AuthError("Could not reach the upstream to identify the account.") from exc
        if not response.is_success:
            raise AuthError("Could not resolve the upstream account for this token.")
        body = response.json()
        subject = body.get(OAUTH_SUBJECT_FIELD) if isinstance(body, dict) else None
        if not subject:
            raise AuthError("The upstream did not return an account id.")
        label = body.get(OAUTH_LABEL_FIELD)
        return UpstreamIdentity(subject=str(subject), label=str(label) if label else None)

    async def _post_token(self, data: dict[str, str]) -> dict[str, Any]:
        client_id, client_secret = self._client_pair()
        try:
            if OAUTH_TOKEN_AUTH_METHOD == "client_secret_basic":  # noqa: S105 - a method name
                response = await self._http.post(
                    OAUTH_TOKEN_URL, data=data, auth=httpx.BasicAuth(client_id, client_secret)
                )
            else:
                body = {**data, "client_id": client_id, "client_secret": client_secret}
                response = await self._http.post(OAUTH_TOKEN_URL, data=body)
        except httpx.TransportError as exc:
            raise AuthError("Could not reach the upstream token endpoint.") from exc
        if not response.is_success:
            raise AuthError(
                "The upstream rejected the token request; the authorization may be "
                "revoked or expired. Reconnect to authorize again."
            )
        body = response.json()
        if not isinstance(body, dict) or not body.get("access_token"):
            raise AuthError("The upstream token response had no access token.")
        return body
