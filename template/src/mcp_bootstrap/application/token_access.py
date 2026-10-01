"""Upstream access-token supply and validation (use cases over domain ports)."""

from __future__ import annotations

from ..domain.errors import AuthError, ConfigError
from ..domain.models import StoredToken
from ..domain.ports import Clock, OAuthProvider, TokenStore
from ..domain.tokens import apply_token_response, usable_access_token

_NOT_CONNECTED = "No upstream account is connected. Reconnect this MCP server to authorize."
_EXPIRED = (
    "The upstream authorization expired and cannot be renewed automatically. "
    "Reconnect this MCP server to authorize again."
)


class TokenAccess:
    """:class:`~mcp_bootstrap.domain.ports.AccessTokenSource` over a tenant's store.

    Returns the stored access token while it is usable, otherwise mints a new one
    with the refresh token and persists the result (so a rotated refresh token is
    never lost). Without a refresh token the tenant must reconnect.
    """

    def __init__(self, store: TokenStore, oauth: OAuthProvider, clock: Clock) -> None:
        self._store = store
        self._oauth = oauth
        self._clock = clock

    async def access_token(self, *, force_refresh: bool = False) -> str:
        token = await self._store.get()
        if token is None:
            raise ConfigError(_NOT_CONNECTED)
        now = self._clock.now()
        if not force_refresh:
            usable = usable_access_token(token, now)
            if usable:
                return usable
        refreshed = await refresh_token(self._store, self._oauth, self._clock, token)
        if not refreshed.access_token:
            raise AuthError(_EXPIRED)
        return refreshed.access_token


async def refresh_token(
    store: TokenStore, oauth: OAuthProvider, clock: Clock, token: StoredToken
) -> StoredToken:
    """Exchange the refresh token and persist the merged result."""
    if not token.refresh_token:
        raise AuthError(_EXPIRED)
    response = await oauth.refresh(token.refresh_token)
    updated = apply_token_response(token, response, clock.now())
    if not updated.access_token:
        raise AuthError(_EXPIRED)
    await store.save(updated)
    return updated


async def validate_token(store: TokenStore, oauth: OAuthProvider, clock: Clock) -> StoredToken:
    """Prove the stored authorization still works (cron sweep and status tools).

    Refreshes when the access token is unusable, then asks the upstream who it
    belongs to — the identity call is what catches a revoked long-lived token.
    """
    token = await store.get()
    if token is None:
        raise ConfigError(_NOT_CONNECTED)
    access = usable_access_token(token, clock.now())
    if access is None:
        token = await refresh_token(store, oauth, clock, token)
        access = token.access_token or ""
    await oauth.identify(access)
    return token
