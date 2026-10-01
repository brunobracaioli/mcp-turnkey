"""Application configuration.

Provider facts (API host, OAuth endpoints, scopes) are code constants: they are
public, versioned with the code and edited once when the server is scaffolded.
Secrets and per-deployment values come from the environment (``.env.local`` during
local development) and are read-only here — the server never writes back to an env
file. Every ``SCAFFOLD:`` marker below is a decision to make for a new upstream.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root (…/src/mcp_bootstrap/config.py → parents[2]); locates .env.local
# regardless of the working directory the server is launched from.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _PROJECT_ROOT / ".env.local"

# Short service slug: prefix of tool names, Redis key namespace and OAuth scope.
SERVICE_SLUG = "bootstrap"
SERVICE_DISPLAY_NAME = "MCP Bootstrap"

# SCAFFOLD: the provider's name as users know it (shown on the consent screen).
UPSTREAM_DISPLAY_NAME = "Bootstrap"

# ── Upstream API ───────────────────────────────────────────────────────────────
# SCAFFOLD: the upstream REST base URL, version included (pin the version here).
UPSTREAM_API_BASE = "https://api.example.com/v1"
# SCAFFOLD: seconds before an upstream request is abandoned.
UPSTREAM_TIMEOUT_SECONDS = 60.0

# ── Upstream OAuth 2.0 (the login provider; distinct from our own AS) ──────────
# SCAFFOLD: the provider's authorization, token and identity endpoints.
OAUTH_AUTHORIZE_URL = "https://auth.example.com/oauth/authorize"
OAUTH_TOKEN_URL = "https://auth.example.com/oauth/token"  # noqa: S105 - public URL
OAUTH_USERINFO_URL = "https://api.example.com/v1/me"
# SCAFFOLD: least-privilege scopes; the separator differs per provider (Google uses
# " ", Meta and TikTok use ",").
OAUTH_SCOPES: tuple[str, ...] = ("items.read", "items.write")
OAUTH_SCOPE_SEPARATOR = " "
# SCAFFOLD: provider-specific authorize params (Google: access_type=offline +
# prompt=consent to always get a refresh token).
OAUTH_EXTRA_AUTHORIZE_PARAMS: Mapping[str, str] = {}
# SCAFFOLD: how the token endpoint authenticates the client.
TokenAuthMethod = Literal["client_secret_post", "client_secret_basic"]
OAUTH_TOKEN_AUTH_METHOD: TokenAuthMethod = "client_secret_post"  # noqa: S105 - a method name
# SCAFFOLD: userinfo fields holding the stable account id and a display label
# (Google/OIDC: "sub"/"email"; Meta Graph /me: "id"/"name").
OAUTH_SUBJECT_FIELD = "sub"
OAUTH_LABEL_FIELD = "email"

# ── Our own surface ─────────────────────────────────────────────────────────────
OAUTH_CALLBACK_PATH = "/oauth/callback"
OAUTH_CONSENT_PATH = "/authorize/consent"
MCP_TRANSPORT_PATH = "/api/mcp"
DEFAULT_LOCAL_REDIRECT_URI = "http://localhost:8765/oauth/callback"

_QUOTES = ("'", '"')
_MIN_QUOTED_LENGTH = 2


class Settings(BaseSettings):
    """Strongly-typed view of the process environment."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # ── Upstream OAuth client (absent when the upstream login is BYOT) ─────────
    upstream_client_id: str | None = Field(default=None, alias="UPSTREAM_CLIENT_ID")
    upstream_client_secret: str | None = Field(default=None, alias="UPSTREAM_CLIENT_SECRET")
    upstream_api_base_url: str | None = Field(default=None, alias="UPSTREAM_API_BASE_URL")
    upstream_oauth_redirect_uri: str | None = Field(
        default=None, alias="UPSTREAM_OAUTH_REDIRECT_URI"
    )
    # Local stdio login: the URL the provider redirects to; the user pastes it back.
    local_redirect_uri: str = Field(default=DEFAULT_LOCAL_REDIRECT_URI, alias="LOCAL_REDIRECT_URI")

    # ── Production multi-tenant settings (all optional; absent in local stdio) ──
    supabase_url: str | None = Field(default=None, alias="SUPABASE_URL")
    supabase_secret_key: str | None = Field(default=None, alias="SUPABASE_SECRET_KEY")
    upstash_redis_rest_url: str | None = Field(default=None, alias="UPSTASH_REDIS_REST_URL")
    upstash_redis_rest_token: str | None = Field(default=None, alias="UPSTASH_REDIS_REST_TOKEN")
    token_encryption_key: str | None = Field(default=None, alias="TOKEN_ENCRYPTION_KEY")
    cron_secret: str | None = Field(default=None, alias="CRON_SECRET")
    # Our OAuth 2.1 Authorization Server signing key (EC P-256 PEM, base64 one line).
    mcp_jwt_private_key: str | None = Field(default=None, alias="MCP_JWT_PRIVATE_KEY")
    public_base_url: str | None = Field(default=None, alias="PUBLIC_BASE_URL")
    # Per-IP budget of the public OAuth endpoints (/register, /authorize, /token).
    oauth_rate_limit_per_min: int = Field(default=30, ge=1, alias="OAUTH_RATE_LIMIT_PER_MIN")
    # CORS allowlist (CSV of origins). "*" keeps the permissive default.
    cors_allowed_origins: str = Field(default="*", alias="CORS_ALLOWED_ORIGINS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("*", mode="before")
    @classmethod
    def _strip_wrapping_quotes(cls, value: Any) -> Any:
        """Drop one pair of quotes copied from a dotenv file into the Vercel UI.

        In production a quoted ``"https://…"`` once broke the Upstash protocol and an
        OAuth client id; a real value never starts and ends with the same quote.
        """
        if isinstance(value, str):
            stripped = value.strip()
            if (
                len(stripped) >= _MIN_QUOTED_LENGTH
                and stripped[0] == stripped[-1]
                and stripped[0] in _QUOTES
            ):
                return stripped[1:-1]
            return stripped
        return value

    # ── derived ──────────────────────────────────────────────────────────────

    @staticmethod
    def _csv_set(raw: str | None) -> frozenset[str]:
        """Parse a comma-separated value into a set of trimmed, non-empty items."""
        if not raw:
            return frozenset()
        return frozenset(item.strip() for item in raw.split(",") if item.strip())

    @property
    def api_base(self) -> str:
        """Upstream REST base URL (env override for sandboxes, else the pinned constant)."""
        return (self.upstream_api_base_url or UPSTREAM_API_BASE).rstrip("/")

    @property
    def as_issuer(self) -> str | None:
        """This server's OAuth issuer (its public origin)."""
        return self.public_base_url.rstrip("/") if self.public_base_url else None

    @property
    def as_resource(self) -> str | None:
        """The protected MCP resource id (audience of issued tokens)."""
        base = self.as_issuer
        return f"{base}{MCP_TRANSPORT_PATH}" if base else None

    @property
    def upstream_redirect_uri(self) -> str | None:
        """Redirect URI registered on the upstream OAuth app for the hosted login."""
        if self.upstream_oauth_redirect_uri:
            return self.upstream_oauth_redirect_uri.rstrip("/")
        base = self.as_issuer
        return f"{base}{OAUTH_CALLBACK_PATH}" if base else None

    @property
    def cors_origin_list(self) -> list[str]:
        """Origins for the CORS middleware; ``["*"]`` when unrestricted."""
        raw = self.cors_allowed_origins.strip()
        if not raw or raw == "*":
            return ["*"]
        return sorted(self._csv_set(raw))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()
