"""In-memory token store (tests and short-lived local use)."""

from __future__ import annotations

from ..domain.models import StoredToken


class MemoryTokenStore:
    """Concrete :class:`~mcp_bootstrap.domain.ports.TokenStore` adapter."""

    def __init__(self, token: StoredToken | None = None) -> None:
        self._token = token

    async def get(self) -> StoredToken | None:
        return self._token

    async def save(self, token: StoredToken) -> None:
        self._token = token

    async def clear(self) -> None:
        self._token = None
