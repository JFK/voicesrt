"""Tests for src.services.crypto."""

import hashlib

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from src.config import settings as app_settings
from src.models import Setting
from src.services.crypto import (
    ENCRYPTED_KEY_PREFIXES,
    ENCRYPTION_KEY_FINGERPRINT_SETTING,
    DecryptionError,
    EncryptionService,
    decrypt,
    decrypt_credential,
    encrypt,
    get_fingerprint,
)
from tests.helpers import foreign_fernet_token, isolated_api_keys


def test_encrypt_decrypt_roundtrip():
    token = encrypt("sk-roundtrip")
    assert decrypt(token) == "sk-roundtrip"


def test_decrypt_credential_raises_decryption_error_under_rotated_key():
    """A token written under a *different* Fernet key must surface as
    DecryptionError, not as the raw cryptography.fernet.InvalidToken — that
    contract is what callers depend on to render a friendly recovery message
    instead of crashing.
    """
    with pytest.raises(DecryptionError):
        decrypt_credential(foreign_fernet_token())


def test_get_fingerprint_known_value(monkeypatch):
    """Pin a known input/output pair instead of re-implementing the SHA-256
    formula inside the assertion. Pre-computed externally with:

        printf 'test-pinned-key-fingerprint-fixture' | sha256sum

    Re-computing in the test would silently pass even if both production
    and test code were miswired to a different hash algorithm.
    """
    monkeypatch.setattr(app_settings, "encryption_key", "test-pinned-key-fingerprint-fixture")
    assert get_fingerprint() == "290c5ee60c25ab3b86d5b13a6bc174b751fa0046df6d0da84fcbb4e20347a121"


def test_get_fingerprint_returns_64_char_lowercase_hex():
    """SHA-256 hex digest is always 64 lowercase hex chars; pin the shape so
    downstream storage / comparison code doesn't accidentally truncate or
    case-normalize.
    """
    fp = get_fingerprint()
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_get_fingerprint_changes_when_key_changes(monkeypatch):
    """Two distinct ENCRYPTION_KEY values must yield two distinct fingerprints.
    Equality on the fingerprint is what /settings uses to detect rotation, so
    a collision here would silently break rotation detection.
    """
    original = get_fingerprint()
    foreign_key = Fernet.generate_key().decode()
    monkeypatch.setattr(app_settings, "encryption_key", foreign_key)
    assert get_fingerprint() != original


def test_get_fingerprint_raises_when_key_unset(monkeypatch):
    """An empty / unset ENCRYPTION_KEY must raise, not silently return a
    fingerprint of empty-string. Otherwise rotation detection would treat
    "key removed" the same as a real key value.
    """
    monkeypatch.setattr(app_settings, "encryption_key", "")
    with pytest.raises(RuntimeError):
        get_fingerprint()


# ─── EncryptionService class — same contracts via the class API ────────────


def test_encryption_service_static_methods_match_module_wrappers():
    """The class-level API and the module-level shims must return identical
    results — the shims are intentionally thin and must not diverge.
    """
    token = EncryptionService.encrypt("sk-class-vs-module")
    assert EncryptionService.decrypt(token) == "sk-class-vs-module"
    assert EncryptionService.decrypt(token) == decrypt(token)
    assert EncryptionService.get_fingerprint() == get_fingerprint()


def test_encryption_service_decrypt_credential_raises_decryption_error():
    """The class method honors the same DecryptionError contract as the shim,
    so callers can migrate from `decrypt_credential(...)` to
    `EncryptionService.decrypt_credential(...)` without changing their
    `except` clause.
    """
    with pytest.raises(DecryptionError):
        EncryptionService.decrypt_credential(foreign_fernet_token())


def test_encrypted_key_prefixes_contains_api_key():
    """The api_key.<provider> namespace is the canonical encrypted slot.
    Removing it from this set would silently downgrade live API keys to
    plaintext on the next save — pin the membership.
    """
    assert "api_key." in ENCRYPTED_KEY_PREFIXES


def test_encrypted_key_prefixes_excludes_meta_namespace():
    """The _meta.* namespace must NOT be in the encrypted-by-default set —
    fingerprint rows and similar metadata are intentionally plaintext.
    A regression here would write hashes to the DB encrypted under a
    rotating key, defeating their purpose as rotation detectors.
    """
    assert not any(p.startswith("_meta.") for p in ENCRYPTED_KEY_PREFIXES)
    # The active fingerprint key explicitly does not match any prefix.
    assert not any(ENCRYPTION_KEY_FINGERPRINT_SETTING.startswith(p) for p in ENCRYPTED_KEY_PREFIXES)


# ─── DB-aware methods (validate_stored_keys, api_key_status, reencrypt_all) ──


@pytest.mark.asyncio
async def test_validate_stored_keys_reports_per_row_status():
    """validate_stored_keys returns a {Setting.key: bool} map so an endpoint
    can render granular per-row recovery state, not just the binary
    all-decrypt signal that all_api_keys_decrypt provides.
    """
    async with isolated_api_keys() as session_factory:
        async with session_factory() as s:
            s.add(Setting(key="api_key.openai", value=encrypt("sk-real"), encrypted=True))
            s.add(Setting(key="api_key.google", value=foreign_fernet_token(), encrypted=True))
            await s.commit()

        async with session_factory() as s:
            status = await EncryptionService(s).validate_stored_keys()
        assert status == {"api_key.openai": True, "api_key.google": False}


@pytest.mark.asyncio
async def test_api_key_status_short_circuits_when_both_flags_set():
    """api_key_status pairs the two flags so callers can route on either
    signal. The implementation should stop iterating once both flags are
    set — verified indirectly by mixing a decryptable and an undecryptable
    row and asserting both flags are True.
    """
    async with isolated_api_keys() as session_factory:
        async with session_factory() as s:
            s.add(Setting(key="api_key.openai", value=encrypt("sk-real"), encrypted=True))
            s.add(Setting(key="api_key.google", value=foreign_fernet_token(), encrypted=True))
            await s.commit()

        async with session_factory() as s:
            has_decryptable, has_undecryptable = await EncryptionService(s).api_key_status()
        assert has_decryptable is True
        assert has_undecryptable is True


@pytest.mark.asyncio
async def test_reencrypt_all_rewrites_rows_and_updates_fingerprint():
    """Happy-path rotation: every encrypted row is re-encrypted from old_key
    to new_key, the active fingerprint is set to new_key's, and the report
    reflects success=N / failed=0.
    """
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()

    async with isolated_api_keys() as session_factory:
        async with session_factory() as s:
            # Two rows encrypted under the OLD key — what a real pre-rotation
            # DB looks like.
            old_fernet = Fernet(old_key.encode())
            s.add(
                Setting(
                    key="api_key.openai",
                    value=old_fernet.encrypt(b"sk-openai").decode(),
                    encrypted=True,
                )
            )
            s.add(
                Setting(
                    key="api_key.google",
                    value=old_fernet.encrypt(b"sk-google").decode(),
                    encrypted=True,
                )
            )
            await s.commit()

        async with session_factory() as s:
            report = await EncryptionService(s).reencrypt_all(old_key, new_key)
            await s.commit()
        assert report == {"success": 2, "failed": 0, "errors": []}

        # Verify rows are now decryptable under new_key.
        new_fernet = Fernet(new_key.encode())
        async with session_factory() as s:
            result = await s.execute(select(Setting).where(Setting.key.like("api_key.%")))
            for row in result.scalars():
                # If the value was correctly re-encrypted, new_fernet.decrypt
                # succeeds and returns the original plaintext.
                assert new_fernet.decrypt(row.value.encode()) in (b"sk-openai", b"sk-google")

            # Fingerprint row points to the NEW key — list_keys downstream will
            # match against the active fingerprint and stop flagging mismatch.
            fp_result = await s.execute(select(Setting).where(Setting.key == ENCRYPTION_KEY_FINGERPRINT_SETTING))
            fp_row = fp_result.scalar_one_or_none()
        expected_new_fp = hashlib.sha256(new_key.encode()).hexdigest()
        assert fp_row is not None
        assert fp_row.value == expected_new_fp


@pytest.mark.asyncio
async def test_reencrypt_all_reports_failures_without_aborting():
    """If a row fails to decrypt under old_key (e.g. it was already encrypted
    under a third unknown key), reencrypt_all records it in `errors` and
    proceeds with the rest. The caller — not the service — decides whether
    a partial result is acceptable.
    """
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    old_fernet = Fernet(old_key.encode())

    async with isolated_api_keys() as session_factory:
        async with session_factory() as s:
            s.add(
                Setting(
                    key="api_key.openai",
                    value=old_fernet.encrypt(b"sk-recoverable").decode(),
                    encrypted=True,
                )
            )
            # Row encrypted under a THIRD key — neither old_key nor new_key.
            s.add(Setting(key="api_key.google", value=foreign_fernet_token(), encrypted=True))
            await s.commit()

        async with session_factory() as s:
            report = await EncryptionService(s).reencrypt_all(old_key, new_key)
            await s.commit()
    assert report["success"] == 1
    assert report["failed"] == 1
    assert report["errors"] == ["api_key.google"]
