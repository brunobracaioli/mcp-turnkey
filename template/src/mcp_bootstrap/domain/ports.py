"""Ports (interfaces) the application layer depends on.

Concrete adapters live in ``infrastructure``; tests use in-memory fakes. Every port
is async except the clock's ``now`` and the cipher, which never do I/O.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .models import StoredToken, UpstreamIdentity


@runtime_checkable
class Clock(Protocol):
    """Injectable time source so expiry and backoff stay deterministic in tests."""

    def now(self) -> float:
        """Current Unix epoch seconds."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Asynchronously sleep for ``seconds``."""
        ...


@runtime_checkable
class Crypto(Protocol):
    """Symmetric authenticated encryption for upstream tokens at rest."""

    def encrypt(self, plaintext: str) -> tuple[bytes, bytes]:
        """Return ``(ciphertext, nonce)``; a fresh random nonce per call."""
        ...

    def decrypt(self, ciphertext: bytes, nonce: bytes) -> str:
        """Recover the plaintext, or raise on tampering/wrong key."""
        ...


@runtime_checkable
class Cache(Protocol):
    """Key/value store with TTL. Callers namespace every key by service slug."""

    async def get(self, key: str) -> str | None:
        """The value, or ``None`` on miss/expiry."""
        ...

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        """Store ``value`` under ``key`` with an explicit TTL."""
        ...

    async def delete(self, key: str) -> None:
        """Remove ``key`` if present."""
        ...

    async def incr(self, key: str, *, ttl_seconds: int) -> int:
        """Atomically increment ``key``; the TTL is armed on the first increment."""
        ...


@runtime_checkable
class TokenStore(Protocol):
    """Persistence of ONE tenant's upstream token (tenant bound at construction)."""

    async def get(self) -> StoredToken | None:
        """The stored token, or ``None``."""
        ...

    async def save(self, token: StoredToken) -> None:
        """Persist ``token``, replacing any previous value."""
        ...

    async def clear(self) -> None:
        """Remove the stored token."""
        ...


@runtime_checkable
class OAuthProvider(Protocol):
    """The upstream's OAuth 2.0 endpoints (the login provider)."""

    def authorize_url(
        self, redirect_uri: str, state: str, *, code_challenge: str | None = None
    ) -> str:
        """The consent URL the user's browser is sent to."""
        ...

    async def exchange_code(
        self, code: str, redirect_uri: str, *, code_verifier: str | None = None
    ) -> dict[str, Any]:
        """Exchange an authorization code for a token response."""
        ...

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        """Exchange a refresh token for a fresh token response."""
        ...

    async def identify(self, access_token: str) -> UpstreamIdentity:
        """Resolve the account behind ``access_token``."""
        ...


@runtime_checkable
class AccessTokenSource(Protocol):
    """Hands the upstream client a usable access token for the current tenant."""

    async def access_token(self, *, force_refresh: bool = False) -> str:
        """A valid access token; ``force_refresh`` after the upstream rejected one."""
        ...


@runtime_checkable
class UpstreamClient(Protocol):
    """Minimal async surface of the upstream REST API used by use cases.

    ``path`` is relative to the API base (``items/abc``); adapters own auth,
    retries and error mapping.
    """

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Authenticated GET."""
        ...

    async def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Authenticated POST."""
        ...

    async def patch(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Authenticated PATCH."""
        ...

    async def delete(self, path: str) -> dict[str, Any]:
        """Authenticated DELETE."""
        ...
