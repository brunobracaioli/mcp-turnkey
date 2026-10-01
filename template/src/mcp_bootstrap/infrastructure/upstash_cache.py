"""Upstash Redis cache over the REST API.

Stateless serverless functions cannot share in-process state, so the cache and the
ephemeral OAuth state live in Upstash. Callers namespace every key with the service
slug: several MCP servers may share one Upstash instance, and an un-namespaced key
minted by another one could be consumed here.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..domain.errors import BackendError, ConfigError

_TIMEOUT_SECONDS = 10.0


class UpstashCache:
    """Concrete :class:`~mcp_bootstrap.domain.ports.Cache` adapter."""

    def __init__(self, url: str, token: str, *, http: httpx.AsyncClient | None = None) -> None:
        if not url or not token:
            raise ConfigError("Upstash Redis is not configured (URL/token missing).")
        self._url = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._http = http or httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get(self, key: str) -> str | None:
        result = await self._command(["GET", key])
        return result if isinstance(result, str) else None

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        await self._command(["SET", key, value, "EX", str(ttl_seconds)])

    async def delete(self, key: str) -> None:
        await self._command(["DEL", key])

    async def incr(self, key: str, *, ttl_seconds: int) -> int:
        """Fixed-window counter; the first increment of a window arms the TTL."""
        result = await self._command(["INCR", key])
        count = int(result) if result is not None else 0
        if count == 1:
            await self._command(["EXPIRE", key, str(ttl_seconds)])
        return count

    async def _command(self, command: list[str]) -> Any:
        try:
            response = await self._http.post(self._url, json=command, headers=self._headers)
        except httpx.TransportError as exc:
            raise BackendError("Could not reach the cache.") from exc
        if not response.is_success:
            raise BackendError(f"Cache request failed ({response.status_code}).")
        body = response.json()
        if isinstance(body, dict) and "error" in body:
            raise BackendError("Cache command error.")
        return body.get("result") if isinstance(body, dict) else None
