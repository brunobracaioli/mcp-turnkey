# How to replace the OAuth login with "bring your own token" (BYOT)

For APIs without OAuth (static API tokens), the user pastes a token on this server's
own page instead of going through a provider login:

1. The `/authorize` consent screen (ADR 0007) gains the token field: the form still shows
   the client, the redirect origin and URI and the scopes, and the **Allow** button sends
   the token together with the `consent_id`. Do not remove the screen or the
   `__Host-consent_csrf` cookie: without them, a third-party link makes the victim hand
   their own token to the attacker's client.
2. The POST validates the consent binding (same checks as `/authorize/consent`),
   validates the token by calling the upstream (`identify`), stores a
   `StoredToken(access_token=..., access_expires_at=None)` and issues our authorization
   code directly (303 to the client). There is no provider callback, hence no
   `__Host-oauth_state`.
3. `OAuthProvider.refresh` raises `AuthError` (there is no refresh); `exchange_code` is
   no longer used.
4. Remove `UPSTREAM_CLIENT_ID/SECRET` from `.env.example` and from the reference.
5. Update ADR 0002 (new Decision) and the threat model (the token now passes through the
   browser).
