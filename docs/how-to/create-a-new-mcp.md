# How to create a new MCP server from the template

1. **Generate the project** (from the root of this repository):

   ```bash
   python scripts/scaffold.py --name acme-crm --title "Acme CRM"
   # → ../mcp-acme-crm  (use --dest for another location)
   ```

   The script lists the `SCAFFOLD:` markers — each one is a decision about your provider.

2. **Environment and checks** in the generated project:

   ```bash
   cd ../mcp-acme-crm
   python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
   ruff check . && mypy src && pytest -q     # green before any change
   git init && git add -A && git commit -m "chore: scaffold from MCP Turnkey"
   ```

3. **Spec first:** fill `docs/specs/mcp-acme-crm.md` (real tools, edge cases,
   acceptance) and review the threat model.

4. **Provider:** resolve the `SCAFFOLD:` markers in `config.py` (endpoints, scopes,
   separator, identity fields) and in `upstream_client.py` (error envelope). No OAuth at
   the provider? Follow `docs/how-to/switch-to-byot-login.md` in the generated project.

5. **Replace the example slice** `items` with the real resources following
   `docs/how-to/add-a-tool-slice.md` (in the generated project).

6. **Deploy:** `docs/how-to/deploy-to-vercel.md` in the generated project — a dedicated
   Supabase project, `python scripts/gen_keys.py` for fresh keys, env vars without quotes.
