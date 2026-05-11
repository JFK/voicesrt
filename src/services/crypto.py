import hashlib

from cryptography.fernet import Fernet, InvalidToken

from src.config import settings

# Setting.key used as the storage slot for the active ENCRYPTION_KEY fingerprint.
# Stored at save time and compared on read to detect rotation without trying
# (and failing) to decrypt every row.
ENCRYPTION_KEY_FINGERPRINT_SETTING = "_meta.encryption_key_fingerprint"


class DecryptionError(RuntimeError):
    """Stored value cannot be decrypted — encryption key was rotated or replaced."""


def _get_fernet() -> Fernet:
    if not settings.encryption_key:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    return Fernet(settings.encryption_key.encode())


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def decrypt_credential(ciphertext: str) -> str:
    """Decrypt a stored credential.

    Raises DecryptionError if ENCRYPTION_KEY has changed since the value
    was encrypted, so callers can surface a user-friendly recovery message
    instead of crashing with a raw InvalidToken.
    """
    try:
        return decrypt(ciphertext)
    except InvalidToken:
        raise DecryptionError(
            "Encryption key has changed. Please re-enter your API key in Settings → API Keys."
        ) from None


def get_fingerprint() -> str:
    """Return a stable, non-reversible fingerprint of the active ENCRYPTION_KEY.

    SHA-256 hex of the ENCRYPTION_KEY string's UTF-8 bytes. Fernet keys are
    base64-encoded text, and we hash that text directly without
    base64-decoding it — the fingerprint is only an identity check, not a
    cryptographic transform of the underlying key material, so hashing the
    canonical string form is sufficient and avoids dragging in a decode
    step. The full 64-char digest is returned for exact equality checks;
    callers that only need a display form should slice locally.

    Raises RuntimeError if ENCRYPTION_KEY is not set — callers should not
    silently store an empty fingerprint, that would mask the misconfiguration.
    """
    if not settings.encryption_key:
        raise RuntimeError("ENCRYPTION_KEY is not set; cannot compute fingerprint.")
    return hashlib.sha256(settings.encryption_key.encode()).hexdigest()
