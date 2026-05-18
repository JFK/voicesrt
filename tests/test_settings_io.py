"""Service-layer unit tests for settings_io export/preview/apply.

Lives at the service layer (no HTTP) so the contract for envelope shape,
fingerprint gating, schema_version handling, `_meta.*` filtering, and the
`encrypted` flag derivation is testable without spinning up FastAPI.

The HTTP-layer tests in tests/test_settings_api.py cover endpoint wiring,
proof-of-possession, and 2-stage import flow at the integration layer.
"""

import contextlib
from datetime import datetime

import pytest
from sqlalchemy import delete, select

from src.errors import AppError
from src.models import Setting
from src.services.crypto import EncryptionService, encrypt
from src.services.settings_io import (
    META_KEY_PREFIX,
    SUPPORTED_SCHEMA_VERSIONS,
    apply_import_envelope,
    export_settings_envelope,
    preview_import_envelope,
)
from tests.helpers import isolated_api_keys

# Plaintext Setting keys this test suite writes outside the api_key./_meta.
# namespaces. `isolated_settings()` only wipes those two prefixes per its own
# docstring, so we wipe these ourselves on entry+exit to keep tests isolated.
TEST_PLAINTEXT_KEYS = ("glossary",)


@contextlib.asynccontextmanager
async def isolated_settings():
    """`isolated_api_keys()` + plaintext-namespace wipe for this suite's keys."""
    async with isolated_api_keys() as session_factory:

        async def _wipe_plaintext() -> None:
            async with session_factory() as session:
                for key in TEST_PLAINTEXT_KEYS:
                    await session.execute(delete(Setting).where(Setting.key == key))
                await session.commit()

        await _wipe_plaintext()
        try:
            yield session_factory
        finally:
            await _wipe_plaintext()


async def _seed(session_factory, rows: list[tuple[str, str, bool]]) -> None:
    """Idempotent seed — overwrites pre-existing rows (conftest autouse
    re-inserts `api_key.openai = encrypt("sk-test")` between tests, so a
    plain INSERT would collide on the primary key)."""
    async with session_factory() as session:
        for key, value, encrypted in rows:
            await session.execute(delete(Setting).where(Setting.key == key))
            session.add(Setting(key=key, value=value, encrypted=encrypted))
        await session.commit()


async def _count_settings(session_factory) -> int:
    async with session_factory() as session:
        result = await session.execute(select(Setting))
        return len(result.scalars().all())


async def _get_setting(session_factory, key: str) -> Setting | None:
    async with session_factory() as session:
        result = await session.execute(select(Setting).where(Setting.key == key))
        return result.scalar_one_or_none()


class TestExportEnvelope:
    @pytest.mark.asyncio
    async def test_envelope_shape(self):
        async with isolated_settings() as session_factory:
            await _seed(session_factory, [("api_key.openai", encrypt("sk-x"), True)])
            async with session_factory() as session:
                envelope = await export_settings_envelope(session)

            assert envelope["schema_version"] == 1
            assert datetime.fromisoformat(envelope["exported_at"])
            assert envelope["source_fingerprint"] == EncryptionService.get_fingerprint()
            assert isinstance(envelope["settings"], list)

    @pytest.mark.asyncio
    async def test_excludes_meta_rows(self):
        async with isolated_settings() as session_factory:
            await _seed(
                session_factory,
                [
                    ("api_key.openai", encrypt("sk-x"), True),
                    ("_meta.encryption_key_fingerprint", "deadbeef", False),
                    ("_meta.custom_marker", "internal", False),
                    ("glossary", "VoiceSRT", False),
                ],
            )
            async with session_factory() as session:
                envelope = await export_settings_envelope(session)

            keys = [r["key"] for r in envelope["settings"]]
            assert not any(k.startswith(META_KEY_PREFIX) for k in keys)
            assert "api_key.openai" in keys
            assert "glossary" in keys

    @pytest.mark.asyncio
    async def test_includes_both_encrypted_and_plaintext(self):
        async with isolated_settings() as session_factory:
            await _seed(
                session_factory,
                [
                    ("api_key.openai", encrypt("sk-x"), True),
                    ("glossary", "VoiceSRT\nJohn", False),
                ],
            )
            async with session_factory() as session:
                envelope = await export_settings_envelope(session)

            by_key = {r["key"]: r for r in envelope["settings"]}
            assert by_key["api_key.openai"]["encrypted"] is True
            assert by_key["glossary"]["encrypted"] is False

    @pytest.mark.asyncio
    async def test_ciphertext_round_trips_unchanged(self):
        async with isolated_settings() as session_factory:
            ciphertext = encrypt("sk-secret")
            await _seed(session_factory, [("api_key.openai", ciphertext, True)])
            async with session_factory() as session:
                envelope = await export_settings_envelope(session)

            row = next(r for r in envelope["settings"] if r["key"] == "api_key.openai")
            # Export preserves the stored ciphertext byte-for-byte —
            # the destination decrypts under the same ENCRYPTION_KEY.
            assert row["value"] == ciphertext


class TestPreviewImport:
    @pytest.mark.asyncio
    async def test_raises_on_unknown_schema_version(self):
        async with isolated_settings() as session_factory:
            envelope = {
                "schema_version": 99,
                "exported_at": "2026-01-01T00:00:00+00:00",
                "source_fingerprint": EncryptionService.get_fingerprint(),
                "settings": [],
            }
            async with session_factory() as session:
                with pytest.raises(AppError) as exc:
                    await preview_import_envelope(session, envelope)
            assert exc.value.code == "IMPORT_SCHEMA_UNSUPPORTED"

    @pytest.mark.asyncio
    async def test_raises_on_fingerprint_mismatch(self):
        async with isolated_settings() as session_factory:
            envelope = {
                "schema_version": 1,
                "exported_at": "2026-01-01T00:00:00+00:00",
                "source_fingerprint": "0" * 64,
                "settings": [],
            }
            async with session_factory() as session:
                with pytest.raises(AppError) as exc:
                    await preview_import_envelope(session, envelope)
            assert exc.value.code == "IMPORT_FINGERPRINT_MISMATCH"

    @pytest.mark.asyncio
    async def test_raises_on_missing_source_fingerprint(self):
        async with isolated_settings() as session_factory:
            envelope = {
                "schema_version": 1,
                "exported_at": "2026-01-01T00:00:00+00:00",
                "settings": [],
            }
            async with session_factory() as session:
                with pytest.raises(AppError) as exc:
                    await preview_import_envelope(session, envelope)
            assert exc.value.code == "IMPORT_SCHEMA_UNSUPPORTED"

    @pytest.mark.asyncio
    async def test_raises_when_encryption_key_unset(self):
        # Symmetric with export_settings_envelope's export_fingerprint_missing —
        # _validate_envelope must catch RuntimeError from get_fingerprint() and
        # surface a structured AppError instead of an unhandled 500.
        from src.config import settings as app_settings

        async with isolated_settings() as session_factory:
            envelope = {
                "schema_version": 1,
                "exported_at": "2026-01-01T00:00:00+00:00",
                "source_fingerprint": "deadbeef" * 8,
                "settings": [],
            }
            # Manual set/restore — pytest's monkeypatch fixture would not be
            # reverted until after isolated_settings's teardown runs, and that
            # teardown calls encrypt() which needs the key.
            original_key = app_settings.encryption_key
            app_settings.encryption_key = ""
            try:
                async with session_factory() as session:
                    with pytest.raises(AppError) as exc:
                        await preview_import_envelope(session, envelope)
                assert exc.value.code == "IMPORT_FINGERPRINT_MISSING"
            finally:
                app_settings.encryption_key = original_key

    @pytest.mark.asyncio
    async def test_returns_counts(self):
        async with isolated_settings() as session_factory:
            await _seed(session_factory, [("api_key.openai", encrypt("sk-existing"), True)])
            envelope = {
                "schema_version": 1,
                "exported_at": "2026-01-01T00:00:00+00:00",
                "source_fingerprint": EncryptionService.get_fingerprint(),
                "settings": [
                    {"key": "api_key.openai", "value": encrypt("sk-new"), "encrypted": True},
                    {"key": "api_key.google", "value": encrypt("g-new"), "encrypted": True},
                    {"key": "glossary", "value": "VoiceSRT", "encrypted": False},
                ],
            }
            async with session_factory() as session:
                preview = await preview_import_envelope(session, envelope)

            assert preview["rows_total"] == 3
            assert preview["rows_encrypted"] == 2
            assert preview["rows_plaintext"] == 1
            assert preview["rows_overwrite"] == 1  # api_key.openai already exists
            assert preview["rows_new"] == 2
            assert preview["keys"] == ["api_key.google", "api_key.openai", "glossary"]

    @pytest.mark.asyncio
    async def test_no_db_writes(self):
        async with isolated_settings() as session_factory:
            envelope = {
                "schema_version": 1,
                "exported_at": "2026-01-01T00:00:00+00:00",
                "source_fingerprint": EncryptionService.get_fingerprint(),
                "settings": [
                    {"key": "glossary", "value": "preview-only", "encrypted": False},
                ],
            }
            before = await _count_settings(session_factory)
            async with session_factory() as session:
                await preview_import_envelope(session, envelope)
                # Caller may commit any session changes; preview itself adds no rows.
                await session.rollback()
            after = await _count_settings(session_factory)
            assert before == after

    @pytest.mark.asyncio
    async def test_filters_meta_rows_in_preview_counts(self):
        async with isolated_settings() as session_factory:
            envelope = {
                "schema_version": 1,
                "exported_at": "2026-01-01T00:00:00+00:00",
                "source_fingerprint": EncryptionService.get_fingerprint(),
                "settings": [
                    {"key": "_meta.encryption_key_fingerprint", "value": "abc", "encrypted": False},
                    {"key": "glossary", "value": "VoiceSRT", "encrypted": False},
                ],
            }
            async with session_factory() as session:
                preview = await preview_import_envelope(session, envelope)
            assert preview["rows_total"] == 1
            assert preview["keys"] == ["glossary"]


class TestApplyImport:
    @pytest.mark.asyncio
    async def test_upserts_new_rows(self):
        async with isolated_settings() as session_factory:
            envelope = {
                "schema_version": 1,
                "exported_at": "2026-01-01T00:00:00+00:00",
                "source_fingerprint": EncryptionService.get_fingerprint(),
                "settings": [
                    {"key": "api_key.google", "value": encrypt("g-x"), "encrypted": True},
                    {"key": "glossary", "value": "VoiceSRT", "encrypted": False},
                ],
            }
            async with session_factory() as session:
                report = await apply_import_envelope(session, envelope)
                await session.commit()

            assert report == {"imported": 2, "overwritten": 0, "new": 2}
            row = await _get_setting(session_factory, "glossary")
            assert row is not None
            assert row.value == "VoiceSRT"
            assert row.encrypted is False

    @pytest.mark.asyncio
    async def test_overwrites_existing_rows(self):
        async with isolated_settings() as session_factory:
            await _seed(session_factory, [("glossary", "old-value", False)])
            envelope = {
                "schema_version": 1,
                "exported_at": "2026-01-01T00:00:00+00:00",
                "source_fingerprint": EncryptionService.get_fingerprint(),
                "settings": [{"key": "glossary", "value": "new-value", "encrypted": False}],
            }
            async with session_factory() as session:
                report = await apply_import_envelope(session, envelope)
                await session.commit()

            assert report == {"imported": 1, "overwritten": 1, "new": 0}
            row = await _get_setting(session_factory, "glossary")
            assert row is not None
            assert row.value == "new-value"

    @pytest.mark.asyncio
    async def test_filters_meta_rows_from_writes(self):
        async with isolated_settings() as session_factory:
            envelope = {
                "schema_version": 1,
                "exported_at": "2026-01-01T00:00:00+00:00",
                "source_fingerprint": EncryptionService.get_fingerprint(),
                "settings": [
                    {"key": "_meta.poisoned", "value": "should-not-write", "encrypted": False},
                    {"key": "glossary", "value": "ok", "encrypted": False},
                ],
            }
            async with session_factory() as session:
                report = await apply_import_envelope(session, envelope)
                await session.commit()

            assert report["imported"] == 1
            assert await _get_setting(session_factory, "_meta.poisoned") is None
            glossary_row = await _get_setting(session_factory, "glossary")
            assert glossary_row is not None
            assert glossary_row.value == "ok"

    @pytest.mark.asyncio
    async def test_forces_encrypted_flag_for_api_key_prefix_update(self):
        # Tampered envelope: api_key.* row arrives with encrypted=False AND a
        # matching row already exists (the conftest baseline). Covers the
        # update branch — flag must be forced True from the prefix.
        async with isolated_settings() as session_factory:
            await _seed(session_factory, [("api_key.openai", encrypt("sk-existing"), True)])
            ciphertext = encrypt("sk-x")
            envelope = {
                "schema_version": 1,
                "exported_at": "2026-01-01T00:00:00+00:00",
                "source_fingerprint": EncryptionService.get_fingerprint(),
                "settings": [{"key": "api_key.openai", "value": ciphertext, "encrypted": False}],
            }
            async with session_factory() as session:
                await apply_import_envelope(session, envelope)
                await session.commit()

            row = await _get_setting(session_factory, "api_key.openai")
            assert row is not None
            assert row.encrypted is True

    @pytest.mark.asyncio
    async def test_forces_encrypted_flag_for_api_key_prefix_insert(self):
        # Tampered envelope: api_key.* row arrives with encrypted=False AND
        # NO matching row exists (insert branch). Covers the case where the
        # invariant is enforced at INSERT time, not just UPDATE — without
        # this, a fresh-install import could store plaintext credentials.
        async with isolated_settings() as session_factory:
            # Wipe any existing api_key.* rows (conftest baseline may seed one)
            async with session_factory() as session:
                await session.execute(delete(Setting).where(Setting.key.like("api_key.%")))
                await session.commit()

            ciphertext = encrypt("g-x")
            envelope = {
                "schema_version": 1,
                "exported_at": "2026-01-01T00:00:00+00:00",
                "source_fingerprint": EncryptionService.get_fingerprint(),
                "settings": [{"key": "api_key.google", "value": ciphertext, "encrypted": False}],
            }
            async with session_factory() as session:
                report = await apply_import_envelope(session, envelope)
                await session.commit()

            assert report["new"] == 1
            row = await _get_setting(session_factory, "api_key.google")
            assert row is not None
            assert row.encrypted is True, "INSERT branch must force encrypted=True for api_key.* prefix"

    @pytest.mark.asyncio
    async def test_does_not_commit(self):
        # Service writes to the session but the caller owns the commit.
        async with isolated_settings() as session_factory:
            envelope = {
                "schema_version": 1,
                "exported_at": "2026-01-01T00:00:00+00:00",
                "source_fingerprint": EncryptionService.get_fingerprint(),
                "settings": [{"key": "glossary", "value": "uncommitted", "encrypted": False}],
            }
            before = await _count_settings(session_factory)
            async with session_factory() as session:
                await apply_import_envelope(session, envelope)
                await session.rollback()  # caller chose to roll back

            assert await _count_settings(session_factory) == before
            assert await _get_setting(session_factory, "glossary") is None


class TestRoundtrip:
    @pytest.mark.asyncio
    async def test_export_then_apply_restores_state(self):
        async with isolated_settings() as session_factory:
            await _seed(
                session_factory,
                [
                    ("api_key.openai", encrypt("sk-source"), True),
                    ("glossary", "source-value", False),
                ],
            )
            # Export the current state
            async with session_factory() as session:
                envelope = await export_settings_envelope(session)

            # Wipe + re-apply
            async with session_factory() as session:
                await session.execute(delete(Setting).where(~Setting.key.like(f"{META_KEY_PREFIX}%")))
                await session.commit()

            assert await _get_setting(session_factory, "glossary") is None

            async with session_factory() as session:
                await apply_import_envelope(session, envelope)
                await session.commit()

            restored = await _get_setting(session_factory, "glossary")
            assert restored is not None
            assert restored.value == "source-value"
            assert restored.encrypted is False

            api_row = await _get_setting(session_factory, "api_key.openai")
            assert api_row is not None
            # Round-tripped ciphertext still decrypts under the same key
            assert EncryptionService.decrypt(api_row.value) == "sk-source"


class TestModuleSurface:
    def test_supported_schema_versions_set(self):
        assert 1 in SUPPORTED_SCHEMA_VERSIONS
        assert 0 not in SUPPORTED_SCHEMA_VERSIONS
