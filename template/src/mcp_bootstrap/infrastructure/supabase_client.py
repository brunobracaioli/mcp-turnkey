"""Supabase (PostgREST) data access over httpx.

We use the **service role** key, which bypasses RLS: encryption at rest is the real
protection for credentials, RLS default-deny is defense in depth. The key and the
PostgREST error bodies (which can echo row data) are never logged or returned.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..domain.errors import BackendError, ConfigError

_TIMEOUT_SECONDS = 15.0
_MINIMAL = {"Prefer": "return=minimal"}
_UPSERT = {"Prefer": "resolution=merge-duplicates,return=minimal"}


class SupabaseClient:
    """Thin async PostgREST client for the tables in ``supabase/migrations``."""

    def __init__(
        self, url: str, service_key: str, *, http: httpx.AsyncClient | None = None
    ) -> None:
        if not url or not service_key:
            raise ConfigError("Supabase is not configured (URL/service key missing).")
        self._base = url.rstrip("/") + "/rest/v1"
        self._headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }
        self._http = http or httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)

    async def aclose(self) -> None:
        await self._http.aclose()

    # ── tenants ───────────────────────────────────────────────────────────────

    async def ensure_tenant(self, tenant_id: str, *, upstream_subject: str | None) -> None:
        """Upsert a tenant row so the token FK is satisfied.

        Only ``id``/``upstream_subject`` are sent, so ``merge-duplicates`` never
        touches ``status``: a tenant an operator suspended stays suspended.
        """
        row: dict[str, Any] = {"id": tenant_id}
        if upstream_subject:
            row["upstream_subject"] = upstream_subject
        await self._request("POST", "/tenants", json=[row], headers=_UPSERT)

    async def get_tenant_row(self, tenant_id: str) -> dict[str, Any] | None:
        rows = await self._request(
            "GET", "/tenants", params={"id": f"eq.{tenant_id}", "select": "*", "limit": "1"}
        )
        return rows[0] if rows else None

    # ── upstream_tokens (ciphertext only) ───────────────────────────────────────

    async def get_token_row(self, tenant_id: str) -> dict[str, Any] | None:
        rows = await self._request(
            "GET",
            "/upstream_tokens",
            params={"tenant_id": f"eq.{tenant_id}", "select": "*", "limit": "1"},
        )
        return rows[0] if rows else None

    async def upsert_token_row(self, row: dict[str, Any]) -> None:
        await self._request("POST", "/upstream_tokens", json=[row], headers=_UPSERT)

    async def delete_token_row(self, tenant_id: str) -> None:
        await self._request(
            "DELETE",
            "/upstream_tokens",
            params={"tenant_id": f"eq.{tenant_id}"},
            headers=_MINIMAL,
        )

    async def list_token_tenants(self) -> list[str]:
        """Tenant ids holding an upstream token (cron sweep)."""
        rows = await self._request(
            "GET", "/upstream_tokens", params={"select": "tenant_id", "order": "tenant_id"}
        )
        return [str(row["tenant_id"]) for row in rows if row.get("tenant_id")]

    # ── oauth_clients (DCR) ────────────────────────────────────────────────────

    async def insert_client(self, row: dict[str, Any]) -> None:
        await self._request("POST", "/oauth_clients", json=[row], headers=_MINIMAL)

    async def get_client_row(self, client_id: str) -> dict[str, Any] | None:
        rows = await self._request(
            "GET",
            "/oauth_clients",
            params={"client_id": f"eq.{client_id}", "select": "*", "limit": "1"},
        )
        return rows[0] if rows else None

    # ── oauth_refresh_tokens (stored only as a hash) ───────────────────────────

    async def insert_refresh(self, row: dict[str, Any]) -> None:
        await self._request("POST", "/oauth_refresh_tokens", json=[row], headers=_MINIMAL)

    async def take_refresh_row(self, token_hash: str) -> dict[str, Any] | None:
        """Delete the row and return it (single-use rotation in one round-trip)."""
        rows = await self._request(
            "DELETE",
            "/oauth_refresh_tokens",
            params={"token_hash": f"eq.{token_hash}"},
            headers={"Prefer": "return=representation"},
        )
        return rows[0] if rows else None

    # ── request engine ────────────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        merged = {**self._headers, **(headers or {})}
        try:
            response = await self._http.request(
                method, self._base + path, params=params, json=json, headers=merged
            )
        except httpx.TransportError as exc:
            raise BackendError("Could not reach the token store.") from exc
        if not response.is_success:
            # Never echo the PostgREST body — it can include row data.
            raise BackendError(f"Token store request failed ({response.status_code}).")
        if response.status_code == httpx.codes.NO_CONTENT or not response.content:
            return []
        body = response.json()
        return body if isinstance(body, list) else [body]
