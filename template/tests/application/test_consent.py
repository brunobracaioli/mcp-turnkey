"""Pure rules of the per-client consent (spec: oauth-client-consent.md)."""

from __future__ import annotations

import pytest

from mcp_bootstrap.application import consent

ISSUER = "https://mcp.example.test"


class TestBrowserBinding:
    def test_only_the_digest_leaves_the_browser_cookie(self) -> None:
        nonce, digest = consent.new_browser_binding()
        assert nonce not in digest
        assert consent.binding_matches(nonce, digest)

    @pytest.mark.parametrize("cookie", [None, "", "another-nonce"])
    def test_missing_or_foreign_cookie_does_not_match(self, cookie: str | None) -> None:
        _, digest = consent.new_browser_binding()
        assert not consent.binding_matches(cookie, digest)

    @pytest.mark.parametrize("stored", [None, "", 42])
    def test_corrupt_stored_digest_never_matches(self, stored: object) -> None:
        assert not consent.binding_matches("nonce", stored)


class TestStateCookie:
    def test_matches_only_the_same_state(self) -> None:
        assert consent.state_matches("s1", "s1")
        assert not consent.state_matches("s1", "s2")

    @pytest.mark.parametrize(("cookie", "state"), [(None, "s"), ("", "s"), ("s", "")])
    def test_missing_values_never_match(self, cookie: str | None, state: str) -> None:
        assert not consent.state_matches(cookie, state)


class TestOriginOf:
    @pytest.mark.parametrize(
        ("url", "origin"),
        [
            ("https://claude.ai/api/mcp/auth_callback", "https://claude.ai"),
            ("HTTPS://Claude.AI/cb", "https://claude.ai"),
            ("http://localhost:3000/callback", "http://localhost:3000"),
            ("http://[::1]:8080/cb", "http://[::1]:8080"),
            ("https://user:pass@evil.example/cb", "https://evil.example"),
        ],
    )
    def test_normalized_origin(self, url: str, origin: str) -> None:
        assert consent.origin_of(url) == origin

    @pytest.mark.parametrize(
        "url", ["/relative", "https://a;b.example/x", "https://a.example:99999/", "nonsense"]
    )
    def test_unsafe_or_relative_url_has_no_origin(self, url: str) -> None:
        assert consent.origin_of(url) == ""


class TestSameOriginSubmission:
    @pytest.mark.parametrize(
        ("origin", "fetch_site"),
        [
            (ISSUER, "same-origin"),
            (ISSUER + "/", None),
            (None, "same-origin"),
            (None, "none"),
            (None, None),  # old clients: the cookie binding still applies
        ],
    )
    def test_accepted(self, origin: str | None, fetch_site: str | None) -> None:
        assert consent.is_same_origin_submission(
            origin=origin, fetch_site=fetch_site, issuer=ISSUER
        )

    @pytest.mark.parametrize(
        ("origin", "fetch_site"),
        [
            ("https://evil.example", None),
            ("null", None),
            (None, "cross-site"),
            (None, "same-site"),
            (ISSUER, "cross-site"),
        ],
    )
    def test_rejected(self, origin: str | None, fetch_site: str | None) -> None:
        assert not consent.is_same_origin_submission(
            origin=origin, fetch_site=fetch_site, issuer=ISSUER
        )

    def test_unconfigured_issuer_rejects_any_origin(self) -> None:
        assert not consent.is_same_origin_submission(origin=ISSUER, fetch_site=None, issuer="")


class TestDisplayClientName:
    @pytest.mark.parametrize("raw", [None, "", "   ", 7, "\x00\x1b"])
    def test_absent_name_is_labelled_unnamed(self, raw: object) -> None:
        assert consent.display_client_name(raw) == consent.UNNAMED_CLIENT

    def test_control_characters_are_dropped(self) -> None:
        assert consent.display_client_name("Claude\u202e\nCode") == "ClaudeCode"

    def test_long_name_is_truncated(self) -> None:
        name = consent.display_client_name("x" * 500)
        assert len(name) == 81
        assert name.endswith("…")


class TestFormActionSources:
    def test_self_first_then_unique_origins(self) -> None:
        sources = consent.form_action_sources(
            "https://auth.example.com", "", "https://claude.ai", "https://claude.ai"
        )
        assert sources == "'self' https://auth.example.com https://claude.ai"
