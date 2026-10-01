"""Domain models returned by use cases and surfaced through MCP tools.

Models are permissive on input (unknown keys ignored) because upstream payloads are
large and only a subset is worth surfacing.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# Identifiers are embedded in upstream URL paths: constrain them so a value can never
# smuggle a path segment, query string or traversal into the request.
ResourceId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class StoredToken(_Base):
    """The upstream credential of one tenant.

    Covers the three shapes seen across providers: a refresh token that mints
    short-lived access tokens (Google, TikTok), a long-lived access token without a
    refresh token (Meta, LinkedIn) and a static token pasted by the user (BYOT,
    Cloudflare). ``access_expires_at`` is ``None`` for tokens that never expire.
    """

    access_token: str | None = None
    refresh_token: str | None = None
    access_expires_at: int | None = None
    scopes: list[str] = Field(default_factory=list)
    obtained_at: int | None = None
    # Stable upstream account id: the tenant identity is derived from it.
    subject: str | None = None
    # Display label (e-mail or name). PII: shown to its owner, never logged.
    account_label: str | None = None


class UpstreamIdentity(_Base):
    """Who the upstream says the credential belongs to."""

    subject: str
    label: str | None = None


class TenantIdentity(_Base):
    """A tenant resolved from a validated MCP access token or API key."""

    tenant_id: str
    scopes: list[str] = Field(default_factory=list)


class WriteResult(_Base):
    """Outcome of a write tool: executed, or a preview of what would be sent."""

    executed: bool
    detail: str
    payload: dict[str, Any] | None = None
    result: dict[str, Any] | None = None


# ── Example slice: items ─────────────────────────────────────────────────────────
# SCAFFOLD: replace with the upstream's real resources.


class Item(_Base):
    """An upstream item."""

    id: str
    name: str | None = None
    status: str | None = None
    created_at: str | None = Field(default=None, alias="createdAt")
