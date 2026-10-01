"""The consent screen shown by ``GET /authorize`` (presentation only).

Plain semantic HTML: no script, no inline style (the CSP allows neither) and every
value escaped — the client name and redirect come from whoever registered the client.
Deny is the first button so it is the form's default. Spec: oauth-client-consent.md.
"""

from __future__ import annotations

from html import escape

from .application.consent import DECISION_APPROVE, DECISION_DENY, ConsentScreen
from .config import OAUTH_CONSENT_PATH


def render_consent_page(screen: ConsentScreen, *, service_name: str, upstream_name: str) -> str:
    service, upstream = escape(service_name), escape(upstream_name)
    client = escape(screen.client_name)
    scopes = "".join(f"<li><code>{escape(scope)}</code></li>" for scope in screen.scopes)
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Authorize {client} — {service}</title></head><body><main>"
        f"<h1>Allow {client} to access your {upstream} account?</h1>"
        f"<p><strong>{client}</strong> is asking to use {service} to act on your "
        f"{upstream} account.</p>"
        "<h2>Where access will be sent</h2>"
        f"<p>If you allow, access is handed to <strong>{escape(screen.redirect_origin)}"
        f"</strong>:</p><p><code>{escape(screen.redirect_uri)}</code></p>"
        "<p>Only allow if you started this connection yourself, in an app you trust. "
        "If you did not, or you do not recognize this address, choose Deny.</p>"
        f"<h2>Permissions requested from {upstream}</h2><ul>{scopes}</ul>"
        f'<form method="post" action="{escape(OAUTH_CONSENT_PATH)}">'
        f'<input type="hidden" name="consent_id" value="{escape(screen.consent_id)}">'
        f'<button type="submit" name="decision" value="{DECISION_DENY}">Deny</button> '
        f'<button type="submit" name="decision" value="{DECISION_APPROVE}">Allow</button>'
        "</form></main></body></html>"
    )
