"""Per-tenant upstream token store: Supabase + AES-256-GCM (+ optional cache).

The tenant id is bound at construction. The database only ever holds ciphertext:
the secret fields (access token, refresh token, expiry) are serialized together and
encrypted as one blob; scopes, subject and label stay in clear for operations.

The optional cache short-circuits the Supabase round-trip. Only the encrypted row is
cached — never plaintext — and it is invalidated on every ``save``/``clear`` so a
refresh or revoke is never masked by a stale entry.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from ..config import SERVICE_SLUG
from ..domain.models import StoredToken
from ..domain.ports import Cache, Crypto
from ..observability.logging import get_logger
from .supabase_client import SupabaseClient

logger = get_logger(__name__)

_CACHE_TTL_SECONDS = 300
_ENCRYPTED_FIELDS = ("access_token", "refresh_token", "access_expires_at")


class SupabaseTokenStore:
    """Concrete :class:`~mcp_bootstrap.domain.ports.TokenStore` adapter."""

    def __init__(
        self,
        tenant_id: str,
        client: SupabaseClient,
        crypto: Crypto,
        *,
        cache: Cache | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._client = client
        self._crypto = crypto
        self._cache = cache
        self._cache_key = f"{SERVICE_SLUG}:tokrow:{tenant_id}"

    async def get(self) -> StoredToken | None:
        row = await self._get_row()
        if not row:
            return None
        plaintext = self._crypto.decrypt(
            base64.b64decode(row["ciphertext"]), base64.b64decode(row["nonce"])
        )
        sealed: dict[str, Any] = json.loads(plaintext)
        return StoredToken(
            access_token=sealed.get("access_token"),
            refresh_token=sealed.get("refresh_token"),
            access_expires_at=sealed.get("access_expires_at"),
            scopes=row.get("scopes") or [],
            obtained_at=row.get("obtained_at"),
            subject=row.get("subject"),
            account_label=row.get("account_label"),
        )

    async def save(self, token: StoredToken) -> None:
        sealed = {field: getattr(token, field) for field in _ENCRYPTED_FIELDS}
        ciphertext, nonce = self._crypto.encrypt(json.dumps(sealed))
        # FK: the tenant row must exist before a token row references it.
        await self._client.ensure_tenant(self._tenant_id, upstream_subject=token.subject)
        await self._client.upsert_token_row(
            {
                "tenant_id": self._tenant_id,
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "scopes": token.scopes,
                "subject": token.subject,
                "account_label": token.account_label,
                "obtained_at": token.obtained_at,
            }
        )
        await self._invalidate()

    async def clear(self) -> None:
        await self._client.delete_token_row(self._tenant_id)
        await self._invalidate()

    # ── caching (best-effort: a cache failure never fails a request) ──────────

    async def _get_row(self) -> dict[str, Any] | None:
        cached = await self._cache_get()
        if cached is not None:
            return cached
        row = await self._client.get_token_row(self._tenant_id)
        if row is not None:
            await self._cache_set(row)
        return row

    async def _cache_get(self) -> dict[str, Any] | None:
        if self._cache is None:
            return None
        try:
            raw = await self._cache.get(self._cache_key)
            parsed = json.loads(raw) if raw else None
        except Exception:
            logger.debug("token_cache_get_failed")
            return None
        return parsed if isinstance(parsed, dict) else None

    async def _cache_set(self, row: dict[str, Any]) -> None:
        if self._cache is None:
            return
        try:
            await self._cache.set(self._cache_key, json.dumps(row), ttl_seconds=_CACHE_TTL_SECONDS)
        except Exception:
            logger.debug("token_cache_set_failed")

    async def _invalidate(self) -> None:
        if self._cache is None:
            return
        try:
            await self._cache.delete(self._cache_key)
        except Exception:
            logger.debug("token_cache_delete_failed")
