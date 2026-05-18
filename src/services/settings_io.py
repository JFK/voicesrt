"""Settings export/import service.

Owns the ExportEnvelope schema contract (schema_version=1) and the two-stage
import protocol (preview + apply). HTTP-agnostic — callers are responsible
for committing the AsyncSession.

Envelope shape (schema_version=1):

    {
        "schema_version": 1,
        "exported_at": "<UTC ISO-8601>",
        "source_fingerprint": "<SHA-256 hex of ENCRYPTION_KEY>",
        "settings": [{"key": str, "value": str, "encrypted": bool}, ...]
    }

The `_meta.*` namespace is filtered out on both export and import:

- Export: `_meta.encryption_key_fingerprint` would just round-trip a redundant
  copy of `source_fingerprint`. Skipping the namespace keeps the envelope small
  and makes the source-fingerprint check the single point of truth.
- Import: the destination's `_meta.encryption_key_fingerprint` is owned by the
  destination's save_key flow and must NOT be overwritten — that row is the
  rotation-detection signal for the destination instance.

The `encrypted` flag on import is derived from the key prefix
(`crypto.ENCRYPTED_KEY_PREFIXES`), not trusted from the envelope. This mirrors
`_upsert_setting`'s invariant and prevents a tampered envelope from storing an
api_key value as plaintext.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.errors import (
    export_fingerprint_missing,
    import_fingerprint_mismatch,
    import_schema_unsupported,
)
from src.models import Setting
from src.services.crypto import ENCRYPTED_KEY_PREFIXES, META_KEY_PREFIX, EncryptionService

SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1})


def _should_be_encrypted(key: str) -> bool:
    return any(key.startswith(prefix) for prefix in ENCRYPTED_KEY_PREFIXES)


async def export_settings_envelope(session: AsyncSession) -> dict[str, Any]:
    """Return a schema_version=1 envelope of all non-`_meta.*` Setting rows.

    Encrypted rows export their stored ciphertext as-is (no decrypt step) —
    the envelope is portable only to instances running the same ENCRYPTION_KEY,
    enforced via `source_fingerprint` on import.
    """
    try:
        source_fingerprint = EncryptionService.get_fingerprint()
    except RuntimeError as e:
        raise export_fingerprint_missing() from e

    result = await session.execute(
        select(Setting).where(~Setting.key.like(f"{META_KEY_PREFIX}%")).order_by(Setting.key)
    )
    rows = [{"key": s.key, "value": s.value, "encrypted": s.encrypted} for s in result.scalars()]
    return {
        "schema_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "source_fingerprint": source_fingerprint,
        "settings": rows,
    }


def _validate_envelope(envelope: dict[str, Any]) -> None:
    """Raise AppError on schema/fingerprint mismatch; no DB access."""
    version = envelope.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise import_schema_unsupported(version)

    source_fp = envelope.get("source_fingerprint")
    if not isinstance(source_fp, str) or not source_fp:
        raise import_schema_unsupported(version)

    current_fp = EncryptionService.get_fingerprint()
    if source_fp != current_fp:
        raise import_fingerprint_mismatch(source_fp, current_fp)


def _filter_importable_rows(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    """Return envelope rows minus `_meta.*` entries; defensive against malformed exports."""
    raw = envelope.get("settings", [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        key = row.get("key")
        if not isinstance(key, str) or not key:
            continue
        if key.startswith(META_KEY_PREFIX):
            continue
        if not isinstance(row.get("value"), str):
            continue
        out.append(row)
    return out


async def preview_import_envelope(session: AsyncSession, envelope: dict[str, Any]) -> dict[str, Any]:
    """Validate envelope and return a row-count preview WITHOUT writing to DB."""
    _validate_envelope(envelope)
    rows = _filter_importable_rows(envelope)

    existing_keys: set[str] = set()
    result = await session.execute(select(Setting.key).where(~Setting.key.like(f"{META_KEY_PREFIX}%")))
    for key in result.scalars():
        existing_keys.add(key)

    encrypted_count = sum(1 for r in rows if _should_be_encrypted(r["key"]))
    overwrite_count = sum(1 for r in rows if r["key"] in existing_keys)
    return {
        "schema_version": envelope["schema_version"],
        "source_fingerprint": envelope["source_fingerprint"],
        "rows_total": len(rows),
        "rows_encrypted": encrypted_count,
        "rows_plaintext": len(rows) - encrypted_count,
        "rows_overwrite": overwrite_count,
        "rows_new": len(rows) - overwrite_count,
        "keys": sorted(r["key"] for r in rows),
    }


async def apply_import_envelope(session: AsyncSession, envelope: dict[str, Any]) -> dict[str, Any]:
    """Upsert all non-`_meta.*` rows from the envelope. Caller MUST commit.

    The `encrypted` flag on each written row is derived from the key prefix
    via `_should_be_encrypted` — the envelope's flag is informational only.
    This keeps the invariant `_upsert_setting` enforces (encrypted iff
    prefix matches `ENCRYPTED_KEY_PREFIXES`) tamper-resistant.
    """
    _validate_envelope(envelope)
    rows = _filter_importable_rows(envelope)

    # Narrow the SELECT to only the keys we'll touch — otherwise a tiny
    # envelope still drags every plaintext setting (glossary, pricing,
    # refine prompts, etc.) into memory for the existence check.
    keys_in_envelope = [row["key"] for row in rows]
    if keys_in_envelope:
        existing_result = await session.execute(select(Setting).where(Setting.key.in_(keys_in_envelope)))
        existing_by_key: dict[str, Setting] = {s.key: s for s in existing_result.scalars()}
    else:
        existing_by_key = {}

    now = datetime.now(UTC)
    overwritten = 0
    new = 0
    for row in rows:
        key = row["key"]
        value = row["value"]
        encrypted = _should_be_encrypted(key)
        existing = existing_by_key.get(key)
        if existing is not None:
            existing.value = value
            existing.encrypted = encrypted
            existing.updated_at = now
            overwritten += 1
        else:
            session.add(Setting(key=key, value=value, encrypted=encrypted, updated_at=now))
            new += 1

    return {
        "imported": overwritten + new,
        "overwritten": overwritten,
        "new": new,
    }
