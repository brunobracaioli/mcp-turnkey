"""In-memory fakes of the ports and adapters (no network)."""

from __future__ import annotations

import copy
from typing import Any

from mcp_bootstrap.domain.errors import AuthError, BackendError
from mcp_bootstrap.domain.models import StoredToken, UpstreamIdentity


class FakeClock:
    def __init__(self, now: float = 1_700_000_000.0) -> None:
        self.current = now
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.current

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.current += seconds


class FakeCache:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        self.data[key] = value
        self.ttls[key] = ttl_seconds

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)

    async def incr(self, key: str, *, ttl_seconds: int) -> int:
        value = int(self.data.get(key, "0")) + 1
        self.data[key] = str(value)
        self.ttls.setdefault(key, ttl_seconds)
        return value


class FailingCache:
    async def get(self, key: str) -> str | None:
        raise BackendError("cache down")

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        raise BackendError("cache down")

    async def delete(self, key: str) -> None:
        raise BackendError("cache down")

    async def incr(self, key: str, *, ttl_seconds: int) -> int:
        raise BackendError("cache down")


class FakeTokenStore:
    def __init__(self, token: StoredToken | None = None) -> None:
        self.token = token
        self.saves = 0

    async def get(self) -> StoredToken | None:
        return self.token

    async def save(self, token: StoredToken) -> None:
        self.token = token
        self.saves += 1

    async def clear(self) -> None:
        self.token = None


class FakeOAuth:
    """Upstream login provider. ``codes`` maps an authorization code to an account.

    Tokens encode the account as ``at-<subject>-<n>``: subjects must not contain "-".
    """

    def __init__(self) -> None:
        self.codes: dict[str, str] = {}
        self.labels: dict[str, str] = {}
        self.refresh_calls: list[str] = []
        self.exchange_calls: list[dict[str, Any]] = []
        self.fail_refresh = False
        self.rotate_refresh = False
        self._serial = 0

    def authorize_url(
        self, redirect_uri: str, state: str, *, code_challenge: str | None = None
    ) -> str:
        extra = f"&code_challenge={code_challenge}" if code_challenge else ""
        return (
            f"https://auth.upstream.test/authorize?state={state}&redirect_uri={redirect_uri}{extra}"
        )

    def _mint(self, subject: str) -> dict[str, Any]:
        self._serial += 1
        return {
            "access_token": f"at-{subject}-{self._serial}",
            "refresh_token": f"rt-{subject}-{self._serial}",
            "expires_in": 3600,
            "scope": "items.read items.write",
        }

    async def exchange_code(
        self, code: str, redirect_uri: str, *, code_verifier: str | None = None
    ) -> dict[str, Any]:
        self.exchange_calls.append(
            {"code": code, "redirect_uri": redirect_uri, "code_verifier": code_verifier}
        )
        subject = self.codes.get(code)
        if subject is None:
            raise AuthError("bad code")
        return self._mint(subject)

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        self.refresh_calls.append(refresh_token)
        if self.fail_refresh:
            raise AuthError("revoked")
        subject = refresh_token.split("-")[1]
        minted = self._mint(subject)
        if not self.rotate_refresh:
            minted.pop("refresh_token")
        return minted

    async def identify(self, access_token: str) -> UpstreamIdentity:
        if not access_token.startswith("at-"):
            raise AuthError("unknown token")
        subject = access_token.split("-")[1]
        return UpstreamIdentity(subject=subject, label=self.labels.get(subject))


class FakeUpstream:
    """Records calls; answers from ``responses`` keyed by ``(method, path)``."""

    def __init__(self, responses: dict[tuple[str, str], dict[str, Any]] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, str, Any]] = []

    async def _answer(self, method: str, path: str, payload: Any) -> dict[str, Any]:
        self.calls.append((method, path, payload))
        return self.responses.get((method, path), {})

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._answer("GET", path, params)

    async def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._answer("POST", path, body)

    async def patch(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._answer("PATCH", path, body)

    async def delete(self, path: str) -> dict[str, Any]:
        return await self._answer("DELETE", path, None)


class FakeSupabase:
    """Duck-typed SupabaseClient over dicts, enforcing the schema's key constraints."""

    def __init__(self) -> None:
        self.tenants: dict[str, dict[str, Any]] = {}
        self.tokens: dict[str, dict[str, Any]] = {}
        self.clients: dict[str, dict[str, Any]] = {}
        self.refresh: dict[str, dict[str, Any]] = {}

    async def aclose(self) -> None:
        return None

    def _check_subject_unique(self, tenant_id: str, subject: str | None) -> None:
        if subject is None:
            return
        for other_id, row in self.tenants.items():
            if other_id != tenant_id and row.get("upstream_subject") == subject:
                raise BackendError("Token store request failed (409).")

    # tenants
    async def ensure_tenant(self, tenant_id: str, *, upstream_subject: str | None) -> None:
        self._check_subject_unique(tenant_id, upstream_subject)
        row = self.tenants.setdefault(tenant_id, {"id": tenant_id, "status": "active"})
        if upstream_subject:
            row["upstream_subject"] = upstream_subject

    async def get_tenant_row(self, tenant_id: str) -> dict[str, Any] | None:
        row = self.tenants.get(tenant_id)
        return copy.deepcopy(row) if row else None

    # upstream_tokens
    async def get_token_row(self, tenant_id: str) -> dict[str, Any] | None:
        row = self.tokens.get(tenant_id)
        return copy.deepcopy(row) if row else None

    async def upsert_token_row(self, row: dict[str, Any]) -> None:
        if row["tenant_id"] not in self.tenants:
            raise BackendError("Token store request failed (409).")  # FK
        self.tokens[row["tenant_id"]] = copy.deepcopy(row)

    async def delete_token_row(self, tenant_id: str) -> None:
        self.tokens.pop(tenant_id, None)

    async def list_token_tenants(self) -> list[str]:
        return sorted(self.tokens)

    # oauth_clients
    async def insert_client(self, row: dict[str, Any]) -> None:
        self.clients[row["client_id"]] = copy.deepcopy(row)

    async def get_client_row(self, client_id: str) -> dict[str, Any] | None:
        row = self.clients.get(client_id)
        return copy.deepcopy(row) if row else None

    # oauth_refresh_tokens
    async def insert_refresh(self, row: dict[str, Any]) -> None:
        self.refresh[row["token_hash"]] = copy.deepcopy(row)

    async def take_refresh_row(self, token_hash: str) -> dict[str, Any] | None:
        return self.refresh.pop(token_hash, None)


class FailingSupabase:
    """Every call fails like a Supabase outage."""

    def __getattr__(self, name: str) -> Any:
        async def _fail(*_args: Any, **_kwargs: Any) -> Any:
            raise BackendError("Token store request failed (503).")

        return _fail
