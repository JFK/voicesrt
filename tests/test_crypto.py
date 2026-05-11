"""Tests for src.services.crypto."""

import pytest
from cryptography.fernet import Fernet

from src.config import settings as app_settings
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
from tests.helpers import foreign_fernet_token


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
