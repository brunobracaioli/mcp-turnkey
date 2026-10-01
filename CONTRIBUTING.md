# Contributing to MCP Turnkey

Thanks for helping! Bug reports, docs fixes, new production lessons and template
improvements are all welcome.

## Development setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e "template[dev]"          # the scaffold's tests reuse the template's deps

(cd template && ruff check . && ruff format --check . && mypy src && pytest -q)
ruff check . && mypy && pytest -q       # scaffold, incl. "the generated project passes"
```

Both must be green before you open a pull request — CI runs the same commands plus
`pip-audit` and `gitleaks`.

## Ground rules

- **Spec first.** A behavior change starts with the spec (`docs/specs/scaffold.md`
  for the scaffold, `template/docs/specs/` for the server) and, when it is structural,
  an ADR (`docs/adr/` or `template/docs/adr/`, Nygard format).
- **Security surface changes update the threat model**
  (`template/docs/security/threats/mcp-bootstrap.md`) in the same pull request.
- **Tests come with the change.** A bug fix starts with a test that reproduces it.
  Tests are deterministic: no network, no sleeps, fakes for the ports.
- **Inside `template/`, `bootstrap` is an identity token only** (package, slug, display
  name). In prose say "this server". The scaffold fails if any other occurrence survives.
- **Code and docs in English**, strict typing (`mypy --strict`, no `Any` without a
  comment explaining why), `ruff` clean.
- **Keep the template provider-agnostic.** Provider-specific behavior goes behind the
  `SCAFFOLD:` constants or into a how-to, not into the core.
- **Never commit secrets**, real tokens or real account ids — not even in tests.

## Commits and pull requests

- [Conventional Commits](https://www.conventionalcommits.org/):
  `feat(template): …`, `fix(scaffold): …`, `docs: …`, `sec: …`.
- Small, focused pull requests; describe the *why* and link the spec/ADR you touched.
- A new production lesson? Add a row to `docs/explanation/production-lessons.md`.

## Reporting vulnerabilities

Please do **not** open a public issue — see [`SECURITY.md`](SECURITY.md).
