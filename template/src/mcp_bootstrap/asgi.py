"""Production ASGI app (Vercel, ``@vercel/python``).

This server is the **OAuth 2.1 Authorization Server** for the MCP connection and the
**Resource Server** for the MCP transport. The login is upstream-native: ``/authorize``
shows this server's per-client consent screen, its approval sends the user to the
provider (ADR 0007); ``/oauth/callback`` captures the
encrypted upstream token AND establishes the tenant, then issues our own
authorization code; ``/token`` exchanges it for a signed JWT used on ``/api/mcp``.

Routes: AS metadata + JWKS, DCR (``/register``), ``/authorize`` + its consent POST,
``/oauth/callback``, ``/token``, the MCP transport, PRM, health and the cron. Vercel
detects the module-level ``app`` (re-exported by the root ``app.py``) and runs its
lifespan.
"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from html import escape
from typing import Any
from urllib.parse import urlencode

from mcp.server.transport_security import TransportSecuritySettings
from pydantic import ValidationError as SchemaError
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .application import authserver as asrv
from .application import consent as consent_uc
from .application import rate_limit
from .config import (
    MCP_TRANSPORT_PATH,
    OAUTH_AUTHORIZE_URL,
    OAUTH_CALLBACK_PATH,
    OAUTH_CONSENT_PATH,
    OAUTH_SCOPES,
    SERVICE_DISPLAY_NAME,
    SERVICE_SLUG,
    UPSTREAM_DISPLAY_NAME,
)
from .consent_page import render_consent_page
from .container import ProdContainer
from .domain.errors import AuthError, DomainError
from .middleware import (
    CorrelationIdMiddleware,
    SecurityHeadersMiddleware,
    TenantAuthMiddleware,
    bearer_token,
    content_security_policy,
)
from .observability.logging import configure_logging, get_logger, log_event
from .server import mcp, set_container

PRM_PATH = "/.well-known/oauth-protected-resource"
AS_META_PATH = "/.well-known/oauth-authorization-server"
JWKS_PATH = "/.well-known/jwks.json"
CRON_PATH = "/api/cron/validate-tokens"

_CONSENT_TTL = 600  # consent screen -> its POST
_AUTH_REQUEST_TTL = 600  # login leg at the upstream
_AUTH_CODE_TTL = 300  # our authorization code
_ACCESS_TTL = 8 * 60 * 60  # 8h
_REFRESH_TTL = 30 * 24 * 60 * 60  # 30d
_RATE_WINDOW_SECONDS = 60
_MAX_DCR_BODY_BYTES = 16 * 1024
_MAX_CONSENT_BODY_BYTES = 4 * 1024

# Configure the transport for serverless.
mcp.settings.stateless_http = True
mcp.settings.json_response = True
mcp.settings.streamable_http_path = MCP_TRANSPORT_PATH
# The SDK's DNS-rebinding guard targets localhost servers reached from a browser; a
# remote server behind Vercel and our own OAuth gets 421 Misdirected Request for every
# non-local Host header with it on.
mcp.settings.transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

_prod = ProdContainer()
set_container(_prod)
configure_logging(_prod.settings.log_level)
logger = get_logger(__name__)


# ── helpers ────────────────────────────────────────────────────────────────────


def _base_url() -> str:
    return (_prod.settings.public_base_url or "").rstrip("/")


def _prm_url() -> str:
    return f"{_base_url()}{PRM_PATH}"


def _append_query(url: str, params: dict[str, str]) -> str:
    return url + ("&" if "?" in url else "?") + urlencode(params)


def _page(message: str, status_code: int = 200) -> HTMLResponse:
    title = escape(SERVICE_DISPLAY_NAME)
    body = (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{title}</title>"
        f"</head><body><h1>{title}</h1><p>{escape(message)}</p></body></html>"
    )
    return HTMLResponse(body, status_code=status_code)


def _set_cookie(response: Response, name: str, value: str, max_age: int) -> None:
    """A ``__Host-`` cookie: Secure, host-only, Path=/, invisible to scripts."""
    response.set_cookie(
        name, value, max_age=max_age, path="/", secure=True, httponly=True, samesite="lax"
    )


def _expire_cookie(response: Response, name: str) -> None:
    response.delete_cookie(name, path="/", secure=True, httponly=True, samesite="lax")


def _client_ip(request: Request) -> str:
    """Caller IP as seen by Vercel's edge (``x-real-ip``), else the socket peer."""
    forwarded = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",", 1)[0].strip()
    if first:
        return first
    return request.client.host if request.client else "unknown"


async def _rate_limited(request: Request, bucket: str) -> Response | None:
    """A 429 when this IP exhausted the bucket, else ``None`` (fail-open)."""
    allowed = await rate_limit.allow(
        _prod.cache_or_none(),
        rate_limit.ip_key(bucket, _client_ip(request)),
        limit=_prod.settings.oauth_rate_limit_per_min,
        window_seconds=_RATE_WINDOW_SECONDS,
    )
    if allowed:
        return None
    log_event(logger, 30, "oauth_rate_limited", bucket=bucket)
    return JSONResponse(
        {"error": "rate_limited"},
        status_code=429,
        headers={"Retry-After": str(_RATE_WINDOW_SECONDS)},
    )


# ── discovery / ops ─────────────────────────────────────────────────────────────


async def health(_request: Request) -> Response:
    return JSONResponse({"status": "ok"})


async def protected_resource_metadata(_request: Request) -> Response:
    issuer = _prod.settings.as_issuer
    return JSONResponse(
        {
            "resource": _prod.settings.as_resource,
            "authorization_servers": [issuer] if issuer else [],
            "scopes_supported": [SERVICE_SLUG],
            "bearer_methods_supported": ["header"],
        }
    )


async def authorization_server_metadata(_request: Request) -> Response:
    base = _base_url()
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/authorize",
            "token_endpoint": f"{base}/token",
            "registration_endpoint": f"{base}/register",
            "jwks_uri": f"{base}{JWKS_PATH}",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": [SERVICE_SLUG],
        }
    )


async def jwks(_request: Request) -> Response:
    try:
        return JSONResponse(_prod.jwt_issuer.jwks())
    except DomainError:
        logger.exception("jwks_unavailable")
        return JSONResponse({"error": "server_misconfigured"}, status_code=503)


# ── Dynamic Client Registration (RFC 7591) ──────────────────────────────────────


async def register(request: Request) -> Response:
    if (limited := await _rate_limited(request, "register")) is not None:
        return limited
    raw = await request.body()
    if len(raw) > _MAX_DCR_BODY_BYTES:
        return JSONResponse({"error": "invalid_client_metadata"}, status_code=400)
    try:
        registration = asrv.ClientRegistration.model_validate_json(raw or b"{}")
    except SchemaError:
        return JSONResponse({"error": "invalid_redirect_uri"}, status_code=400)
    client = await _prod.authserver.register_client(
        redirect_uris=registration.redirect_uris,
        client_name=registration.client_name,
        grant_types=list(registration.grant_types),
    )
    log_event(logger, 20, "oauth_client_registered", client_id=client["client_id"])
    return JSONResponse(client, status_code=201)


# ── authorization endpoint + upstream login leg ─────────────────────────────────


async def authorize(request: Request) -> Response:
    if (limited := await _rate_limited(request, "authorize")) is not None:
        return limited
    q = request.query_params
    client_id, redirect_uri = q.get("client_id", ""), q.get("redirect_uri", "")
    client = await _prod.authserver.get_client(client_id) if client_id else None
    if client is None or redirect_uri not in (client.get("redirect_uris") or []):
        # Never redirect to an unverified URI (open-redirect guard).
        return _page("Invalid client or redirect_uri.", 400)
    if q.get("response_type") != "code":
        return RedirectResponse(
            _append_query(redirect_uri, {"error": "unsupported_response_type"}), 302
        )
    challenge = q.get("code_challenge", "")
    if not challenge or q.get("code_challenge_method", "S256") != "S256":
        return RedirectResponse(_append_query(redirect_uri, {"error": "invalid_request"}), 302)
    if not _prod.settings.upstream_redirect_uri:
        return _page("The server is missing its public URL.", 503)

    # Per-client consent BEFORE the provider (ADR 0007): nothing reaches the upstream
    # login, and no login state exists, until this browser approves this client.
    consent_id = asrv.new_opaque_token()
    nonce, binding = consent_uc.new_browser_binding()
    await _prod.authserver.put_consent(
        consent_id,
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "client_state": q.get("state"),
            "scope": SERVICE_SLUG,
            "binding": binding,
        },
        ttl_seconds=_CONSENT_TTL,
    )
    screen = consent_uc.ConsentScreen(
        consent_id=consent_id,
        client_name=consent_uc.display_client_name(client.get("client_name")),
        redirect_uri=redirect_uri,
        redirect_origin=consent_uc.origin_of(redirect_uri),
        scopes=OAUTH_SCOPES,
    )
    response = HTMLResponse(
        render_consent_page(
            screen, service_name=SERVICE_DISPLAY_NAME, upstream_name=UPSTREAM_DISPLAY_NAME
        )
    )
    response.headers["Content-Security-Policy"] = content_security_policy(
        consent_uc.form_action_sources(
            consent_uc.origin_of(OAUTH_AUTHORIZE_URL), screen.redirect_origin
        )
    )
    _set_cookie(response, consent_uc.CSRF_COOKIE, nonce, _CONSENT_TTL)
    log_event(logger, 20, "consent_shown", client_id=client_id)
    return response


async def authorize_consent(request: Request) -> Response:
    """The consent form's POST: approve starts the upstream login, deny ends it."""
    if (limited := await _rate_limited(request, "consent")) is not None:
        return limited
    if not consent_uc.is_same_origin_submission(
        origin=request.headers.get("origin"),
        fetch_site=request.headers.get("sec-fetch-site"),
        issuer=_base_url(),
    ):
        log_event(logger, 30, "consent_rejected", reason="cross_site")
        return _page("This request did not come from this server's consent page.", 403)
    if len(await request.body()) > _MAX_CONSENT_BODY_BYTES:
        return _page("Invalid consent request.", 400)
    form = await request.form()
    consent_id, decision = form.get("consent_id"), form.get("decision")
    if not isinstance(consent_id, str) or not consent_id or decision not in consent_uc.DECISIONS:
        return _page("Invalid consent request.", 400)

    pending = await _prod.authserver.pop_consent(consent_id)  # single-use from here on
    response: Response
    if pending is None:
        log_event(logger, 30, "consent_rejected", reason="expired")
        response = _page(
            "This consent screen expired or was already used. Retry from your app.", 400
        )
    elif not consent_uc.binding_matches(
        request.cookies.get(consent_uc.CSRF_COOKIE), pending.get("binding")
    ):
        log_event(
            logger, 30, "consent_rejected", reason="binding", client_id=pending.get("client_id")
        )
        response = _page(
            "This consent screen was opened in a different browser session. Retry from your app.",
            403,
        )
    elif decision == consent_uc.DECISION_DENY:
        response = _deny(pending)
    else:
        response = await _approve(pending)
    _expire_cookie(response, consent_uc.CSRF_COOKIE)
    return response


def _deny(pending: dict[str, Any]) -> Response:
    params = {"error": "access_denied"}
    if pending.get("client_state"):
        params["state"] = str(pending["client_state"])
    log_event(logger, 20, "consent_denied", client_id=pending.get("client_id"))
    return RedirectResponse(_append_query(str(pending["redirect_uri"]), params), 303)


async def _approve(pending: dict[str, Any]) -> Response:
    upstream_redirect = _prod.settings.upstream_redirect_uri
    if not upstream_redirect:
        return _page("The server is missing its public URL.", 503)
    # The login state exists only after approval, and is bound to this browser.
    login_state = asrv.new_opaque_token()
    await _prod.authserver.put_auth_request(
        login_state,
        {
            key: pending.get(key)
            for key in ("client_id", "redirect_uri", "code_challenge", "client_state", "scope")
        },
        ttl_seconds=_AUTH_REQUEST_TTL,
    )
    response = RedirectResponse(_prod.oauth.authorize_url(upstream_redirect, login_state), 303)
    _set_cookie(response, consent_uc.STATE_COOKIE, login_state, _AUTH_REQUEST_TTL)
    log_event(logger, 20, "consent_approved", client_id=pending.get("client_id"))
    return response


async def oauth_callback(request: Request) -> Response:
    """Upstream redirect target: capture the token, then mint our authorization code.

    The state cookie is single-use: every answer expires it.
    """
    response = await _complete_upstream_login(request)
    _expire_cookie(response, consent_uc.STATE_COOKIE)
    return response


async def _complete_upstream_login(request: Request) -> Response:
    q = request.query_params
    if q.get("error"):
        return _page("Authorization was cancelled or denied.", 400)
    code, state = q.get("code"), q.get("state")
    if not code or not state:
        return _page("Missing code or state.", 400)
    # Checked before the store is touched: a callback from another browser never
    # consumes the pending login of the one that approved it.
    if not consent_uc.state_matches(request.cookies.get(consent_uc.STATE_COOKIE), state):
        log_event(logger, 30, "oauth_state_rejected")
        return _page(
            "This login was started in a different browser session. Retry from your app.", 400
        )
    req = await _prod.authserver.pop_auth_request(state)
    if req is None:
        return _page("The login session expired. Please retry from your client.", 400)
    try:
        tenant_id = await _prod.capture_login(code)
    except DomainError:
        logger.exception("upstream_login_failed")
        return _page("Could not complete the login. Please try again.", 400)

    our_code = asrv.new_opaque_token()
    await _prod.authserver.put_auth_code(
        our_code,
        {
            "tenant_id": tenant_id,
            "client_id": req["client_id"],
            "redirect_uri": req["redirect_uri"],
            "code_challenge": req["code_challenge"],
            "scope": req.get("scope") or SERVICE_SLUG,
        },
        ttl_seconds=_AUTH_CODE_TTL,
    )
    log_event(logger, 20, "mcp_login_completed", tenant_id=tenant_id)
    params = {"code": our_code}
    if req.get("client_state"):
        params["state"] = str(req["client_state"])
    return RedirectResponse(_append_query(str(req["redirect_uri"]), params), 302)


# ── token endpoint ───────────────────────────────────────────────────────────────


async def token(request: Request) -> Response:
    if (limited := await _rate_limited(request, "token")) is not None:
        return limited
    form = await request.form()
    fields = {key: str(value) for key, value in form.items() if isinstance(value, str)}
    grant = fields.get("grant_type")
    if grant == "authorization_code":
        return await _grant_authorization_code(fields)
    if grant == "refresh_token":
        return await _grant_refresh_token(fields)
    return _oauth_error("unsupported_grant_type")


def _oauth_error(error: str) -> JSONResponse:
    return JSONResponse({"error": error}, status_code=400)


def _client_matches(fields: dict[str, str], bound_client_id: Any) -> bool:
    """A presented client_id must match the one the grant was issued to."""
    presented = fields.get("client_id")
    return not presented or not bound_client_id or presented == str(bound_client_id)


async def _grant_authorization_code(fields: dict[str, str]) -> Response:
    code = fields.get("code", "")
    data = await _prod.authserver.pop_auth_code(code) if code else None
    if data is None or not _client_matches(fields, data.get("client_id")):
        return _oauth_error("invalid_grant")
    if fields.get("redirect_uri", "") != data["redirect_uri"]:
        return _oauth_error("invalid_grant")
    if not asrv.verify_pkce_s256(fields.get("code_verifier", ""), str(data["code_challenge"])):
        return _oauth_error("invalid_grant")
    return await _issue_tokens(
        str(data["tenant_id"]), data.get("client_id"), str(data.get("scope") or SERVICE_SLUG)
    )


async def _grant_refresh_token(fields: dict[str, str]) -> Response:
    presented = fields.get("refresh_token", "")
    row = await _prod.authserver.consume_refresh(presented) if presented else None
    if row is None or int(row.get("expires_at", 0)) < int(_prod.clock.now()):
        return _oauth_error("invalid_grant")
    if not _client_matches(fields, row.get("client_id")):
        return _oauth_error("invalid_grant")
    tenant_id = str(row["tenant_id"])
    # A suspended/revoked tenant stops renewing (its JWT lapses within the access TTL).
    if not await _prod.tenant_is_active(tenant_id):
        return _oauth_error("invalid_grant")
    return await _issue_tokens(
        tenant_id, row.get("client_id"), str(row.get("scope") or SERVICE_SLUG)
    )


async def _issue_tokens(tenant_id: str, client_id: Any, scope: str) -> Response:
    now = int(_prod.clock.now())
    access = _prod.jwt_issuer.mint_access(
        subject=tenant_id, scope=scope, now=now, ttl_seconds=_ACCESS_TTL
    )
    refresh = asrv.new_opaque_token()
    await _prod.authserver.save_refresh(
        refresh,
        tenant_id=tenant_id,
        client_id=str(client_id) if client_id else None,
        scope=scope,
        expires_at=now + _REFRESH_TTL,
    )
    return JSONResponse(
        {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": _ACCESS_TTL,
            "refresh_token": refresh,
            "scope": scope,
        }
    )


# ── cron ─────────────────────────────────────────────────────────────────────────


async def cron_validate_tokens(request: Request) -> Response:
    secret = _prod.settings.cron_secret
    if not secret:
        return JSONResponse({"error": "cron_not_configured"}, status_code=503)
    presented = bearer_token(request.headers.get("authorization"))
    if presented is None or not hmac.compare_digest(presented.encode(), secret.encode()):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        summary = await _prod.validate_all_tokens()
    except DomainError:
        logger.exception("cron_validation_failed")
        return JSONResponse({"error": "backend_unavailable"}, status_code=503)
    log_event(logger, 20, "cron_tokens_validated", **summary)
    return JSONResponse(summary)


# ── error guard for the AS routes (store outages answer 503, never 500) ──────────


_Handler = Callable[[Request], Awaitable[Response]]


def _guard(handler: _Handler) -> _Handler:
    async def wrapper(request: Request) -> Response:
        try:
            response = await handler(request)
        except AuthError:
            return _oauth_error("invalid_grant")
        except DomainError:
            logger.exception("oauth_backend_unavailable")
            return JSONResponse({"error": "temporarily_unavailable"}, status_code=503)
        return response

    return wrapper


# ── build the app ───────────────────────────────────────────────────────────────

app = mcp.streamable_http_app()
app.add_route("/api/health", health, methods=["GET"])
app.add_route(PRM_PATH, protected_resource_metadata, methods=["GET"])
app.add_route(f"{PRM_PATH}{MCP_TRANSPORT_PATH}", protected_resource_metadata, methods=["GET"])
app.add_route(AS_META_PATH, authorization_server_metadata, methods=["GET"])
app.add_route(JWKS_PATH, jwks, methods=["GET"])
app.add_route("/register", _guard(register), methods=["POST"])
app.add_route("/authorize", _guard(authorize), methods=["GET"])
app.add_route(OAUTH_CONSENT_PATH, _guard(authorize_consent), methods=["POST"])
app.add_route(OAUTH_CALLBACK_PATH, _guard(oauth_callback), methods=["GET"])
app.add_route("/token", _guard(token), methods=["POST"])
app.add_route(CRON_PATH, cron_validate_tokens, methods=["GET"])

# Added innermost first: the last one added wraps everything.
app.add_middleware(
    TenantAuthMiddleware, resolver=_prod, mcp_path=MCP_TRANSPORT_PATH, prm_url=_prm_url
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_prod.settings.cors_origin_list,
    allow_methods=["GET", "POST", "OPTIONS"],
    # Bearer auth; the only cookies are the browser login's (SameSite=Lax) and no
    # credentials are allowed cross-origin, so any request header grants nothing extra.
    allow_headers=["*"],
    expose_headers=["WWW-Authenticate", "Mcp-Session-Id", "X-Request-ID"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CorrelationIdMiddleware)
