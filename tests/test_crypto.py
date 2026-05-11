"""Tests for src.services.crypto."""

import hashlib

import pytest
from cryptography.fernet import Fernet

from src.config import settings as app_settings
from src.services.crypto import (
    DecryptionError,
    decrypt,
    decrypt_credential,
    encrypt,
    get_fingerprint,
)


def test_encrypt_decrypt_roundtrip():
    token = encrypt("sk-roundtrip")
    assert decrypt(token) == "sk-roundtrip"


def test_decrypt_credential_raises_decryption_error_under_rotated_key():
    """A token written under a *different* Fernet key must surface as
    DecryptionError, not as the raw cryptography.fernet.InvalidToken — that
    contract is what callers depend on to render a friendly recovery message
    instead of crashing.
    """
    foreign_token = Fernet(Fernet.generate_key()).encrypt(b"sk-foreign").decode()
    with pytest.raises(DecryptionError):
        decrypt_credential(foreign_token)


def test_get_fingerprint_matches_sha256_of_active_key():
    expected = hashlib.sha256(app_settings.encryption_key.encode()).hexdigest()
    assert get_fingerprint() == expected
    # SHA-256 hex digest is always 64 chars; pin the contract so downstream
    # storage / comparison code doesn't accidentally truncate.
    assert len(get_fingerprint()) == 64


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
