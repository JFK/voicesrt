from cryptography.fernet import Fernet, InvalidToken

from src.config import settings


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
