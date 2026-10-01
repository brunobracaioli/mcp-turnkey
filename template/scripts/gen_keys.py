"""Generate fresh production keys for THIS server and print them to stdout.

Usage: python scripts/gen_keys.py

Prints ``NAME=value`` lines (unquoted — paste the values into Vercel without quotes)
and writes nothing to disk. Run it once per server: never reuse another server's
keys, or a token minted/encrypted there becomes valid here.
"""

from __future__ import annotations

import base64
import os
import secrets

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

_AES_KEY_BYTES = 32
_SHARED_SECRET_BYTES = 48


def _jwt_signing_key() -> str:
    pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return base64.b64encode(pem).decode("ascii")


def main() -> None:
    values = {
        "TOKEN_ENCRYPTION_KEY": base64.b64encode(os.urandom(_AES_KEY_BYTES)).decode("ascii"),
        "MCP_JWT_PRIVATE_KEY": _jwt_signing_key(),
        "CRON_SECRET": secrets.token_urlsafe(_SHARED_SECRET_BYTES),
    }
    for name, value in values.items():
        print(f"{name}={value}")


if __name__ == "__main__":
    main()
