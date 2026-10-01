"""Pure token rules (no I/O): upstream access-token lifecycle and opaque-token hashing."""

from __future__ import annotations

import hashlib
from typing import Any

from .models import StoredToken

# Re-mint an access token this many seconds before its real expiry.
ACCESS_SKEW_SECONDS = 60


def usable_access_token(token: StoredToken, now: float) -> str | None:
    """The stored access token if it can still be sent, else ``None``."""
    access = token.access_token
    if not access:
        return None
    expires_at = token.access_expires_at
    if expires_at is None:
        return access
    return access if expires_at - now > ACCESS_SKEW_SECONDS else None


def apply_token_response(token: StoredToken, response: dict[str, Any], now: float) -> StoredToken:
    """Merge an OAuth token response into ``token``.

    A rotated ``refresh_token`` replaces the old one (providers like TikTok
    invalidate the previous value); a response without one keeps the current.
    """
    access = response.get("access_token")
    expires_in = response.get("expires_in")
    scope = response.get("scope")
    update: dict[str, Any] = {
        "access_token": str(access) if access else None,
        "access_expires_at": int(now) + int(expires_in) if expires_in else None,
    }
    if response.get("refresh_token"):
        update["refresh_token"] = str(response["refresh_token"])
    if isinstance(scope, str) and scope:
        update["scopes"] = scope.replace(",", " ").split()
    return token.model_copy(update=update)


def hash_token(token: str) -> str:
    """SHA-256 hex digest. Opaque tokens we issue are only ever stored as this hash."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
