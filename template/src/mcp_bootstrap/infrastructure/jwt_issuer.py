"""Issues and verifies the access tokens of our own OAuth 2.1 Authorization Server.

We mint short-lived ES256 JWTs signed with our private key and validate them locally
(no network). The public key is published as a JWKS so any standard client could
verify independently.
"""

from __future__ import annotations

import base64
import hashlib
import json

import jwt
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from jwt.algorithms import ECAlgorithm

from ..domain.errors import AuthError, ConfigError
from ..domain.models import TenantIdentity

_ALG = "ES256"


def _thumbprint(jwk: dict[str, str]) -> str:
    """RFC 7638 JWK thumbprint (base64url SHA-256 over the canonical members)."""
    canonical = json.dumps(
        {"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"], "y": jwk["y"]},
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(canonical.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class JwtIssuer:
    """Signs/verifies AS access tokens and exposes the JWKS."""

    def __init__(self, private_key_b64: str, *, issuer: str, audience: str) -> None:
        try:
            pem = base64.b64decode(private_key_b64, validate=True)
            loaded = load_pem_private_key(pem, password=None)
        except (ValueError, TypeError) as exc:
            raise ConfigError("MCP_JWT_PRIVATE_KEY is not a valid base64 PEM.") from exc
        if not isinstance(loaded, EllipticCurvePrivateKey):
            raise ConfigError("MCP_JWT_PRIVATE_KEY must be an EC (P-256) private key.")
        self._private_key = loaded
        self._public_key = loaded.public_key()
        self._issuer = issuer
        self._audience = audience
        jwk: dict[str, str] = json.loads(ECAlgorithm.to_jwk(self._public_key))
        self._kid = _thumbprint(jwk)
        self._jwk = {**jwk, "kid": self._kid, "use": "sig", "alg": _ALG}

    def mint_access(self, *, subject: str, scope: str, now: int, ttl_seconds: int) -> str:
        claims = {
            "iss": self._issuer,
            "sub": subject,
            "aud": self._audience,
            "iat": now,
            "exp": now + ttl_seconds,
            "scope": scope,
        }
        return jwt.encode(claims, self._private_key, algorithm=_ALG, headers={"kid": self._kid})

    def verify(self, token: str) -> TenantIdentity:
        try:
            claims = jwt.decode(
                token,
                self._public_key,
                algorithms=[_ALG],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError("Invalid MCP access token.") from exc
        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub:
            raise AuthError("Invalid MCP access token.")
        scope = claims.get("scope") or ""
        return TenantIdentity(tenant_id=sub, scopes=str(scope).split())

    def jwks(self) -> dict[str, list[dict[str, str]]]:
        return {"keys": [self._jwk]}
