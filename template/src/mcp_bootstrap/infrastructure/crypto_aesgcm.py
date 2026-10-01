"""AES-256-GCM encryption for upstream tokens at rest.

The key is a 32-byte secret given as base64 via ``TOKEN_ENCRYPTION_KEY`` and lives
only in the environment. A fresh 96-bit nonce is drawn for every ``encrypt``; the
ciphertext carries the GCM tag, so tampering (or a wrong key) makes ``decrypt``
raise. Never reuse another server's key: each MCP server gets its own.
"""

from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..domain.errors import ConfigError

_NONCE_BYTES = 12  # 96-bit nonce recommended for AES-GCM
_KEY_BYTES = 32  # AES-256


class AesGcmCrypto:
    """Concrete :class:`~mcp_bootstrap.domain.ports.Crypto` adapter."""

    def __init__(self, key_b64: str) -> None:
        try:
            key = base64.b64decode(key_b64, validate=True)
        except (ValueError, TypeError) as exc:
            raise ConfigError("TOKEN_ENCRYPTION_KEY is not valid base64.") from exc
        if len(key) != _KEY_BYTES:
            raise ConfigError(f"TOKEN_ENCRYPTION_KEY must decode to {_KEY_BYTES} bytes.")
        self._aesgcm = AESGCM(key)

    def encrypt(self, plaintext: str) -> tuple[bytes, bytes]:
        nonce = os.urandom(_NONCE_BYTES)
        return self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None), nonce

    def decrypt(self, ciphertext: bytes, nonce: bytes) -> str:
        try:
            plaintext = self._aesgcm.decrypt(nonce, ciphertext, None)
        except InvalidTag as exc:
            # Wrong key or tampered ciphertext — never expose details.
            raise ConfigError("Failed to decrypt the stored token.") from exc
        return plaintext.decode("utf-8")
