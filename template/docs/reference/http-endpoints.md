# Reference — HTTP endpoints

Every response carries the security headers (ADR 0006) and `X-Request-ID`.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/health` | — | `{"status":"ok"}` |
| GET | `/.well-known/oauth-protected-resource` (and `…/api/mcp`) | — | PRM (RFC 9728) |
| GET | `/.well-known/oauth-authorization-server` | — | AS metadata (RFC 8414) |
| GET | `/.well-known/jwks.json` | — | ES256 public key |
| POST | `/register` | — · rate limit | DCR (RFC 7591); public client |
| GET | `/authorize` | — · rate limit | Validates client + PKCE and answers the consent screen (200) — ADR 0007 |
| POST | `/authorize/consent` | cookie `__Host-consent_csrf` · rate limit | `consent_id` + `decision`; approve → 303 to the provider, deny → 303 to the client with `access_denied` |
| GET | `/oauth/callback` | `state` + cookie `__Host-oauth_state` | Provider redirect; issues our authorization code |
| POST | `/token` | PKCE / refresh · rate limit | `authorization_code` and `refresh_token` (rotation) |
| POST | `/api/mcp` | Bearer (our JWT) | Stateless MCP transport, JSON responses |
| GET/DELETE/PUT | `/api/mcp` | — | **405** `Allow: POST` (ADR 0004) |
| GET | `/api/cron/validate-tokens` | `Bearer CRON_SECRET` | Refreshes/validates every stored token (daily cron) |

## Error codes

| Situation | Response |
|---|---|
| Missing / invalid bearer on `/api/mcp` | 401 + `WWW-Authenticate: Bearer resource_metadata="…"` |
| Server misconfigured or backend down during verification | 503 `backend_unavailable` + `Retry-After: 30` |
| Rate limit | 429 `rate_limited` + `Retry-After` |
| Invalid grant on `/token` | 400 `invalid_grant` |
| Backend failure on the OAuth routes | 503 `temporarily_unavailable` |

## Cookies (browser login only)

All are `__Host-`, `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age=600`.

| Cookie | Set by | Required by | Content |
|---|---|---|---|
| `__Host-consent_csrf` | `GET /authorize` (screen) | `POST /authorize/consent` | nonce; the server keeps only its SHA-256 |
| `__Host-oauth_state` | consent approval | `GET /oauth/callback` | the `state` sent to the provider |

Every response of the route that requires a cookie expires it (single use).
