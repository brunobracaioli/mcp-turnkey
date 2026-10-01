"""Pure-ASGI middlewares of the production app.

Order (outermost first, see ``asgi.py``): correlation id -> security headers ->
CORS -> tenant auth -> app. Pure ASGI (not ``BaseHTTPMiddleware``) so the MCP
transport's responses are never buffered.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, MutableMapping
from typing import Protocol

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .domain.errors import AuthError, BackendError, ConfigError
from .domain.models import TenantIdentity
from .observability.logging import get_logger, request_id_var
from .request_context import RequestScope, current_scope

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
# An inbound id is trusted only if it is short and boring (log-injection guard).
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def content_security_policy(form_action: str = "'self'") -> str:
    """The server's CSP; only ``form-action`` varies (the consent page widens it)."""
    return f"default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action {form_action}"


# JSON-first server: nothing is ever framed, scripted or embedded. The few HTML pages
# (consent, login errors, connect confirmation) use no scripts and no inline styles.
SECURITY_HEADERS: dict[str, str] = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": content_security_policy(),
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cache-Control": "no-store",
}

# The streamable-HTTP transport runs stateless + JSON responses, so the server never
# pushes anything: a GET would open an SSE stream that idles until the function's
# maxDuration (billed). The spec lets a server without SSE answer 405 instead.
MCP_ALLOWED_METHODS = frozenset({"POST"})


class CorrelationIdMiddleware:
    """Assign every HTTP request an id, expose it in logs and echo it back."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        inbound = headers.get("x-request-id") or headers.get("x-vercel-id") or ""
        request_id = inbound if _SAFE_REQUEST_ID.match(inbound) else uuid.uuid4().hex

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        token = request_id_var.set(request_id)
        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)


class SecurityHeadersMiddleware:
    """Add the security headers to every response that does not set its own."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    if name not in headers:
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)


class TenantResolver(Protocol):
    """What the tenant middleware needs from the composition root."""

    async def verify_token(self, bearer: str) -> TenantIdentity: ...

    def build_request_scope(self, tenant_id: str) -> RequestScope: ...


def bearer_token(authorization: str | None) -> str | None:
    """The token of an ``Authorization: Bearer`` header, or ``None``."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


class TenantAuthMiddleware:
    """Authenticate the MCP transport path and bind the tenant scope for the request."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        resolver: TenantResolver,
        mcp_path: str,
        prm_url: Callable[[], str],
    ) -> None:
        self.app = app
        self._resolver = resolver
        self._mcp_path = mcp_path
        self._prm_url = prm_url

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith(self._mcp_path):
            await self.app(scope, receive, send)
            return
        if scope["method"] not in MCP_ALLOWED_METHODS:
            # Before auth: there is nothing to protect in a 405, and it spares every
            # client reconnect a token verification.
            await _json(
                scope,
                receive,
                send,
                405,
                "method_not_allowed",
                headers={"Allow": ", ".join(sorted(MCP_ALLOWED_METHODS))},
            )
            return
        challenge = {"WWW-Authenticate": f'Bearer resource_metadata="{self._prm_url()}"'}
        bearer = bearer_token(Headers(scope=scope).get("authorization"))
        if not bearer:
            await _json(scope, receive, send, 401, "missing_token", headers=challenge)
            return
        try:
            identity = await self._resolver.verify_token(bearer)
        except AuthError:
            await _json(scope, receive, send, 401, "invalid_token", headers=challenge)
            return
        except (BackendError, ConfigError):
            # The store/cache/config behind verification failed — not the credential.
            # Never 401 here: it would tell a legitimate caller to discard a good key.
            logger.exception("token_verification_unavailable")
            await _json(
                scope, receive, send, 503, "backend_unavailable", headers={"Retry-After": "30"}
            )
            return
        token = current_scope.set(self._resolver.build_request_scope(identity.tenant_id))
        try:
            await self.app(scope, receive, send)
        finally:
            current_scope.reset(token)


async def _json(
    scope: Scope,
    receive: Receive,
    send: Send,
    status: int,
    error: str,
    *,
    headers: MutableMapping[str, str] | None = None,
) -> None:
    response = JSONResponse({"error": error}, status_code=status, headers=dict(headers or {}))
    await response(scope, receive, send)
