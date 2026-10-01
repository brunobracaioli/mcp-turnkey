# Tutorial — first local run (stdio)

1. Create the environment:

   ```bash
   python -m venv .venv && . .venv/bin/activate
   pip install -e ".[dev]"
   pytest -q            # everything green before you touch anything
   ```

2. Create the OAuth app at the upstream provider and register the redirect
   `http://localhost:8765/oauth/callback`.
3. Copy `.env.example` to `.env.local` and fill `UPSTREAM_CLIENT_ID` and
   `UPSTREAM_CLIENT_SECRET`.
4. Register the server in Claude Code: copy `.mcp.json.example` to `.mcp.json`.
5. In Claude Code, ask it to run `bootstrap_login`; open the URL, approve, copy the
   full URL the browser was redirected to (the page may fail to load — that is fine)
   and pass it to `bootstrap_submit_callback`.
6. `bootstrap_token_status` should answer `authenticated: true`. The token is stored in
   `.secrets/upstream_token.json` (mode 0600, git-ignored).

To inspect over local HTTP: `python -m mcp_bootstrap --http` and the MCP Inspector at
`http://127.0.0.1:8000/mcp`.
