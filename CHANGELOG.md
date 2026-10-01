# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [0.1.0] — unreleased

### Added

- Living template (`template/`): a multi-tenant MCP server in Python (FastMCP) that is
  its own OAuth 2.1 Authorization Server (discovery, DCR, PKCE S256, ES256 JWT, rotating
  refresh tokens), with a per-client consent screen against the "confused deputy"
  attack, AES-256-GCM encrypted upstream tokens in Supabase, Upstash for ephemeral state,
  tenant lifecycle via `status`, a stateless transport for Vercel, a token-validation
  cron and an HTTP hardening baseline.
- Scaffold (`scripts/scaffold.py`, standard library only) that copies and renames the
  template, draws a fresh tenant namespace and stamps the migration.
- CI: template checks, end-to-end scaffold, `pip-audit` and `gitleaks`.
- Docs: specs, ADRs, threat model and Diátaxis docs; production lessons.
