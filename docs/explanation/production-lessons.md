# Lessons from production

Every row below is a failure that happened to a real, deployed MCP server — and the
fix the template ships so the next server does not repeat it. If you generated a server
from an older version of this template, this is the list worth porting.

| Symptom | Root cause | What the template does |
|---|---|---|
| CI went red on `main` with no code change | Linters pinned without an upper bound: a new ruff release added a rule | `ruff`/`mypy` pinned to a minor range; Dependabot proposes bumps as PRs that CI must pass |
| A dependency bot proposed re-opening a known crash | Dependabot widened `mcp<2` to `<3` | Dependabot `ignore` for major `mcp` updates, with the reason next to it |
| Every route answered 500 after a routine redeploy | `mcp` without an upper bound resolved 2.x, which removed `mcp.server.fastmcp` | `mcp[cli]>=1.12,<2` in `pyproject.toml` and `requirements.txt` |
| Every route answered 404 on Vercel | A rewrite to `/api/index` without a root `app.py` that Vercel's Python runtime detects | Root `app.py` re-exports the ASGI app; `vercel.json` sets `"framework": "python"` |
| Clients dropped valid credentials during an outage | A config or database error during token verification answered 401, which tells the client to discard its token | `AuthError` → 401, `BackendError`/`ConfigError` → 503 with `Retry-After` |
| OAuth and Redis broke right after setting env vars | Values pasted with quotes from a dotenv file (`"https://…"`) | The settings validator strips one pair of wrapping quotes |
| An allowlist with several hosts matched none | A CSV value treated as a single host | `_csv_set` parses CSV settings into a set |
| A store outage looked like an invalid credential | The store's failure and a bad credential raised the same error | Separate `AuthError` and `BackendError` all the way to the HTTP layer |
| Tokens from one server were accepted by another | Keys and secrets copied between servers | `scripts/gen_keys.py` per server + a fresh tenant namespace from the scaffold |
| Keys collided between servers | Two servers sharing one Supabase/Upstash | Every Redis key is prefixed with the slug; a dedicated Supabase project per server |
| Users had to reconnect every week | Google OAuth app left in "Testing" mode: refresh tokens expire in 7 days | Documented in `configure-upstream-oauth.md`: publish the app |
| New tools did not show up after a deploy | claude.ai caches the connector's tool list | Documented: reconnect the connector after deploys that change tools |
| An import vanished between edits | The post-edit `ruff check --fix` removes imports that are not used yet | Documented in the template's `CLAUDE.md`: add an import with its first use |
| Access tokens appeared in logs | httpx/httpcore log request URLs at INFO, and some APIs take the token as a query parameter | httpx/httpcore loggers pinned to WARNING |
| A connector cost tens of GB-hours per day while idle | `GET /api/mcp` opened an SSE stream that idled until the function's max duration | Stateless transport; non-POST answers 405 before authentication |
| An attacker's client could receive a victim's authorization code | Open DCR + one static provider `client_id` = the MCP spec's "confused deputy" | Per-client consent screen before the provider; `state` bound to the browser by a `__Host-` cookie |
| Any JSON registered as an OAuth client | DCR only checked that the redirect list was non-empty | DCR validated by a Pydantic schema: https or loopback redirects, valid hostnames, ≤ 10 URIs, body ≤ 16 KiB |
