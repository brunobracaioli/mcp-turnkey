-- Migration: initial schema of the multi-tenant MCP Bootstrap server.
-- Spec: docs/specs/mcp-bootstrap.md · Threat model: docs/security/threats/mcp-bootstrap.md
-- Immutable once applied: fixes go in a NEW migration, never edit this file.
--
-- Meant for a DEDICATED Supabase project; on a shared project, prefix every table
-- instead (see docs/how-to/deploy-to-vercel.md).
--
-- RLS is default-deny on every table: only the service-role key (server-side, which
-- bypasses RLS) touches these rows. Encryption at rest is the real protection for
-- upstream tokens; RLS is defense in depth.

-- ── tenants ──────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.tenants (
    id                UUID PRIMARY KEY,
    -- Stable upstream account id; one account belongs to at most one tenant.
    upstream_subject  TEXT,
    -- Operator switch: a non-active tenant can neither log in again nor refresh its
    -- MCP token; an already-issued access token lapses within its TTL (8 h).
    status            TEXT NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active', 'suspended', 'revoked')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Global ownership: one upstream account maps to exactly one tenant.
CREATE UNIQUE INDEX IF NOT EXISTS tenants_upstream_subject_key
    ON public.tenants (upstream_subject) WHERE upstream_subject IS NOT NULL;

-- ── upstream_tokens: ONLY ciphertext of the token material ───────────────────────
CREATE TABLE IF NOT EXISTS public.upstream_tokens (
    tenant_id      UUID PRIMARY KEY REFERENCES public.tenants (id) ON DELETE CASCADE,
    ciphertext     TEXT NOT NULL,      -- AES-256-GCM of {access, refresh, expiry} JSON
    nonce          TEXT NOT NULL,
    scopes         TEXT[] NOT NULL DEFAULT '{}',
    subject        TEXT,
    account_label  TEXT,               -- e-mail/name: PII, never logged
    obtained_at    BIGINT,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── oauth_clients (Dynamic Client Registration) ──────────────────────────────────
CREATE TABLE IF NOT EXISTS public.oauth_clients (
    client_id                   TEXT PRIMARY KEY,
    client_name                 TEXT,
    redirect_uris               TEXT[] NOT NULL,
    grant_types                 TEXT[] NOT NULL,
    token_endpoint_auth_method  TEXT NOT NULL DEFAULT 'none',
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── oauth_refresh_tokens: our AS refresh tokens, stored ONLY as a hash ───────────
CREATE TABLE IF NOT EXISTS public.oauth_refresh_tokens (
    token_hash  TEXT PRIMARY KEY,
    tenant_id   UUID NOT NULL REFERENCES public.tenants (id) ON DELETE CASCADE,
    client_id   TEXT,
    scope       TEXT NOT NULL,
    expires_at  BIGINT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Supports purging expired rows (DELETE … WHERE expires_at < extract(epoch FROM now())).
CREATE INDEX IF NOT EXISTS oauth_refresh_tokens_expires_idx
    ON public.oauth_refresh_tokens (expires_at);

-- ── RLS: default-deny (no policies → no access for anon/authenticated) ───────────
ALTER TABLE public.tenants               ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.upstream_tokens       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.oauth_clients         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.oauth_refresh_tokens  ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.tenants               FROM anon, authenticated;
REVOKE ALL ON public.upstream_tokens       FROM anon, authenticated;
REVOKE ALL ON public.oauth_clients         FROM anon, authenticated;
REVOKE ALL ON public.oauth_refresh_tokens  FROM anon, authenticated;

-- New Supabase projects ship a SECURITY DEFINER `rls_auto_enable()` event-trigger
-- function EXECUTE-granted to public, which exposes it at /rest/v1/rpc. Revoking
-- EXECUTE does not affect the event trigger itself.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.proname = 'rls_auto_enable'
    ) THEN
        REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM public, anon, authenticated;
    END IF;
END
$$;
