"""Domain error hierarchy.

Adapters map raw upstream/infrastructure failures onto these types so the
application and presentation layers never depend on HTTP specifics. Every message
is written to be safe to surface to the model: raw payloads, tokens and internal
hosts must never be put in one.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for every error this server raises on purpose."""

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        status: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.request_id = request_id


class ConfigError(DomainError):
    """Missing or invalid server configuration (an operator problem)."""


class AuthError(DomainError):
    """A credential is missing, invalid, expired or lacks permission."""


class ValidationError(DomainError):
    """Input rejected by our own rules or by the upstream (HTTP 400)."""


class BackendError(DomainError):
    """Our own infrastructure (Supabase, Upstash) failed. Maps to HTTP 503."""


class UpstreamError(DomainError):
    """The upstream API failed in a way not covered by a subclass."""


class NotFoundError(UpstreamError):
    """The referenced upstream object does not exist or is not visible (404)."""


class ConflictError(UpstreamError):
    """The upstream object changed under the caller (409); re-read and retry."""


class TransientError(UpstreamError):
    """A temporary upstream failure that is safe to retry (5xx, network)."""


class RateLimitError(UpstreamError):
    """The upstream throttled us (429 or a quota error)."""

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: int | None = None,
        status: str | None = None,
    ) -> None:
        super().__init__(message, code=429, status=status)
        self.retry_after_seconds = retry_after_seconds
