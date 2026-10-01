"""Shared fixtures: a deterministic environment, keys and a Settings factory."""

from __future__ import annotations

import base64
import os
from collections.abc import Iterator
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from mcp_bootstrap.config import Settings, get_settings

PUBLIC_BASE_URL = "https://mcp.example.test"


def jwt_key_b64() -> str:
    """A fresh EC P-256 private key, PEM, base64 one line (MCP_JWT_PRIVATE_KEY shape)."""
    pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return base64.b64encode(pem).decode("ascii")


def encryption_key_b64() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def make_settings(**overrides: Any) -> Settings:
    """Settings from explicit values only — never the developer's .env.local."""
    values: dict[str, Any] = {
        "UPSTREAM_CLIENT_ID": "client-123",
        "UPSTREAM_CLIENT_SECRET": "secret-456",
        "PUBLIC_BASE_URL": PUBLIC_BASE_URL,
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _isolated_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings() -> Settings:
    return make_settings()
