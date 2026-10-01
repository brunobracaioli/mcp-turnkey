# Spec — Per-client consent and `state` binding (confused deputy)

> Status: **implemented** (tests: `tests/test_asgi_consent.py`,
> `tests/application/test_consent.py`) · Decision: [ADR 0007](../adr/0007-per-client-consent-and-state-cookie.md)
> · Threats: [threat model](../security/threats/mcp-bootstrap.md)

## 1. Goal

Prevent an MCP client registered by an attacker from receiving someone else's
authorization code. The user must approve, on a screen of **this server**, the specific
client and the address the access will be sent to, before going to the provider; and the
provider's answer is only accepted in the same browser that approved it.

## 2. Context

This server is an OAuth proxy: it uses one static `client_id` at the upstream provider
and accepts Dynamic Client Registration (DCR) from any MCP client. Without per-client
consent:

1. The attacker registers a client with their own `https` `redirect_uri`.
2. They send the victim a link to our `/authorize` with their own `code_challenge`.
3. The victim sees the provider's screen, which shows **our** app's name — or no screen
   at all, if the provider remembers a previous consent — and approves.
4. Our code goes to the attacker, who exchanges it for a JWT of the victim's tenant.

The "Confused Deputy Problem" section of the MCP Security Best Practices (2025-11-25)
makes these mandatory: per-client consent before the provider, a screen that identifies
the client, the scopes and the `redirect_uri`, CSRF protection, anti-framing, and `state`
validation through a cookie set only after approval.

## 3. Scope

**In:** `GET /authorize`, `POST /authorize/consent`, `GET /oauth/callback` and hostname
validation in DCR.

**Out:**

- Remembering consent (an approval cookie). The screen appears on every new connection;
  see ADR 0007.
- Providers with `response_mode=form_post` (the `SameSite=Lax` cookie would not be sent
  on the POST).
- Local (stdio) login: it does not use these routes.
- Translating the page (the server's HTML pages are in English).

## 4. Contract

### 4.1 `GET /authorize`

Validations, in order: per-IP rate limit → the client exists and `redirect_uri` is
exactly one of its registered URIs (otherwise 400 without redirecting) →
`response_type=code` → PKCE S256 → public URL configured.

Success: **200** with the consent screen.

- Single-use record `<slug>:consent:<consent_id>` in the cache, TTL 600 s:
  `client_id`, `redirect_uri`, `code_challenge`, `client_state`, `scope` and
  `binding = sha256(nonce)`. **No login request is stored at this stage.**
- `Set-Cookie: __Host-consent_csrf=<nonce>; Max-Age=600; Path=/; Secure; HttpOnly; SameSite=Lax`
- `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self' <provider origin> <client redirect origin>`
  (browsers also apply `form-action` to the redirects that follow the POST).
- The page shows, HTML-escaped: the client name (no control characters, ≤ 80 chars,
  `Unnamed client` when absent); the redirect origin, highlighted, and the full
  `redirect_uri`; this server's and the provider's names; the scopes requested from the
  provider; a warning to deny if the user did not start the connection; and a
  `POST /authorize/consent` form with a hidden `consent_id` and the buttons **Deny**
  (first) and **Allow** (`name="decision"`, values `deny`/`approve`). No scripts, no
  inline styles.

### 4.2 `POST /authorize/consent`

Checks, in order:

| # | Check | Failure |
|---|---|---|
| 1 | Per-IP rate limit (bucket `consent`) | 429 `rate_limited` + `Retry-After` |
| 2 | `Sec-Fetch-Site`, when present, is `same-origin` or `none`; `Origin`, when present, is this server's origin | 403 (page) |
| 3 | Body ≤ 4 KiB; non-empty `consent_id`; `decision` ∈ {`approve`, `deny`} | 400 (page) |
| 4 | `consent_id` exists (consumed here, single use) | 400 "expired or already used" |
| 5 | `__Host-consent_csrf` cookie present and `sha256(cookie) == binding` (constant time) | 403; the record was already consumed |

After the checks, every response expires the CSRF cookie.

- `deny` → **303** to `redirect_uri?error=access_denied[&state=<client_state>]`.
- `approve` → stores the login request under a fresh `state` (TTL 600 s), sets
  `__Host-oauth_state=<state>; Max-Age=600; Path=/; Secure; HttpOnly; SameSite=Lax`
  and answers **303** to the provider.

### 4.3 `GET /oauth/callback`

After `error`/`code`/`state`: requires the `__Host-oauth_state` cookie to equal `state`
(constant time) **before** the login request is consumed; otherwise 400 without touching
the store. Every callback response expires the `state` cookie.

### 4.4 DCR

A `redirect_uri` is accepted only with a hostname shaped like a DNS name or an IP. The
origin shown on the screen and used in the CSP therefore never carries `;`, spaces or
other odd characters.

### 4.5 Logs (no PII; with the request id)

`consent_shown`, `consent_approved`, `consent_denied` (with `client_id`) and
`consent_rejected` (`reason` = `cross_site` | `expired` | `binding`), plus
`oauth_state_rejected` at the callback.

## 5. Edge cases

| Case | Behavior |
|---|---|
| The attacker opens `/authorize` to get a `consent_id` and makes the victim's browser post it | 403: the victim has no cookie with that nonce (and a cross-site POST does not carry a `Lax` cookie) |
| Two simultaneous login tabs | The second approval overwrites the `state` cookie; the first one's callback fails with a message to start over |
| Browser "back" and re-submit | 400: the `consent_id` was already consumed |
| Screen open for more than 10 min | 400 "expired": start over from the client |
| Browser blocks cookies | Fails closed (403/400) with a message; there is no cookie-less mode |
| `client_name` with HTML or control characters | Escaped and cleaned; does not alter the page |
| Misleading `client_name` ("Claude") | Partial mitigation: the redirect origin is highlighted; see the accepted risk |
| Loopback redirect `http://localhost:<port>` | Accepted; the origin with its port goes into `form-action` |
| User denies | The client receives `access_denied`; nothing is stored |
| User cancels at the provider | Callback with `error` → "cancelled" page; cookie expired |
| Tokens already issued | Unaffected: refresh does not go through `/authorize` |

## 6. Acceptance criteria

- [x] A valid `GET /authorize` → 200 with the screen; client, origin/`redirect_uri` and
      scopes present; no `authreq` in the cache.
- [x] CSRF cookie `__Host-`, `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`.
- [x] Screen CSP with `form-action 'self'` + provider origin + redirect origin;
      `X-Frame-Options: DENY` and `frame-ancestors 'none'`.
- [x] A `client_name` containing `<script>` comes out escaped.
- [x] Approve → 303 to the provider, `state` cookie set, `authreq` stored.
- [x] Deny → 303 to the client with `access_denied` and the client's `state`; nothing stored.
- [x] POST without the cookie, with another browser's cookie, or with a cross-site
      `Origin` or `Sec-Fetch-Site` → 403; re-submitting the same `consent_id` → 400.
- [x] Callback without the `state` cookie or with a different value → 400 and the login
      request stays in the store.
- [x] POST rate limit → 429.
- [x] DCR refuses a redirect with an invalid hostname.
