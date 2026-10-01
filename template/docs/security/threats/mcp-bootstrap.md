# Threat model (STRIDE) — MCP Bootstrap

> Update this file in the same pull request as any change of surface (new route, new
> provider, new destructive write).

## Assets

Each tenant's upstream token · the JWT signing key · the encryption key · the cron
secret · upstream account data (PII: the owner's e-mail/name).

## Trust boundaries

MCP client ↔ `/api/mcp` · browser ↔ OAuth routes · server ↔ upstream ·
server ↔ Supabase/Upstash · Vercel cron ↔ `/api/cron/*`.

| Threat | Scenario | Mitigation |
|---|---|---|
| **S**poofing | Forged bearer on `/api/mcp` | ES256 JWT with iss/aud/exp verified locally; a non-active tenant can neither log in nor refresh |
| S | A malicious DCR client registers its own redirect and sends the victim an `/authorize` link (the MCP spec's "confused deputy") | This server's consent screen before the provider, showing the client name, the redirect origin and URI and the scopes (ADR 0007); redirects must be https (or http on loopback) with a valid hostname; `/authorize` only accepts a registered URI (exact match) |
| S | Consent form posted by another site, or the attacker's `consent_id` posted from the victim's browser | Single-use record bound to the browser: `sha256(nonce)` in the cache, nonce in a `__Host-` cookie `Secure; HttpOnly; SameSite=Lax`; cross-site `Origin`/`Sec-Fetch-Site` → 403 |
| S | Clickjacking of the consent screen | `frame-ancestors 'none'` + `X-Frame-Options: DENY` |
| S | Authorization code theft | Mandatory PKCE S256; single-use code, 300 s TTL, bound to client_id + redirect_uri |
| S | Forged cron call | `Bearer CRON_SECRET` compared in constant time; 503 when unset |
| **T**ampering | Altering the encrypted token in the database | Authenticated AES-GCM: an invalid tag fails closed |
| T | Forged login `state`, or a callback replayed in another browser (CSRF) | Opaque single-use `state` (600 s TTL) created only on approval; the `__Host-oauth_state` cookie is required at the callback before the request is consumed |
| T | HTML or control characters in `client_name` alter the screen | Name cleaned (≤ 80 chars, no control characters) and escaped; page without scripts or inline styles (CSP `default-src 'none'`) |
| **R**epudiation | Login or consent decision without a trace | Structured events (`consent_*`, `mcp_login_completed`, `login_refused_inactive_tenant`, …) with the request id and ids only |
| **I**nformation disclosure | Token in logs | JSON logs with ids only; httpx/httpcore at WARNING; upstream/PostgREST error bodies never forwarded (except 4xx validation messages, truncated to 300 chars) |
| I | Cross-tenant reads | Tenant derived only from the credential; no tool accepts `tenant_id` (ADR 0005) |
| **D**enial of service | Flood on `/register`, `/authorize`, `/authorize/consent`, `/token` | Per-IP rate limit + 429 `Retry-After`; DCR body ≤ 16 KiB, consent body ≤ 4 KiB |
| D | Billed idle SSE streams | 405 for non-POST on `/api/mcp`, before authentication |
| D | Huge payload in a tool | Size limits in the tool schemas (`max_length`, `le`) |
| **E**levation of privilege | Path smuggling in ids (`../admin`) | `^[A-Za-z0-9_-]{1,64}$` pattern in the schema + `quote(safe="")` in the path |
| E | Destructive call triggered by a prompt | Destructive tools do nothing without `confirm=true`; writes support `preview` |

## Accepted risks

- **Malicious client with a convincing name** ("Claude"): the name is chosen by whoever
  registers it. The user may approve it; the highlighted redirect origin on the screen is
  the signal that protects them (ADR 0007).
- **Consent is not remembered:** the screen appears on every new connection (one more
  click), in exchange for not keeping an approval cookie.
- **Suspension is bounded, not instant**, for sessions already open (≤ 8 h, ADR 0005).
- Fail-open rate limiting while Upstash is unavailable.
- Refresh race with providers that rotate refresh tokens (see ADR 0003).
- CORS `*` by default: the API uses a Bearer header; the only cookies are the browser
  login's (`SameSite=Lax`, no `allow_credentials`), which a third-party site can neither
  read nor send in a POST. Restrict with `CORS_ALLOWED_ORIGINS`.
