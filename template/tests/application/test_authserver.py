"""Pure Authorization Server helpers: PKCE, tenant derivation, DCR validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mcp_bootstrap.application import authserver as asrv


class TestPkce:
    def test_generated_pair_verifies(self) -> None:
        verifier, challenge = asrv.pkce_pair()
        assert asrv.verify_pkce_s256(verifier, challenge)

    def test_wrong_verifier_fails(self) -> None:
        _, challenge = asrv.pkce_pair()
        assert not asrv.verify_pkce_s256("not-the-verifier", challenge)

    def test_empty_values_fail(self) -> None:
        assert not asrv.verify_pkce_s256("", "x")
        assert not asrv.verify_pkce_s256("x", "")


class TestTenantDerivation:
    def test_same_subject_maps_to_same_tenant(self) -> None:
        assert asrv.tenant_id_for_subject("acct-1") == asrv.tenant_id_for_subject("acct-1")

    def test_different_subjects_map_to_different_tenants(self) -> None:
        assert asrv.tenant_id_for_subject("acct-1") != asrv.tenant_id_for_subject("acct-2")


class TestRedirectUris:
    @pytest.mark.parametrize(
        "uri",
        [
            "https://claude.ai/api/mcp/auth_callback",
            "http://localhost:6274/oauth/callback",
            "http://127.0.0.1:33418/callback",
        ],
    )
    def test_allowed(self, uri: str) -> None:
        assert asrv.is_allowed_redirect_uri(uri)

    @pytest.mark.parametrize(
        "uri",
        [
            "http://evil.example/callback",
            "javascript:alert(1)",
            "https://ok.example/cb#fragment",
            "ftp://ok.example/cb",
            "not-a-url",
        ],
    )
    def test_rejected(self, uri: str) -> None:
        assert not asrv.is_allowed_redirect_uri(uri)


class TestClientRegistration:
    def test_defaults_to_code_and_refresh_grants(self) -> None:
        reg = asrv.ClientRegistration.model_validate({"redirect_uris": ["https://a.test/cb"]})
        assert reg.grant_types == ["authorization_code", "refresh_token"]

    def test_requested_secret_auth_method_is_ignored(self) -> None:
        reg = asrv.ClientRegistration.model_validate(
            {
                "redirect_uris": ["https://a.test/cb"],
                "token_endpoint_auth_method": "client_secret_basic",
            }
        )
        assert "token_endpoint_auth_method" not in reg.model_dump()

    def test_rejects_unsafe_redirect(self) -> None:
        with pytest.raises(ValidationError):
            asrv.ClientRegistration.model_validate({"redirect_uris": ["http://evil.example/cb"]})

    def test_rejects_too_many_redirects(self) -> None:
        uris = [f"https://a.test/cb{i}" for i in range(11)]
        with pytest.raises(ValidationError):
            asrv.ClientRegistration.model_validate({"redirect_uris": uris})

    def test_rejects_missing_redirects(self) -> None:
        with pytest.raises(ValidationError):
            asrv.ClientRegistration.model_validate({})

    def test_rejects_unknown_grant(self) -> None:
        with pytest.raises(ValidationError):
            asrv.ClientRegistration.model_validate(
                {"redirect_uris": ["https://a.test/cb"], "grant_types": ["password"]}
            )
