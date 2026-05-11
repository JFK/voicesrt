---
description: API keys and secrets must be stored encrypted in DB via EncryptionService. Never store plaintext secrets.
---

# Encrypted Settings Rule

## Pattern
1. User enters API key in Settings page
2. Backend encrypts with `EncryptionService.encrypt()` (Fernet) before DB write
3. On use, `EncryptionService.decrypt_credential()` just before API call
4. Never log or return decrypted keys in responses

`EncryptionService` lives in `src/services/crypto.py`. Stateless primitives
(`encrypt`, `decrypt`, `decrypt_credential`, `get_fingerprint`) are
`@staticmethod`; DB-aware helpers (`get_stored_fingerprint`,
`all_api_keys_decrypt`, `validate_stored_keys`, `api_key_status`,
`reencrypt_all`) are instance methods bound to an `AsyncSession` at
construction. Module-level shims (`encrypt`, `decrypt`,
`decrypt_credential`, `get_fingerprint`) exist as backward-compatibility
wrappers — new code should prefer the class form.

## Setting key namespaces

The `Setting` table holds three logical categories distinguished only by
the key's prefix:

| Prefix | `encrypted` | Examples |
|---|---|---|
| `api_key.<provider>` | `True` | `api_key.openai`, `api_key.google` |
| `_meta.*` (reserved) | `False` | `_meta.encryption_key_fingerprint` |
| Everything else (model, glossary, pricing, etc.) | `False` | `model.openai`, `glossary`, `pricing`, `general.*` |

`crypto.ENCRYPTED_KEY_PREFIXES` is the **canonical declaration** of which
prefixes are sensitive. To add a new encrypted-by-default namespace,
extend `ENCRYPTED_KEY_PREFIXES` — do **not** rely on each call site
remembering to pass `encrypted=True`.

`_meta.*` is the reserved namespace for app-internal metadata that needs
to live in the `Setting` table (so we avoid Alembic migrations for
additive metadata) but is intentionally plaintext: hashes, schema
versions, and similar identity-check values.

## `_upsert_setting` contract

`src/api/settings.py:_upsert_setting(session, key, value, encrypted=None)`:

- `encrypted=None` (default): the flag is derived from the key prefix
  against `ENCRYPTED_KEY_PREFIXES`. Callers should normally omit it.
- `encrypted=True/False` explicit: used as-is, **except** that
  `encrypted=False` for a key matching `ENCRYPTED_KEY_PREFIXES` raises
  `ValueError`. The prefix declaration is load-bearing; silently
  overriding it would defeat the safety net.

## Key management
- `ENCRYPTION_KEY` env var is the only secret in `.env`
- All other secrets go through the Settings → encrypted DB flow
- The active `ENCRYPTION_KEY` fingerprint is stamped to
  `_meta.encryption_key_fingerprint` on every successful `save_key` once
  all existing rows decrypt — rotation detection in `list_keys` reads it

## When adding new API integrations
- Store credentials via the existing `Setting` model (key-value, encrypted)
- Use the `api_key.<provider>` key shape so `ENCRYPTED_KEY_PREFIXES`
  classifies it automatically
- Never add new secrets to `.env` or hardcode in source
- Use `EncryptionService` (or the module-level shims) — do not create
  alternative encryption
