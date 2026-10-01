# How to configure the upstream provider's OAuth

Every public fact about the provider lives in constants in
`src/mcp_bootstrap/config.py` (search for `SCAFFOLD:`):

| Constant | Examples |
|---|---|
| `OAUTH_AUTHORIZE_URL`, `OAUTH_TOKEN_URL`, `OAUTH_USERINFO_URL` | the provider's endpoints |
| `OAUTH_SCOPES` / `OAUTH_SCOPE_SEPARATOR` | Google `" "`; Meta and TikTok `","` |
| `OAUTH_EXTRA_AUTHORIZE_PARAMS` | Google: `{"access_type": "offline", "prompt": "consent"}` |
| `OAUTH_TOKEN_AUTH_METHOD` | `client_secret_post` (default) or `client_secret_basic` |
| `OAUTH_SUBJECT_FIELD` / `OAUTH_LABEL_FIELD` | OIDC `sub`/`email`; Meta Graph `/me` `id`/`name` |

Register these redirect URIs on the provider's OAuth app:

- production: `https://<your-domain>/oauth/callback`
- local: the value of `LOCAL_REDIRECT_URI` (default `http://localhost:8765/oauth/callback`)

## Known pitfalls

- **Google apps in "Testing" mode**: refresh tokens die after 7 days. Publish the app
  (or accept reconnecting weekly).
- **Tokens that never expire** (some business/system tokens, PATs): leave `expires_in`
  out — the domain treats `access_expires_at=None` as non-expiring; the cron validates
  them through `identify`.
- **No refresh token** (e.g. LinkedIn, Meta long-lived tokens): when the access token
  expires, the tool asks the user to reconnect.
- **Rotating refresh tokens** (e.g. TikTok): supported; read the race limitation in ADR 0003.
- **Token in the query string** (e.g. Meta Graph): keep `httpx` at WARNING (the default).
