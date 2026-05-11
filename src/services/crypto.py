import hashlib
from datetime import UTC, datetime

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings

# Setting.key prefixes whose rows must be stored encrypted.
# _upsert_setting derives the `encrypted` flag from this set when the
# caller does not pass one explicitly — see src/api/settings.py.
# Adding a new prefix here is the only step needed to make a new
# Setting namespace encrypted-by-default.
ENCRYPTED_KEY_PREFIXES: frozenset[str] = frozenset({"api_key."})

# Setting.key used as the storage slot for the active ENCRYPTION_KEY fingerprint.
# Stored at save time and compared on read to detect rotation without trying
# (and failing) to decrypt every row.
ENCRYPTION_KEY_FINGERPRINT_SETTING = "_meta.encryption_key_fingerprint"


class DecryptionError(RuntimeError):
    """Stored value cannot be decrypted — encryption key was rotated or replaced."""


class EncryptionService:
    """ENCRYPTION_KEY-bound operations consolidated into one place.

    Stateless cryptographic primitives are exposed as @staticmethod so
    callers that do not need a DB session can use them directly. The
    DB-aware helpers (`get_stored_fingerprint`, `all_api_keys_decrypt`,
    `api_key_status`, `validate_stored_keys`, `reencrypt_all`) are
    instance methods bound to the AsyncSession passed at construction —
    that keeps the call sites lock-step with FastAPI's request-scoped
    session lifecycle.

    Module-level shims (`encrypt`, `decrypt`, `decrypt_credential`,
    `get_fingerprint`) below preserve the pre-refactor import surface so
    existing callers and tests do not need to migrate in one step.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _get_fernet() -> Fernet:
        if not settings.encryption_key:
            raise RuntimeError(
                "ENCRYPTION_KEY is not set. Generate one with: "
                'python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            )
        return Fernet(settings.encryption_key.encode())

    @staticmethod
    def encrypt(plaintext: str) -> str:
        return EncryptionService._get_fernet().encrypt(plaintext.encode()).decode()

    @staticmethod
    def decrypt(ciphertext: str) -> str:
        return EncryptionService._get_fernet().decrypt(ciphertext.encode()).decode()

    @staticmethod
    def decrypt_credential(ciphertext: str) -> str:
        """Decrypt a stored credential.

        Raises DecryptionError if ENCRYPTION_KEY has changed since the
        value was encrypted, so callers can surface a user-friendly
        recovery message instead of crashing with a raw InvalidToken.
        """
        try:
            return EncryptionService.decrypt(ciphertext)
        except InvalidToken:
            raise DecryptionError(
                "Encryption key has changed. Please re-enter your API key in Settings → API Keys."
            ) from None

    @staticmethod
    def get_fingerprint() -> str:
        """SHA-256 hex of the ENCRYPTION_KEY string's UTF-8 bytes.

        Fernet keys are base64-encoded text; we hash that text directly
        rather than base64-decoding it first — the fingerprint is only an
        identity check, not a cryptographic transform of the underlying
        key material, so hashing the canonical string form is sufficient
        and avoids a decode step.

        Raises RuntimeError when ENCRYPTION_KEY is unset so callers do
        not silently store an empty fingerprint and mask the misconfig.
        """
        if not settings.encryption_key:
            raise RuntimeError("ENCRYPTION_KEY is not set; cannot compute fingerprint.")
        return hashlib.sha256(settings.encryption_key.encode()).hexdigest()

    async def get_stored_fingerprint(self) -> str | None:
        """Return the ENCRYPTION_KEY fingerprint persisted at the last save_key call.

        None means "never stamped" (legacy / fresh install) — callers
        must treat None as 'unknown', NOT as 'mismatch', so existing
        users without a stamped fingerprint don't see a false rotation
        warning until they next save a key.
        """
        from src.models import Setting

        result = await self.session.execute(select(Setting).where(Setting.key == ENCRYPTION_KEY_FINGERPRINT_SETTING))
        setting = result.scalar_one_or_none()
        return setting.value if setting else None

    async def _iter_encrypted_api_key_rows(self):
        """Yield every encrypted api_key.% Setting row for the active session.

        Single source of truth for the SQL filter used by every
        decrypt-scanning method below — change the predicate here and all
        scanners adjust, instead of relying on four `Setting.key.like(...)`
        literals staying in sync.
        """
        from src.models import Setting

        result = await self.session.execute(
            select(Setting).where(Setting.key.like("api_key.%"), Setting.encrypted.is_(True))
        )
        for row in result.scalars():
            yield row

    async def all_api_keys_decrypt(self) -> bool:
        """True iff every encrypted api_key.% row decrypts under the active key.

        Gates the fingerprint stamp in save_key: stamping unconditionally
        would silently lose the rotation signal during partial recovery.
        """
        async for row in self._iter_encrypted_api_key_rows():
            try:
                EncryptionService.decrypt_credential(row.value)
            except DecryptionError:
                return False
        return True

    async def api_key_status(self) -> tuple[bool, bool]:
        """Return (has_decryptable, has_undecryptable) for stored api_key.% rows.

        A row is "undecryptable" when DecryptionError is raised — typically
        because ENCRYPTION_KEY was changed after the row was written. Both
        flags surface so callers can distinguish "no keys at all" from
        "keys exist but the active ENCRYPTION_KEY can't decrypt them" — the
        latter needs a user-visible warning, not a silent /setup redirect
        followed by a later crash in transcribe._get_credential().

        Deliberately does not catch RuntimeError. _get_fernet() raises
        RuntimeError when ENCRYPTION_KEY is unset, which is a server
        misconfiguration — not a data-state recovery scenario. Letting it
        propagate fails fast and signals "fix the env var" rather than
        misdirecting the user to a recovery banner they cannot act on.
        """
        has_decryptable = False
        has_undecryptable = False
        async for row in self._iter_encrypted_api_key_rows():
            # Fernet decrypt does signature verification — stop as soon as
            # both flags are set so request-path callers (landing, upload)
            # don't burn cycles on every additional row when the answer is
            # already decided.
            if has_decryptable and has_undecryptable:
                break
            try:
                EncryptionService.decrypt_credential(row.value)
                has_decryptable = True
            except DecryptionError:
                has_undecryptable = True
        return has_decryptable, has_undecryptable

    async def validate_stored_keys(self) -> dict[str, bool]:
        """Per-row decrypt status for every encrypted api_key.% row.

        Returned mapping is {Setting.key: True if decrypts else False}.
        Diagnostic helper — endpoints can use it to render granular
        per-provider status instead of the binary all-or-nothing signal
        that all_api_keys_decrypt returns.
        """
        status: dict[str, bool] = {}
        async for row in self._iter_encrypted_api_key_rows():
            try:
                EncryptionService.decrypt_credential(row.value)
                status[row.key] = True
            except DecryptionError:
                status[row.key] = False
        return status

    async def reencrypt_all(self, old_key: str, new_key: str) -> dict:
        """Re-encrypt every api_key.% row from old_key to new_key.

        Mutates the rows in the current session but does NOT commit — the
        caller owns the transaction so it can roll back on partial
        failure if it chooses to. The fingerprint row is updated to the
        new key's fingerprint inline so the active fingerprint moves
        atomically with the row mutations on the caller's commit.

        Returns {"success": N, "failed": N, "errors": [Setting.key, ...]}.
        Rows that fail to decrypt under old_key are skipped (their value
        is left as-is); the caller decides whether to abort or proceed
        based on the report.

        Fingerprint stamping is gated on `failed == 0` for the same
        reason save_key gates on `all_api_keys_decrypt`: if we advanced
        the fingerprint while undecryptable rows remained, list_keys
        would stop emitting `key_mismatch` against them — the rotation
        banner would disappear from the Settings page even though the
        rotation is genuinely incomplete. Leaving the fingerprint stale
        keeps the rotation signal visible for the residual rows until
        the operator clears them manually (or supplies a key under which
        they decrypt).

        Transaction contract — DO NOT MIX with _upsert_setting in the
        same transaction. This method handles the fingerprint row with a
        direct ORM mutation / session.add() so it aligns with the row
        mutation pattern above. Calling _upsert_setting in the same
        transaction would issue a second concurrent UPSERT for the same
        key and confuse SQLAlchemy's identity map. Endpoints that wrap
        reencrypt_all should commit on the same session immediately and
        not stack other Setting writes before that commit.
        """
        from src.models import Setting

        old_fernet = Fernet(old_key.encode())
        new_fernet = Fernet(new_key.encode())

        success = 0
        failed = 0
        errors: list[str] = []
        async for row in self._iter_encrypted_api_key_rows():
            try:
                plaintext = old_fernet.decrypt(row.value.encode())
            except InvalidToken:
                failed += 1
                errors.append(row.key)
                continue
            row.value = new_fernet.encrypt(plaintext).decode()
            row.updated_at = datetime.now(UTC)
            success += 1

        # Only stamp the new fingerprint when the rotation is fully complete.
        # See docstring for why partial-success cases must leave it stale.
        if failed == 0:
            new_fingerprint = hashlib.sha256(new_key.encode()).hexdigest()
            fp_result = await self.session.execute(
                select(Setting).where(Setting.key == ENCRYPTION_KEY_FINGERPRINT_SETTING)
            )
            fp_row = fp_result.scalar_one_or_none()
            if fp_row is not None:
                fp_row.value = new_fingerprint
                fp_row.updated_at = datetime.now(UTC)
            else:
                self.session.add(
                    Setting(key=ENCRYPTION_KEY_FINGERPRINT_SETTING, value=new_fingerprint, encrypted=False)
                )

        return {"success": success, "failed": failed, "errors": errors}


# Backward-compatibility shims for the pre-refactor module-level API.
# New callers should use EncryptionService directly; these wrappers keep
# the existing `from src.services.crypto import encrypt, decrypt, ...`
# imports working so the refactor stays scoped to one PR.


def encrypt(plaintext: str) -> str:
    return EncryptionService.encrypt(plaintext)


def decrypt(ciphertext: str) -> str:
    return EncryptionService.decrypt(ciphertext)


def decrypt_credential(ciphertext: str) -> str:
    return EncryptionService.decrypt_credential(ciphertext)


def get_fingerprint() -> str:
    return EncryptionService.get_fingerprint()
