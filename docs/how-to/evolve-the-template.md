# How to evolve the template

1. Work inside `template/` as in any MCP server (spec → code → tests → docs).
2. Use `bootstrap` **only** as an identity token (package, slug, display name). In prose
   say "this server". Never mention this repository's name inside the template.
3. Validate:

   ```bash
   cd template && ruff check . && ruff format --check . && mypy src && pytest -q
   cd .. && ruff check . && mypy && pytest -q   # includes the end-to-end scaffold
   ```

4. A new lesson from production? Add it to `docs/explanation/production-lessons.md`
   and, if it is a structural decision, to an ADR in the template.
