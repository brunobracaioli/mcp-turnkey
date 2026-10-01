"""Composition roots: wire ports to concrete adapters.

Both roots expose the surface the MCP tools depend on (:class:`ToolHost`):

* :class:`Container` — local stdio, single tenant, file-backed token, manual login.
* :class:`ProdContainer` — remote multi-tenant (Vercel). We are the OAuth 2.1
  Authorization Server and the login is upstream-native: one login identifies the
  tenant (by upstream account) and captures its encrypted token. Per request the
  tenant comes from the validated MCP credential (our signed JWT).
"""

from __future__ import annotations

import webbrowser
from typing import Any, Protocol

import httpx

from .application import auth as auth_uc
from .application.authserver import tenant_id_for_subject
from .application.token_access import TokenAccess, validate_token
from .config import SERVICE_SLUG, UPSTREAM_TIMEOUT_SECONDS, Settings, get_settings
from .domain.errors import AuthError, ConfigError, DomainError
from .domain.models import StoredToken, TenantIdentity
from .domain.ports import Cache, UpstreamClient
from .domain.tokens import apply_token_response
from .infrastructure.authserver_store import AuthServerStore
from .infrastructure.clock import SystemClock
from .infrastructure.crypto_aesgcm import AesGcmCrypto
from .infrastructure.jwt_issuer import JwtIssuer
from .infrastructure.oauth_client import OAuth2Client
from .infrastructure.supabase_client import SupabaseClient
from .infrastructure.supabase_token_store import SupabaseTokenStore
from .infrastructure.token_store_file import FileTokenStore
from .infrastructure.upstash_cache import UpstashCache
from .infrastructure.upstream_client import UpstreamAPIClient
from .observability.logging import get_logger, log_event
from .request_context import RequestScope, get_scope

logger = get_logger(__name__)

_NO_TENANT = "No tenant context; authenticate via MCP OAuth."


class ToolHost(Protocol):
    """What the MCP tools need from a composition root."""

    @property
    def api(self) -> UpstreamClient: ...

    async def auth_login(self) -> dict[str, Any]: ...

    async def auth_submit_callback(self, callback: str) -> dict[str, Any]: ...

    async def auth_status(self) -> dict[str, Any]: ...

    async def auth_refresh(self) -> dict[str, Any]: ...


class Container:
    """Local, single-tenant composition root (stdio)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._clock = SystemClock()
        self._store = FileTokenStore()
        self._oauth: OAuth2Client | None = None
        self._api: UpstreamAPIClient | None = None
        # Two-step manual login: *_login stashes this; *_submit_callback consumes it.
        self._pending: auth_uc.PendingLogin | None = None

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def oauth(self) -> OAuth2Client:
        if self._oauth is None:
            self._oauth = OAuth2Client(self._settings)
        return self._oauth

    @property
    def api(self) -> UpstreamClient:
        if self._api is None:
            tokens = TokenAccess(self._store, self.oauth, self._clock)
            self._api = UpstreamAPIClient(self._settings.api_base, tokens, self._clock)
        return self._api

    async def auth_login(self) -> dict[str, Any]:
        self._pending = auth_uc.start_login(self.oauth, self._settings.local_redirect_uri)
        try:
            webbrowser.open(self._pending.authorize_url)
        except Exception:  # headless/WSL: the URL is returned anyway
            logger.debug("browser_open_failed")
        return {
            "status": "awaiting_authorization",
            "authorize_url": self._pending.authorize_url,
            "detail": (
                "1) Open authorize_url and approve. 2) The browser is redirected to "
                f"{self._settings.local_redirect_uri} — the page may fail to load, that is "
                f"fine. 3) Copy that FULL URL and call {SERVICE_SLUG}_submit_callback."
            ),
        }

    async def auth_submit_callback(self, callback: str) -> dict[str, Any]:
        if self._pending is None:
            raise ConfigError(f"No login in progress. Run {SERVICE_SLUG}_login first.")
        token = await auth_uc.complete_login(
            self._store, self.oauth, self._clock, pending=self._pending, callback=callback
        )
        self._pending = None
        return {"success": True, "account": token.account_label, "scopes": token.scopes}

    async def auth_status(self) -> dict[str, Any]:
        return await auth_uc.token_status(self._store, self.oauth, self._clock)

    async def auth_refresh(self) -> dict[str, Any]:
        token = await validate_token(self._store, self.oauth, self._clock)
        return {"success": True, "access_expires_at": token.access_expires_at}

    async def aclose(self) -> None:
        for closeable in (self._api, self._oauth):
            if closeable is not None:
                await closeable.aclose()


class ProdContainer:
    """Remote, multi-tenant composition root (Vercel serverless)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._clock = SystemClock()
        self._crypto: AesGcmCrypto | None = None
        self._supabase: SupabaseClient | None = None
        self._cache: Cache | None = None
        self._issuer: JwtIssuer | None = None
        self._authserver: AuthServerStore | None = None
        self._oauth: OAuth2Client | None = None
        self._upstream_http: httpx.AsyncClient | None = None

    # ── shared singletons (lazy: a cold start builds only what it uses) ────────

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def clock(self) -> SystemClock:
        return self._clock

    @property
    def crypto(self) -> AesGcmCrypto:
        if self._crypto is None:
            if not self._settings.token_encryption_key:
                raise ConfigError("TOKEN_ENCRYPTION_KEY is not configured.")
            self._crypto = AesGcmCrypto(self._settings.token_encryption_key)
        return self._crypto

    @property
    def supabase(self) -> SupabaseClient:
        if self._supabase is None:
            self._supabase = SupabaseClient(
                self._settings.supabase_url or "", self._settings.supabase_secret_key or ""
            )
        return self._supabase

    @property
    def cache(self) -> Cache:
        if self._cache is None:
            self._cache = UpstashCache(
                self._settings.upstash_redis_rest_url or "",
                self._settings.upstash_redis_rest_token or "",
            )
        return self._cache

    def cache_or_none(self) -> Cache | None:
        """The cache when configured — for best-effort paths (rate limits, memo)."""
        if self._cache is not None:
            return self._cache
        if self._settings.upstash_redis_rest_url and self._settings.upstash_redis_rest_token:
            return self.cache
        return None

    @property
    def jwt_issuer(self) -> JwtIssuer:
        if self._issuer is None:
            key = self._settings.mcp_jwt_private_key
            issuer, resource = self._settings.as_issuer, self._settings.as_resource
            if not key:
                raise ConfigError("MCP_JWT_PRIVATE_KEY is not configured.")
            if not issuer or not resource:
                raise ConfigError("PUBLIC_BASE_URL is not configured.")
            self._issuer = JwtIssuer(key, issuer=issuer, audience=resource)
        return self._issuer

    @property
    def authserver(self) -> AuthServerStore:
        if self._authserver is None:
            self._authserver = AuthServerStore(self.supabase, self.cache)
        return self._authserver

    @property
    def oauth(self) -> OAuth2Client:
        if self._oauth is None:
            self._oauth = OAuth2Client(self._settings)
        return self._oauth

    def _upstream_client(self) -> httpx.AsyncClient:
        if self._upstream_http is None:
            self._upstream_http = httpx.AsyncClient(
                base_url=self._settings.api_base, timeout=UPSTREAM_TIMEOUT_SECONDS
            )
        return self._upstream_http

    # ── per-tenant wiring ──────────────────────────────────────────────────────

    def token_store_for(self, tenant_id: str) -> SupabaseTokenStore:
        return SupabaseTokenStore(tenant_id, self.supabase, self.crypto, cache=self.cache_or_none())

    def build_request_scope(self, tenant_id: str) -> RequestScope:
        """A tenant-bound upstream client. No I/O: the token is read on first use."""
        tokens = TokenAccess(self.token_store_for(tenant_id), self.oauth, self._clock)
        api = UpstreamAPIClient(
            self._settings.api_base, tokens, self._clock, http=self._upstream_client()
        )
        return RequestScope(tenant_id=tenant_id, api=api)

    async def verify_token(self, bearer: str) -> TenantIdentity:
        """Resolve the tenant behind a data-plane bearer (our ES256 JWT, verified locally)."""
        return self.jwt_issuer.verify(bearer)

    async def tenant_is_active(self, tenant_id: str) -> bool:
        row = await self.supabase.get_tenant_row(tenant_id)
        return row is not None and row.get("status") == "active"

    # ── upstream login legs ────────────────────────────────────────────────────

    async def _exchange_and_identify(self, code: str) -> StoredToken:
        """Exchange an upstream code and identify the account. Persists nothing."""
        redirect_uri = self._settings.upstream_redirect_uri
        if not redirect_uri:
            raise ConfigError("No upstream redirect URI configured (PUBLIC_BASE_URL).")
        response = await self.oauth.exchange_code(code, redirect_uri)
        now = self._clock.now()
        token = apply_token_response(StoredToken(obtained_at=int(now)), response, now)
        if not token.access_token:
            raise AuthError("The upstream returned no access token.")
        identity = await self.oauth.identify(token.access_token)
        return token.model_copy(
            update={"subject": identity.subject, "account_label": identity.label}
        )

    async def capture_login(self, code: str) -> str:
        """Login leg: store the encrypted token; return the tenant id."""
        token = await self._exchange_and_identify(code)
        tenant_id = await self._resolve_login_tenant(_require_subject(token))
        await self.token_store_for(tenant_id).save(token)
        return tenant_id

    async def _resolve_login_tenant(self, subject: str) -> str:
        """The tenant a fresh login belongs to: the uuid5 of the upstream account.

        A tenant an operator suspended or revoked (``tenants.status``) cannot log in
        again; a brand-new account has no row yet and is created on save.
        """
        tenant_id = tenant_id_for_subject(subject)
        row = await self.supabase.get_tenant_row(tenant_id)
        if row is not None and row.get("status") != "active":
            log_event(logger, 30, "login_refused_inactive_tenant", tenant_id=tenant_id)
            raise AuthError("This account is not active on this server.")
        return tenant_id

    # ── surface the tools depend on ────────────────────────────────────────────

    def _scope(self) -> RequestScope:
        scope = get_scope()
        if scope is None:
            raise AuthError(_NO_TENANT)
        return scope

    @property
    def api(self) -> UpstreamClient:
        return self._scope().api

    async def auth_login(self) -> dict[str, Any]:
        stored = await self.token_store_for(self._scope().tenant_id).get()
        if stored is not None:
            return {"connected": True, "account": stored.account_label}
        return {
            "connected": False,
            "detail": "No upstream account connected. Reconnect this MCP server in your "
            "client to run the login.",
        }

    async def auth_submit_callback(self, callback: str) -> dict[str, Any]:
        return {
            "success": False,
            "detail": "In hosted mode the login runs during your client's OAuth connection; "
            "there is no callback to submit.",
        }

    async def auth_status(self) -> dict[str, Any]:
        store = self.token_store_for(self._scope().tenant_id)
        return await auth_uc.token_status(store, self.oauth, self._clock)

    async def auth_refresh(self) -> dict[str, Any]:
        store = self.token_store_for(self._scope().tenant_id)
        token = await validate_token(store, self.oauth, self._clock)
        return {"success": True, "access_expires_at": token.access_expires_at}

    # ── cron ────────────────────────────────────────────────────────────────────

    async def validate_all_tokens(self) -> dict[str, int]:
        """Refresh what is refreshable and prove every stored authorization works."""
        tenants = await self.supabase.list_token_tenants()
        valid = failed = 0
        for tenant_id in tenants:
            try:
                await validate_token(self.token_store_for(tenant_id), self.oauth, self._clock)
                valid += 1
            except DomainError:
                log_event(logger, 30, "token_validation_failed", tenant_id=tenant_id)
                failed += 1
        return {"checked": len(tenants), "valid": valid, "failed": failed}

    async def aclose(self) -> None:
        for closeable in (self._upstream_http, self._oauth, self._supabase):
            if closeable is not None:
                await closeable.aclose()
        if isinstance(self._cache, UpstashCache):
            await self._cache.aclose()


def _require_subject(token: StoredToken) -> str:
    """The upstream account id; refuse a login whose account could not be identified."""
    if not token.subject:
        raise AuthError("Could not determine the upstream account for this login.")
    return token.subject
