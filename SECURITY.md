# Security policy

## Reporting a vulnerability

Please report vulnerabilities **privately** through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
(the **Security** tab → **Report a vulnerability**). Do not open a public issue.

Include what you can: the affected component (template, scaffold), a description of the
impact, steps to reproduce and, if possible, a suggested fix. You should get an
acknowledgement within a few days; fixes are released as soon as they are ready, with
credit to the reporter unless you prefer otherwise.

## Scope

In scope: the template server (`template/`) — the OAuth 2.1 Authorization Server, the
consent screen, token storage and encryption, tenant isolation, the HTTP hardening — and
the scaffold (`scripts/scaffold.py`).

Out of scope: vulnerabilities in a server *you* generated and then modified, in your
deployment configuration, or in third-party services (Vercel, Supabase, Upstash, the
upstream provider). Do report issues in upstream dependencies to their maintainers.

## Supported versions

Only the latest commit on `main` is supported. Servers generated from the template own
their code: when a security fix lands here, port it to your server (the change log and
`docs/explanation/production-lessons.md` describe what changed).

## Design

The threat model (STRIDE) lives in
[`template/docs/security/threats/mcp-bootstrap.md`](template/docs/security/threats/mcp-bootstrap.md),
and the security decisions in [`template/docs/adr/`](template/docs/adr/).
