# Reference — environment variables

Values pasted with quotes from a dotenv file are accepted (one outer pair of quotes is
stripped), but register them without quotes on Vercel. Generate keys with
`python scripts/gen_keys.py`.

| Variable | Required | Purpose |
|---|---|---|
| `UPSTREAM_CLIENT_ID` / `UPSTREAM_CLIENT_SECRET` | yes (OAuth) | OAuth app at the upstream provider |
| `UPSTREAM_API_BASE_URL` | no | Overrides `UPSTREAM_API_BASE` (sandbox) |
| `UPSTREAM_OAUTH_REDIRECT_URI` | no | Default: `PUBLIC_BASE_URL` + `/oauth/callback` |
| `LOCAL_REDIRECT_URI` | no | Local (stdio) login; register it on the upstream app |
| `PUBLIC_BASE_URL` | prod | Public origin (issuer and audience) |
| `SUPABASE_URL` / `SUPABASE_SECRET_KEY` | prod | Database (service role) |
| `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` | prod | Ephemeral state, cache, rate limits |
| `TOKEN_ENCRYPTION_KEY` | prod | AES-256 key (base64 of 32 bytes) |
| `MCP_JWT_PRIVATE_KEY` | prod | EC P-256 private key, PEM, base64 on one line |
| `CRON_SECRET` | prod | Bearer of the cron route (Vercel sends it automatically) |
| `OAUTH_RATE_LIMIT_PER_MIN` | no (30) | Per IP, per OAuth route |
| `CORS_ALLOWED_ORIGINS` | no (`*`) | CSV of origins |
| `LOG_LEVEL` | no (`INFO`) | Root logger level |
