"""Per-client consent before the upstream login ("confused deputy" mitigation).

Pure helpers (no I/O): the browser binding of the consent form, the same-origin check
of its submission, the state-cookie check of the upstream callback, and what the
consent screen shows. Spec: docs/specs/oauth-client-consent.md · ADR 0007.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from urllib.parse import urlsplit

# __Host- cookies must be Secure, Path=/ and carry no Domain: no subdomain can set them.
CSRF_COOKIE = "__Host-consent_csrf"
STATE_COOKIE = "__Host-oauth_state"

DECISION_APPROVE = "approve"
DECISION_DENY = "deny"
DECISIONS = frozenset({DECISION_APPROVE, DECISION_DENY})

UNNAMED_CLIENT = "Unnamed client"
_MAX_NAME_CHARS = 80
_NONCE_BYTES = 32
# Fetch metadata a browser sends for a form posted by this server's own page.
_SAME_ORIGIN_FETCH_SITES = frozenset({"same-origin", "none"})
# A DNS name or an IP literal; anything else must never reach the page or the CSP.
_SAFE_HOSTNAME = re.compile(r"^(?:[a-z0-9-]+(?:\.[a-z0-9-]+)*|[0-9a-f:.]+)$")


@dataclass(frozen=True)
class ConsentScreen:
    """Everything the consent page shows (still HTML-escaped by the page)."""

    consent_id: str
    client_name: str
    redirect_uri: str
    redirect_origin: str
    scopes: tuple[str, ...]


def new_browser_binding() -> tuple[str, str]:
    """``(nonce, digest)``: the nonce goes in the cookie, only its digest is stored."""
    nonce = secrets.token_urlsafe(_NONCE_BYTES)
    return nonce, binding_digest(nonce)


def binding_digest(nonce: str) -> str:
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def binding_matches(cookie_value: str | None, stored_digest: object) -> bool:
    """Whether the submitting browser holds the nonce the consent page was shown with."""
    if not cookie_value or not isinstance(stored_digest, str) or not stored_digest:
        return False
    return hmac.compare_digest(binding_digest(cookie_value), stored_digest)


def state_matches(cookie_value: str | None, state: str) -> bool:
    """Whether the upstream callback reached the browser that approved the consent."""
    if not cookie_value or not state:
        return False
    return hmac.compare_digest(cookie_value.encode("utf-8"), state.encode("utf-8"))


def safe_hostname(hostname: str | None) -> bool:
    return bool(hostname) and _SAFE_HOSTNAME.fullmatch(hostname or "") is not None


def origin_of(url: str) -> str:
    """``scheme://host[:port]`` of an absolute URL, or ``""`` when it has none.

    Built from the parsed parts (never from ``netloc``), so userinfo is dropped and a
    host outside the safe alphabet yields ``""`` instead of reaching a CSP header.
    """
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        return ""
    hostname = parts.hostname or ""
    if not parts.scheme or not safe_hostname(hostname):
        return ""
    host = f"[{hostname}]" if ":" in hostname else hostname
    return f"{parts.scheme.lower()}://{host}" + (f":{port}" if port else "")


def is_same_origin_submission(*, origin: str | None, fetch_site: str | None, issuer: str) -> bool:
    """Reject a consent POST that the browser marks as coming from another site.

    ``Origin`` and ``Sec-Fetch-Site`` are checked when present; the cookie binding is
    the primary control and covers clients that send neither.
    """
    if fetch_site is not None and fetch_site.strip().lower() not in _SAME_ORIGIN_FETCH_SITES:
        return False
    if origin is None:
        return True
    expected = origin_of(issuer)
    return bool(expected) and origin.strip().lower().rstrip("/") == expected


def display_client_name(raw: object) -> str:
    """A bounded, control-character-free label for the registered client."""
    if not isinstance(raw, str):
        return UNNAMED_CLIENT
    cleaned = "".join(ch for ch in raw if ch.isprintable()).strip()
    if not cleaned:
        return UNNAMED_CLIENT
    if len(cleaned) > _MAX_NAME_CHARS:
        return cleaned[:_MAX_NAME_CHARS] + "…"
    return cleaned


def form_action_sources(*origins: str) -> str:
    """CSP ``form-action`` sources: this server plus where the submission may redirect.

    Browsers apply ``form-action`` to the redirects that follow a form submission, so
    the provider (approve) and the client's redirect (deny) must both be allowed.
    """
    sources = ["'self'"]
    for origin in origins:
        if origin and origin not in sources:
            sources.append(origin)
    return " ".join(sources)
