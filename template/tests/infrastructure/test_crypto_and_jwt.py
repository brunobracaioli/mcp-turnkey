"""AES-256-GCM at rest and the ES256 access tokens of our Authorization Server."""

from __future__ import annotations

import base64
import time

import pytest

from conftest import encryption_key_b64, jwt_key_b64
from mcp_bootstrap.domain.errors import AuthError, ConfigError
from mcp_bootstrap.infrastructure.crypto_aesgcm import AesGcmCrypto
from mcp_bootstrap.infrastructure.jwt_issuer import JwtIssuer

ISSUER = "https://mcp.example.test"
AUDIENCE = f"{ISSUER}/api/mcp"
NOW = 1_700_000_000


class TestAesGcm:
    def test_roundtrip_with_a_fresh_nonce_each_time(self) -> None:
        crypto = AesGcmCrypto(encryption_key_b64())
        first, nonce_1 = crypto.encrypt("secret")
        second, nonce_2 = crypto.encrypt("secret")
        assert nonce_1 != nonce_2 and first != second
        assert crypto.decrypt(first, nonce_1) == "secret"

    def test_wrong_key_fails_closed(self) -> None:
        ciphertext, nonce = AesGcmCrypto(encryption_key_b64()).encrypt("secret")
        with pytest.raises(ConfigError):
            AesGcmCrypto(encryption_key_b64()).decrypt(ciphertext, nonce)

    @pytest.mark.parametrize("key", ["not base64!", base64.b64encode(b"short").decode()])
    def test_invalid_keys_are_config_errors(self, key: str) -> None:
        with pytest.raises(ConfigError):
            AesGcmCrypto(key)


class TestJwtIssuer:
    def test_mint_then_verify(self) -> None:
        issuer = JwtIssuer(jwt_key_b64(), issuer=ISSUER, audience=AUDIENCE)
        token = issuer.mint_access(
            subject="t1", scope="bootstrap", now=int(time.time()), ttl_seconds=60
        )
        identity = issuer.verify(token)
        assert identity.tenant_id == "t1"

    def test_expired_token_is_rejected(self) -> None:
        issuer = JwtIssuer(jwt_key_b64(), issuer=ISSUER, audience=AUDIENCE)
        token = issuer.mint_access(subject="t1", scope="s", now=NOW, ttl_seconds=60)
        with pytest.raises(AuthError):
            issuer.verify(token)

    def test_token_for_another_audience_is_rejected(self) -> None:
        key = jwt_key_b64()
        other = JwtIssuer(key, issuer=ISSUER, audience="https://other.test/api/mcp")
        token = other.mint_access(subject="t1", scope="s", now=int(time.time()), ttl_seconds=60)
        with pytest.raises(AuthError):
            JwtIssuer(key, issuer=ISSUER, audience=AUDIENCE).verify(token)

    def test_token_signed_by_another_key_is_rejected(self) -> None:
        token = JwtIssuer(jwt_key_b64(), issuer=ISSUER, audience=AUDIENCE).mint_access(
            subject="t1", scope="s", now=int(time.time()), ttl_seconds=60
        )
        with pytest.raises(AuthError):
            JwtIssuer(jwt_key_b64(), issuer=ISSUER, audience=AUDIENCE).verify(token)

    def test_jwks_publishes_the_public_key_with_a_kid(self) -> None:
        jwks = JwtIssuer(jwt_key_b64(), issuer=ISSUER, audience=AUDIENCE).jwks()
        (key,) = jwks["keys"]
        assert key["kty"] == "EC" and key["alg"] == "ES256" and key["kid"]
        assert "d" not in key  # never the private part
