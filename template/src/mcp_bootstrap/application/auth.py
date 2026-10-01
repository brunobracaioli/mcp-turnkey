"""Local (stdio) login use cases: a two-step manual OAuth flow.

``start_login`` builds the consent URL with a CSRF ``state`` and PKCE; the user
approves in a browser and copies the URL the provider redirected to (the page itself
may fail to load — only the URL matters); ``complete_login`` validates it, exchanges
the code and persists the token. No callback server or tunnel is needed: the
redirect URI only has to be registered on the upstream OAuth app.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ..domain.errors import AuthError, ConfigError
from ..domain.models import StoredToken
from ..domain.ports import Clock, OAuthProvider, TokenStore
from ..domain.tokens import apply_token_response
from .authserver import new_opaque_token, pkce_pair
from .token_access import validate_token


@dataclass(frozen=True, slots=True)
class PendingLogin:
    """What must be remembered between ``start_login`` and ``complete_login``."""

    authorize_url: str
    state: str
    code_verifier: str
    redirect_uri: str


def start_login(oauth: OAuthProvider, redirect_uri: str) -> PendingLogin:
    """Begin a login: the consent URL plus the state to remember."""
    state = new_opaque_token()
    verifier, challenge = pkce_pair()
    url = oauth.authorize_url(redirect_uri, state, code_challenge=challenge)
    return PendingLogin(
        authorize_url=url, state=state, code_verifier=verifier, redirect_uri=redirect_uri
    )


def parse_callback(value: str) -> tuple[str, str | None]:
    """Accept a full redirect URL or a bare code; return ``(code, state | None)``."""
    value = value.strip()
    if "code=" not in value and "error=" not in value:
        return value, None
    query = parse_qs(urlsplit(value).query or value)
    if query.get("error"):
        raise AuthError("Authorization was not granted.")
    codes, states = query.get("code"), query.get("state")
    return (codes[0] if codes else ""), (states[0] if states else None)


async def complete_login(
    store: TokenStore,
    oauth: OAuthProvider,
    clock: Clock,
    *,
    pending: PendingLogin,
    callback: str,
) -> StoredToken:
    """Exchange the pasted callback for a token, identify the account and persist it."""
    code, state = parse_callback(callback)
    if not code:
        raise AuthError("No authorization code found in the pasted value.")
    if state is None or not hmac.compare_digest(state, pending.state):
        raise AuthError("Paste the FULL redirect URL (it carries the state); or start again.")
    response = await oauth.exchange_code(
        code, pending.redirect_uri, code_verifier=pending.code_verifier
    )
    now = clock.now()
    token = apply_token_response(StoredToken(obtained_at=int(now)), response, now)
    if not token.access_token:
        raise AuthError("The upstream returned no access token.")
    identity = await oauth.identify(token.access_token)
    token = token.model_copy(update={"subject": identity.subject, "account_label": identity.label})
    await store.save(token)
    return token


async def token_status(store: TokenStore, oauth: OAuthProvider, clock: Clock) -> dict[str, Any]:
    """Whether the stored authorization works, without raising for the common cases."""
    try:
        token = await validate_token(store, oauth, clock)
    except ConfigError:
        return {"authenticated": False, "detail": "No upstream account is connected."}
    except AuthError:
        return {"authenticated": False, "detail": "The stored authorization is invalid or revoked."}
    return {
        "authenticated": True,
        "account": token.account_label,
        "scopes": token.scopes,
        "access_expires_at": token.access_expires_at,
    }
