# ADR 0007 — Per-client consent and a browser-bound `state` cookie

- Status: accepted
- Date: inherited from the template

## Context

This server is an OAuth proxy (ADR 0002): one static `client_id` at the provider and open
DCR. That enables the "confused deputy" attack described in the MCP specification: a
malicious client registered with its own redirect receives the authorization code of a
victim who only saw the provider's screen, which shows *our* app name. The MCP Security
Best Practices (2025-11-25) require per-client consent before the provider and `state`
validation through a cookie. Details in
[`oauth-client-consent.md`](../specs/oauth-client-consent.md).

## Decision

1. **The consent screen appears on every new connection.** Approvals are not remembered:
   we do not know who the user is before the provider login, and an approval cookie would
   be one more surface (signing, per-`client_id` binding, revocation). The cost is one
   click per connection; logins are rare because the refresh token lasts 30 days.
2. **Form CSRF via browser binding.** The GET stores a single-use record with
   `sha256(nonce)` and puts the nonce in a `__Host-consent_csrf` cookie
   (`Secure; HttpOnly; SameSite=Lax`). The POST is only valid with the matching cookie.
   `Origin` and `Sec-Fetch-Site` checks, when present, add defense in depth.
3. **The provider `state` is only born on approval.** The login request and the
   `__Host-oauth_state` cookie are created by the approved POST, right before the 303 to
   the provider, and the callback requires a cookie equal to `state`.
4. **The POST answers 303** (turns into a GET) to the provider or back to the client.
5. **Per-response CSP on the screen:** `form-action 'self'` plus the provider's and the
   client redirect's origins, because browsers apply `form-action` to the redirects that
   follow a submission. `SecurityHeadersMiddleware` only fills what the response left unset.
6. **HTML without scripts or inline styles**, everything escaped; the redirect origin is
   highlighted because the client name is chosen by whoever registers it.

## Consequences

- An `/authorize` link sent by a third party yields no code unless the victim approves a
  visible client and destination.
- Flows that relied on a direct 302 to the provider change: MCP clients are unaffected
  (they follow the browser), but tests and smoke scripts must go through the screen.
- Login requires first-party cookies; a browser that blocks them cannot connect.
- Accepted residual risk: a user may approve a malicious client with a convincing name;
  the highlighted redirect origin is the signal that protects them.
