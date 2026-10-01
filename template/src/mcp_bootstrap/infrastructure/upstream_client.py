"""Async client for the upstream REST API.

Responsibilities:
  * attach a valid access token (from an :class:`AccessTokenSource`) to every call;
  * retry transient failures (network, 5xx) with bounded exponential backoff;
  * on a 401, force one token refresh and retry once;
  * map error responses onto domain errors without leaking the raw payload.

Tokens are never logged. ``_to_domain_error`` is the one place that knows the
upstream's error envelope — adapt it to the provider when scaffolding.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import UPSTREAM_TIMEOUT_SECONDS
from ..domain.errors import (
    AuthError,
    ConflictError,
    DomainError,
    NotFoundError,
    RateLimitError,
    TransientError,
    UpstreamError,
    ValidationError,
)
from ..domain.ports import AccessTokenSource, Clock
from ..observability.logging import get_logger, log_event

logger = get_logger(__name__)

_MAX_RETRIES = 3
_BACKOFF_BASE_SECONDS = 0.5
_MAX_SAFE_MESSAGE_LENGTH = 300


class UpstreamAPIClient:
    """Concrete :class:`~mcp_bootstrap.domain.ports.UpstreamClient` adapter."""

    def __init__(
        self,
        base_url: str,
        tokens: AccessTokenSource,
        clock: Clock,
        *,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._tokens = tokens
        self._clock = clock
        self._http = http or httpx.AsyncClient(base_url=base_url, timeout=UPSTREAM_TIMEOUT_SECONDS)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("POST", path, json_body=body)

    async def patch(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("PATCH", path, json_body=body)

    async def delete(self, path: str) -> dict[str, Any]:
        return await self._request("DELETE", path)

    # ── request engine ──────────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = path.lstrip("/")
        attempt = 0
        force_refresh = False
        reauthed = False
        while True:
            attempt += 1
            access = await self._tokens.access_token(force_refresh=force_refresh)
            force_refresh = False
            try:
                response = await self._http.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers={"Authorization": f"Bearer {access}"},
                )
            except httpx.TransportError as exc:
                if attempt > _MAX_RETRIES:
                    raise TransientError("Network error reaching the upstream API.") from exc
                await self._backoff(attempt)
                continue

            if response.is_success:
                return _decode(response)

            error = _to_domain_error(response)
            if (
                isinstance(error, AuthError)
                and response.status_code == httpx.codes.UNAUTHORIZED
                and not reauthed
            ):
                # The access token may have expired mid-flight: refresh once and retry.
                reauthed = True
                force_refresh = True
                continue
            if isinstance(error, TransientError) and attempt <= _MAX_RETRIES:
                await self._backoff(attempt)
                continue
            raise error

    async def _backoff(self, attempt: int) -> None:
        await self._clock.sleep(_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))


def _to_domain_error(response: httpx.Response) -> DomainError:
    """Map an upstream error response onto a domain error.

    SCAFFOLD: adapt to the provider's error envelope. This default understands
    ``{"error": {"message": …, "code": …}}`` and ``{"message": …}``.
    """
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        payload = {}
    err = payload.get("error") if isinstance(payload, dict) else None
    envelope = err if isinstance(err, dict) else payload if isinstance(payload, dict) else {}
    raw_message = envelope.get("message")
    status = envelope.get("status") or envelope.get("code")
    status_text = str(status) if status is not None else None
    http_status = response.status_code
    request_id = response.headers.get("x-request-id")

    log_event(
        logger,
        logging.WARNING,
        "upstream_api_error",
        http=http_status,
        status=status_text,
        upstream_request_id=request_id,
    )

    if http_status == httpx.codes.TOO_MANY_REQUESTS:
        retry_after = response.headers.get("retry-after")
        return RateLimitError(
            "The upstream rate limit was reached. Wait and retry, or narrow the request.",
            retry_after_seconds=int(retry_after) if retry_after and retry_after.isdigit() else None,
            status=status_text,
        )
    if http_status in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
        return AuthError(
            "The upstream rejected the credential or it lacks access to this resource. "
            "Reconnect to authorize again.",
            code=http_status,
            status=status_text,
        )
    if http_status == httpx.codes.NOT_FOUND:
        return NotFoundError("The requested upstream object was not found.", code=http_status)
    if http_status == httpx.codes.CONFLICT:
        return ConflictError(
            "The object changed since it was read. Re-read it and retry.", code=http_status
        )
    if http_status >= httpx.codes.INTERNAL_SERVER_ERROR:
        return TransientError("Temporary upstream API error.", code=http_status)
    if http_status in (httpx.codes.BAD_REQUEST, httpx.codes.UNPROCESSABLE_ENTITY):
        # The upstream's own validation message helps the model fix its input; it is
        # length-capped because it is the one upstream string we pass through.
        message = str(raw_message)[:_MAX_SAFE_MESSAGE_LENGTH] if raw_message else None
        return ValidationError(message or "The upstream rejected the request.", code=http_status)
    return UpstreamError(f"Upstream API request failed ({http_status}).", code=http_status)


def _decode(response: httpx.Response) -> dict[str, Any]:
    if response.status_code == httpx.codes.NO_CONTENT or not response.content:
        return {}
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        return {}
    return body if isinstance(body, dict) else {"data": body}
