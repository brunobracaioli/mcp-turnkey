"""Pure upstream-token lifecycle rules."""

from __future__ import annotations

from mcp_bootstrap.domain.models import StoredToken
from mcp_bootstrap.domain.tokens import (
    ACCESS_SKEW_SECONDS,
    apply_token_response,
    hash_token,
    usable_access_token,
)

NOW = 1_000_000.0


class TestUsableAccessToken:
    def test_none_without_access_token(self) -> None:
        assert usable_access_token(StoredToken(refresh_token="rt"), NOW) is None

    def test_token_without_expiry_never_expires(self) -> None:
        assert usable_access_token(StoredToken(access_token="at"), NOW) == "at"

    def test_valid_token_outside_the_skew_window(self) -> None:
        token = StoredToken(access_token="at", access_expires_at=int(NOW) + 3600)
        assert usable_access_token(token, NOW) == "at"

    def test_token_inside_the_skew_window_is_treated_as_expired(self) -> None:
        token = StoredToken(access_token="at", access_expires_at=int(NOW) + ACCESS_SKEW_SECONDS)
        assert usable_access_token(token, NOW) is None


class TestApplyTokenResponse:
    def test_sets_access_and_expiry(self) -> None:
        updated = apply_token_response(StoredToken(), {"access_token": "at", "expires_in": 60}, NOW)
        assert updated.access_token == "at"
        assert updated.access_expires_at == int(NOW) + 60

    def test_rotated_refresh_token_replaces_the_old_one(self) -> None:
        token = StoredToken(refresh_token="old")
        updated = apply_token_response(token, {"access_token": "at", "refresh_token": "new"}, NOW)
        assert updated.refresh_token == "new"

    def test_response_without_refresh_token_keeps_the_current_one(self) -> None:
        token = StoredToken(refresh_token="keep")
        assert apply_token_response(token, {"access_token": "at"}, NOW).refresh_token == "keep"

    def test_scopes_accept_comma_and_space_separators(self) -> None:
        updated = apply_token_response(StoredToken(), {"access_token": "a", "scope": "x,y z"}, NOW)
        assert updated.scopes == ["x", "y", "z"]

    def test_response_without_expiry_yields_a_non_expiring_token(self) -> None:
        updated = apply_token_response(StoredToken(), {"access_token": "a"}, NOW)
        assert updated.access_expires_at is None


def test_hash_token_is_stable_sha256_hex() -> None:
    assert hash_token("abc") == hash_token("abc")
    assert len(hash_token("abc")) == 64
    assert hash_token("abc") != hash_token("abd")
