"""Storage for our OAuth 2.1 Authorization Server.

- Registered clients (DCR) and issued refresh tokens persist in Supabase.
- Pending consents, login requests and authorization codes are ephemeral and live
  in the cache with a TTL; each is single-use (popped on consumption).
- Refresh tokens are stored only as a SHA-256 hash and rotate on every use.

Every cache key carries the service slug: several MCP servers may share one Upstash,
and a code minted by another one must never be consumable here.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from ..config import SERVICE_SLUG
from ..domain.ports import Cache
from ..domain.tokens import hash_token
from .supabase_client import SupabaseClient

_AUTH_REQUEST_PREFIX = f"{SERVICE_SLUG}:authreq:"
_AUTH_CODE_PREFIX = f"{SERVICE_SLUG}:authcode:"
_CONSENT_PREFIX = f"{SERVICE_SLUG}:consent:"
# Every client is public (PKCE): this server never issues client secrets.
_PUBLIC_CLIENT_AUTH_METHOD = "none"


class AuthServerStore:
    def __init__(self, supabase: SupabaseClient, cache: Cache) -> None:
        self._db = supabase
        self._cache = cache

    # ── clients (DCR) ──────────────────────────────────────────────────────────

    async def register_client(
        self,
        *,
        redirect_uris: list[str],
        client_name: str | None,
        grant_types: list[str],
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "client_id": str(uuid.uuid4()),
            "client_name": client_name,
            "redirect_uris": redirect_uris,
            "grant_types": grant_types,
            "token_endpoint_auth_method": _PUBLIC_CLIENT_AUTH_METHOD,
        }
        await self._db.insert_client(row)
        return row

    async def get_client(self, client_id: str) -> dict[str, Any] | None:
        return await self._db.get_client_row(client_id)

    # ── ephemeral, single-use entries ──────────────────────────────────────────

    async def put_consent(self, consent_id: str, data: dict[str, Any], *, ttl_seconds: int) -> None:
        await self._put(_CONSENT_PREFIX + consent_id, data, ttl_seconds)

    async def pop_consent(self, consent_id: str) -> dict[str, Any] | None:
        return await self._pop(_CONSENT_PREFIX + consent_id)

    async def put_auth_request(self, state: str, data: dict[str, Any], *, ttl_seconds: int) -> None:
        await self._put(_AUTH_REQUEST_PREFIX + state, data, ttl_seconds)

    async def pop_auth_request(self, state: str) -> dict[str, Any] | None:
        return await self._pop(_AUTH_REQUEST_PREFIX + state)

    async def put_auth_code(self, code: str, data: dict[str, Any], *, ttl_seconds: int) -> None:
        await self._put(_AUTH_CODE_PREFIX + code, data, ttl_seconds)

    async def pop_auth_code(self, code: str) -> dict[str, Any] | None:
        return await self._pop(_AUTH_CODE_PREFIX + code)

    # ── refresh tokens — persisted (hashed), rotated on use ────────────────────

    async def save_refresh(
        self, token: str, *, tenant_id: str, client_id: str | None, scope: str, expires_at: int
    ) -> None:
        await self._db.insert_refresh(
            {
                "token_hash": hash_token(token),
                "tenant_id": tenant_id,
                "client_id": client_id,
                "scope": scope,
                "expires_at": expires_at,
            }
        )

    async def consume_refresh(self, token: str) -> dict[str, Any] | None:
        """Return the refresh row and delete it (rotation), or ``None``."""
        return await self._db.take_refresh_row(hash_token(token))

    # ── helpers ────────────────────────────────────────────────────────────────

    async def _put(self, key: str, data: dict[str, Any], ttl_seconds: int) -> None:
        await self._cache.set(key, json.dumps(data), ttl_seconds=ttl_seconds)

    async def _pop(self, key: str) -> dict[str, Any] | None:
        raw = await self._cache.get(key)
        if raw is None:
            return None
        await self._cache.delete(key)  # single-use
        try:
            parsed = json.loads(raw)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
