# How to deploy to Vercel

1. **Dedicated Supabase project:** create one and apply
   `supabase/migrations/*_init.sql`. On a project shared with another MCP server, prefix
   every table (Upstash keys are already prefixed with the slug).
2. **Upstash Redis:** create a database and copy `UPSTASH_REDIS_REST_URL`/`_TOKEN`.
3. **Keys:** `python scripts/gen_keys.py` — always fresh keys; never reuse another
   server's.
4. **Vercel project:** `vercel link`, then add the variables from
   [`env-vars.md`](../reference/env-vars.md) **without quotes** (e.g.
   `vercel env add NAME production --value '...'`).
5. **Deploy:** `vercel --prod`. `vercel.json` needs `"framework": "python"` and the root
   `app.py` — without them every route answers 404.
6. **Upstream OAuth:** register `https://<domain>/oauth/callback` on the provider's app.
7. **Verify:**
   - `curl https://<domain>/api/health` → `{"status":"ok"}` + security headers
   - `curl -i https://<domain>/api/mcp` → 405 `Allow: POST`
   - `curl -i -X POST https://<domain>/api/mcp` → 401 with `WWW-Authenticate`
8. **Connect from claude.ai:** Settings → Connectors → add a custom connector with the
   URL `https://<domain>/api/mcp`. You should see this server's consent screen, then the
   provider's login.

> After every deploy that changes tools, **reconnect the connector in claude.ai**: it
> caches the previous tool list.

## Operations

- **Suspend a tenant:** `UPDATE tenants SET status = 'suspended' WHERE id = '<uuid>';`
  (ADR 0005). New logins and refreshes stop at once; an open session ends within 8 h.
- **Purge expired refresh tokens:**
  `DELETE FROM oauth_refresh_tokens WHERE expires_at < extract(epoch FROM now());`
