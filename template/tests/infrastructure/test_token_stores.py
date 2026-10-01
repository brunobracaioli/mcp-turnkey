"""Token persistence: Supabase + AES-GCM (+ cache), and the local file store."""

from __future__ import annotations

import json
import stat

from conftest import encryption_key_b64
from fakes import FailingCache, FakeCache, FakeSupabase
from mcp_bootstrap.config import SERVICE_SLUG
from mcp_bootstrap.domain.models import StoredToken
from mcp_bootstrap.infrastructure.crypto_aesgcm import AesGcmCrypto
from mcp_bootstrap.infrastructure.supabase_token_store import SupabaseTokenStore
from mcp_bootstrap.infrastructure.token_store_file import FileTokenStore

TENANT = "11111111-1111-4111-8111-111111111111"
TOKEN = StoredToken(
    access_token="ACCESS-PLAINTEXT",
    refresh_token="REFRESH-PLAINTEXT",
    access_expires_at=123,
    scopes=["items.read"],
    subject="acct-1",
    account_label="owner@example.test",
)


class TestSupabaseTokenStore:
    async def test_roundtrip(self) -> None:
        store = SupabaseTokenStore(TENANT, FakeSupabase(), AesGcmCrypto(encryption_key_b64()))  # type: ignore[arg-type]
        await store.save(TOKEN)
        assert await store.get() == TOKEN

    async def test_database_never_holds_plaintext_tokens(self) -> None:
        db = FakeSupabase()
        await SupabaseTokenStore(TENANT, db, AesGcmCrypto(encryption_key_b64())).save(TOKEN)  # type: ignore[arg-type]
        row = json.dumps(db.tokens[TENANT])
        assert "ACCESS-PLAINTEXT" not in row and "REFRESH-PLAINTEXT" not in row
        assert db.tenants[TENANT]["upstream_subject"] == "acct-1"

    async def test_cache_holds_ciphertext_and_is_invalidated_on_save(self) -> None:
        db, cache = FakeSupabase(), FakeCache()
        store = SupabaseTokenStore(TENANT, db, AesGcmCrypto(encryption_key_b64()), cache=cache)  # type: ignore[arg-type]
        await store.save(TOKEN)
        await store.get()  # populates the cache
        (key,) = cache.data
        assert key.startswith(f"{SERVICE_SLUG}:")
        assert "ACCESS-PLAINTEXT" not in cache.data[key]
        await store.save(TOKEN.model_copy(update={"access_token": "NEW"}))
        assert cache.data == {}
        fetched = await store.get()
        assert fetched is not None and fetched.access_token == "NEW"

    async def test_a_failing_cache_never_fails_the_request(self) -> None:
        store = SupabaseTokenStore(
            TENANT,
            FakeSupabase(),
            AesGcmCrypto(encryption_key_b64()),
            cache=FailingCache(),  # type: ignore[arg-type]
        )
        await store.save(TOKEN)
        assert await store.get() == TOKEN

    async def test_clear(self) -> None:
        store = SupabaseTokenStore(TENANT, FakeSupabase(), AesGcmCrypto(encryption_key_b64()))  # type: ignore[arg-type]
        await store.save(TOKEN)
        await store.clear()
        assert await store.get() is None


class TestFileTokenStore:
    async def test_roundtrip_with_owner_only_permissions(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        path = tmp_path / ".secrets" / "upstream_token.json"
        store = FileTokenStore(path)
        await store.save(TOKEN)
        assert await store.get() == TOKEN
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        await store.clear()
        assert await store.get() is None

    async def test_corrupt_file_reads_as_not_connected(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        path = tmp_path / "t.json"
        path.write_text("{not json")
        assert await FileTokenStore(path).get() is None
