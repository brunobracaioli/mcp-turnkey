# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [0.1.0] — unreleased

### Added

- Skeleton generated from an MCP server template: OAuth 2.1 Authorization Server (DCR +
  PKCE), per-client consent screen before the provider with a browser-bound `state`
  (ADR 0007 — mitigates the MCP spec's "confused deputy"), stateless MCP transport,
  encrypted upstream tokens (Supabase + AES-256-GCM), tenant lifecycle via `status`,
  HTTP hardening baseline and the example `items` slice.
