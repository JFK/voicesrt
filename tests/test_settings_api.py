"""Tests for Settings API endpoints."""

import pytest

from src.models import Setting
from tests.helpers import foreign_fernet_token, isolated_api_keys


@pytest.mark.asyncio
async def test_list_keys_tolerates_undecryptable_row(make_client):
    """A row encrypted with a different ENCRYPTION_KEY must not crash the endpoint.

    Reproduces the failure mode where rotating ENCRYPTION_KEY (or restoring a
    DB from another environment) leaves stale rows that decrypt() rejects.
    The endpoint should surface them with `decryption_error: True` instead of
    returning HTTP 500.
    """
    from src.services.crypto import encrypt

    async with isolated_api_keys() as session_factory:
        async with session_factory() as s:
            s.add(Setting(key="api_key.openai", value=encrypt("sk-test"), encrypted=True))
            s.add(Setting(key="api_key.google", value=foreign_fernet_token(), encrypted=True))
            await s.commit()

        async with make_client() as c:
            resp = await c.get("/api/settings/keys")
        assert resp.status_code == 200
        data = resp.json()
        google_entry = next((e for e in data if e["provider"] == "google"), None)
        assert google_entry is not None
        assert google_entry.get("decryption_error") is True
        assert google_entry["masked"] == "****"
        openai_entry = next((e for e in data if e["provider"] == "openai"), None)
        assert openai_entry is not None
        assert openai_entry.get("decryption_error") is not True


@pytest.mark.asyncio
async def test_get_models(make_client):
    async with make_client() as c:
        resp = await c.get("/api/settings/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "openai" in data
    assert "gemini" in data


@pytest.mark.asyncio
async def test_set_model(make_client):
    async with make_client() as c:
        resp = await c.put("/api/settings/models/openai", json={"model": "gpt-5.4-mini"})
    assert resp.status_code == 200
    assert resp.json()["model"] == "gpt-5.4-mini"


@pytest.mark.asyncio
async def test_set_model_invalid_provider(make_client):
    async with make_client() as c:
        resp = await c.put("/api/settings/models/invalid", json={"model": "test"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_glossary(make_client):
    async with make_client() as c:
        resp = await c.get("/api/settings/glossary")
    assert resp.status_code == 200
    assert "glossary" in resp.json()


@pytest.mark.asyncio
async def test_set_glossary(make_client):
    async with make_client() as c:
        resp = await c.put("/api/settings/glossary", json={"value": "term1\nterm2"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_tone_references(make_client):
    async with make_client() as c:
        resp = await c.get("/api/settings/tone-references")
    assert resp.status_code == 200
    assert "tone_references" in resp.json()


@pytest.mark.asyncio
async def test_set_tone_references(make_client):
    async with make_client() as c:
        resp = await c.put(
            "/api/settings/tone-references",
            json={"value": "---\nTitle: Test\nDescription: Test desc\n---"},
        )
    assert resp.status_code == 200
    assert resp.json()["saved"] is True


@pytest.mark.asyncio
async def test_get_pricing(make_client):
    async with make_client() as c:
        resp = await c.get("/api/settings/pricing")
    assert resp.status_code == 200
    data = resp.json()
    assert "pricing" in data
    assert "whisper-1" in data["pricing"]


@pytest.mark.asyncio
async def test_set_pricing(make_client):
    async with make_client() as c:
        resp = await c.put(
            "/api/settings/pricing",
            json={"pricing": {"whisper-1": {"input_per_1m": 0.0, "output_per_1m": 0.0, "per_minute": 0.006}}},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_general_settings(make_client):
    async with make_client() as c:
        resp = await c.get("/api/settings/general")
    assert resp.status_code == 200
    data = resp.json()
    assert "max_upload_size_gb" in data


@pytest.mark.asyncio
async def test_set_general_setting(make_client):
    async with make_client() as c:
        resp = await c.put("/api/settings/general/max_upload_size_gb", json={"value": "5"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_set_general_setting_invalid_key(make_client):
    async with make_client() as c:
        resp = await c.put("/api/settings/general/nonexistent", json={"value": "test"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_meta_context(make_client):
    async with make_client() as c:
        resp = await c.get("/api/settings/meta-context")
    assert resp.status_code == 200
    data = resp.json()
    assert "context" in data
    assert "prompt" in data


@pytest.mark.asyncio
async def test_set_meta_context(make_client):
    async with make_client() as c:
        resp = await c.put(
            "/api/settings/meta-context",
            json={"context": '{"channelName": "Test"}', "prompt": "Generate metadata"},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_test_key_decryption_error(make_client):
    """test_key returns valid=False when ENCRYPTION_KEY has been rotated."""
    async with isolated_api_keys() as session_factory:
        async with session_factory() as s:
            s.add(Setting(key="api_key.openai", value=foreign_fernet_token(), encrypted=True))
            await s.commit()

        async with make_client() as c:
            resp = await c.post("/api/settings/keys/openai/test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert "Encryption key" in data["error"]


@pytest.mark.asyncio
async def test_save_key_invalid_provider(make_client):
    async with make_client() as c:
        resp = await c.put("/api/settings/keys/invalid", json={"key": "test-key"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_save_key_stamps_encryption_key_fingerprint(make_client):
    """Every successful save_key must persist the current ENCRYPTION_KEY
    fingerprint so list_keys can later detect rotation.
    """
    from sqlalchemy import select

    from src.services.crypto import (
        ENCRYPTION_KEY_FINGERPRINT_SETTING,
        get_fingerprint,
    )

    async with isolated_api_keys() as session_factory:
        async with make_client() as c:
            resp = await c.put("/api/settings/keys/openai", json={"key": "sk-fingerprint-test"})
        assert resp.status_code == 200

        async with session_factory() as s:
            result = await s.execute(select(Setting).where(Setting.key == ENCRYPTION_KEY_FINGERPRINT_SETTING))
            row = result.scalar_one_or_none()
        assert row is not None
        assert row.value == get_fingerprint()


@pytest.mark.asyncio
async def test_save_key_during_partial_recovery_preserves_stale_fingerprint(make_client):
    """Partial recovery scenario: stale fingerprint must NOT be overwritten while
    other api_key.% rows still fail to decrypt. Otherwise the rotation banner
    in list_keys would clear after the first re-save, hiding the fact that the
    remaining stale rows are still broken.
    """
    from sqlalchemy import select

    from src.services.crypto import ENCRYPTION_KEY_FINGERPRINT_SETTING

    stale_fp = "0" * 64

    async with isolated_api_keys() as session_factory:
        # Pre-state: an old undecryptable Google row + a stale fingerprint
        # mimicking "the prior ENCRYPTION_KEY". The user is mid-recovery
        # about to re-save OpenAI under the new key.
        async with session_factory() as s:
            s.add(Setting(key="api_key.google", value=foreign_fernet_token(), encrypted=True))
            s.add(Setting(key=ENCRYPTION_KEY_FINGERPRINT_SETTING, value=stale_fp, encrypted=False))
            await s.commit()

        async with make_client() as c:
            resp = await c.put("/api/settings/keys/openai", json={"key": "sk-partial-recovery"})
        assert resp.status_code == 200

        # Stored fingerprint must STILL be the stale value, because google is
        # still encrypted under the prior key. list_keys() must continue to
        # mark google with key_mismatch until the user re-saves it too.
        async with session_factory() as s:
            result = await s.execute(select(Setting).where(Setting.key == ENCRYPTION_KEY_FINGERPRINT_SETTING))
            row = result.scalar_one_or_none()
        assert row is not None
        assert row.value == stale_fp, "fingerprint must not advance until ALL rows decrypt under the active key"

        async with make_client() as c:
            resp = await c.get("/api/settings/keys")
        data = resp.json()
        google_entry = next((e for e in data if e["provider"] == "google"), None)
        assert google_entry is not None
        assert google_entry.get("decryption_error") is True
        assert google_entry.get("key_mismatch") is True


@pytest.mark.asyncio
async def test_save_key_after_full_recovery_refreshes_fingerprint(make_client):
    """Complementary scenario: once all api_key.% rows decrypt under the
    active key, the next save_key MUST advance the stored fingerprint so
    future rotations have a fresh baseline to compare against.
    """
    from sqlalchemy import select

    from src.services.crypto import (
        ENCRYPTION_KEY_FINGERPRINT_SETTING,
        get_fingerprint,
    )

    stale_fp = "0" * 64

    async with isolated_api_keys() as session_factory:
        async with session_factory() as s:
            s.add(Setting(key=ENCRYPTION_KEY_FINGERPRINT_SETTING, value=stale_fp, encrypted=False))
            await s.commit()

        # No stale undecryptable rows exist; save_key should advance the
        # fingerprint because every encrypted row (just this one) decrypts.
        async with make_client() as c:
            resp = await c.put("/api/settings/keys/openai", json={"key": "sk-clean-recovery"})
        assert resp.status_code == 200

        async with session_factory() as s:
            result = await s.execute(select(Setting).where(Setting.key == ENCRYPTION_KEY_FINGERPRINT_SETTING))
            row = result.scalar_one_or_none()
        assert row is not None
        assert row.value == get_fingerprint()


@pytest.mark.asyncio
async def test_list_keys_marks_key_mismatch_when_fingerprint_differs(make_client):
    """When the stamped fingerprint disagrees with the active ENCRYPTION_KEY,
    list_keys must attach key_mismatch=True to entries that fail to decrypt —
    distinguishing whole-key rotation from a single corrupted row.
    """
    from src.services.crypto import ENCRYPTION_KEY_FINGERPRINT_SETTING, encrypt

    async with isolated_api_keys() as session_factory:
        async with session_factory() as s:
            s.add(Setting(key="api_key.openai", value=encrypt("sk-real"), encrypted=True))
            s.add(Setting(key="api_key.google", value=foreign_fernet_token(), encrypted=True))
            # Stamp a *different* fingerprint to simulate "key rotated since save".
            s.add(Setting(key=ENCRYPTION_KEY_FINGERPRINT_SETTING, value="0" * 64, encrypted=False))
            await s.commit()

        async with make_client() as c:
            resp = await c.get("/api/settings/keys")
        assert resp.status_code == 200
        data = resp.json()
        google_entry = next((e for e in data if e["provider"] == "google"), None)
        assert google_entry is not None
        assert google_entry.get("decryption_error") is True
        assert google_entry.get("key_mismatch") is True
        # Decryptable rows must NOT carry key_mismatch — the flag only attributes
        # *failures* to rotation, not successes.
        openai_entry = next((e for e in data if e["provider"] == "openai"), None)
        assert openai_entry is not None
        assert "key_mismatch" not in openai_entry


@pytest.mark.asyncio
async def test_list_keys_omits_key_mismatch_when_no_stamped_fingerprint(make_client):
    """Legacy installs (rows pre-date the fingerprint feature) must not see a
    false rotation warning. A decryption failure with no stamped fingerprint
    is "unknown cause" — surface decryption_error but NOT key_mismatch.
    """
    async with isolated_api_keys() as session_factory:
        async with session_factory() as s:
            s.add(Setting(key="api_key.google", value=foreign_fernet_token(), encrypted=True))
            await s.commit()

        async with make_client() as c:
            resp = await c.get("/api/settings/keys")
        assert resp.status_code == 200
        data = resp.json()
        google_entry = next((e for e in data if e["provider"] == "google"), None)
        assert google_entry is not None
        assert google_entry.get("decryption_error") is True
        assert "key_mismatch" not in google_entry


# ─── _upsert_setting auto-detect contract (#71) ────────────────────────────


@pytest.mark.asyncio
async def test_upsert_setting_auto_encrypts_api_key_namespace():
    """api_key.<provider> keys must be persisted with encrypted=True when the
    caller omits the explicit flag. This is the safety net that #71 adds —
    forgetting to pass encrypted=True would previously have written
    plaintext credentials to the DB.
    """
    from sqlalchemy import select

    from src.api.settings import _upsert_setting

    async with isolated_api_keys() as session_factory:
        async with session_factory() as s:
            await _upsert_setting(s, "api_key.openai", "stub-ciphertext")
            await s.commit()

        async with session_factory() as s:
            row = (await s.execute(select(Setting).where(Setting.key == "api_key.openai"))).scalar_one()
        assert row.encrypted is True


@pytest.mark.asyncio
async def test_upsert_setting_defaults_plain_for_non_prefixed_keys():
    """Keys outside ENCRYPTED_KEY_PREFIXES default to encrypted=False — the
    _meta.encryption_key_fingerprint row is the canonical example. A
    regression here would write the SHA-256 hash through Fernet and break
    the rotation detector.
    """
    from sqlalchemy import select

    from src.api.settings import _upsert_setting

    test_key = "_meta.test_upsert_classification_marker"
    async with isolated_api_keys() as session_factory:
        async with session_factory() as s:
            await _upsert_setting(s, test_key, "plaintext-marker")
            await s.commit()

        async with session_factory() as s:
            row = (await s.execute(select(Setting).where(Setting.key == test_key))).scalar_one()
        assert row.encrypted is False
        assert row.value == "plaintext-marker"


@pytest.mark.asyncio
async def test_upsert_setting_rejects_plaintext_for_encrypted_prefix():
    """`encrypted=False` for a key in ENCRYPTED_KEY_PREFIXES is a contract
    violation — the prefix declaration is exactly what the safety net
    relies on. The function must raise instead of silently writing
    plaintext credentials.
    """
    from src.api.settings import _upsert_setting
    from src.database import async_session

    async with async_session() as s:
        with pytest.raises(ValueError, match="ENCRYPTED_KEY_PREFIXES"):
            await _upsert_setting(s, "api_key.openai", "would-be-plaintext", encrypted=False)
        # Roll back so the bad write does not persist even though we raised
        # before the commit.
        await s.rollback()
