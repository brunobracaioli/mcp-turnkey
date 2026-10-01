# Architecture

```
src/mcp_bootstrap/
  domain/          models, errors, ports (Protocols) and pure token rules
  application/     use cases per slice (items, auth, token_access) + pure helpers for
                   the Authorization Server (authserver), consent and rate_limit
  infrastructure/  adapters: upstream REST, upstream OAuth, Supabase, Upstash,
                   AES-GCM, ES256 JWT, token stores (Supabase, file, memory)
  observability/   JSON logs on STDERR with the request id
  server.py        MCP tools (thin)
  container.py     composition: Container (stdio) and ProdContainer (multi-tenant)
  middleware.py    correlation id, security headers, transport authentication
  asgi.py          production app: OAuth 2.1 AS, consent screen, transport, cron
  consent_page.py  the per-client consent screen (HTML, no scripts)
```

## A tool call in production

1. `CorrelationIdMiddleware` assigns the request id; `SecurityHeadersMiddleware` prepares
   the headers.
2. `TenantAuthMiddleware`: non-POST → 405; no bearer → 401; otherwise the ES256 JWT is
   verified locally. It builds a `RequestScope` (tenant + upstream client) in a
   `ContextVar`.
3. The tool calls the use case with `_host().api` (the current tenant's client).
4. `UpstreamAPIClient` asks `TokenAccess` for a token; it reads the
   `SupabaseTokenStore` (decrypts), refreshes when needed and persists the result.
5. Domain errors become a `ToolError` with a safe message.

## A new connection (hosted)

```
MCP client ──DCR──▶ /register
MCP client ──browser──▶ /authorize ──200 consent screen (cookie __Host-consent_csrf)
browser ──Allow──▶ /authorize/consent ──303──▶ provider login (cookie __Host-oauth_state)
provider ──▶ /oauth/callback: exchange code, identify account, encrypt + store token,
             derive tenant, mint our code ──302──▶ MCP client redirect_uri
MCP client ──PKCE──▶ /token ──▶ ES256 JWT (8 h) + rotating refresh token (30 d)
```

## Why things are the way they are

- **Tenant only from the credential:** no tool accepts `tenant_id`, so a malicious
  prompt cannot point at another tenant.
- **Provider constants in code, secrets in the environment:** public configuration is
  versioned and reviewed; secrets never go through a pull request.
- **Fakes in tests:** the ports let the whole OAuth flow run without network.
