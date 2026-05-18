# Backup and Recovery

VoiceSRT encrypts every stored API key with the Fernet key in your
`.env`'s `ENCRYPTION_KEY` variable. If that value is lost or changed
without re-encrypting the database, every stored key becomes
permanently unreadable. This document covers the three flows that keep
that from happening: **backup**, **restore**, and **key rotation**.

## TL;DR

1. **Back up `ENCRYPTION_KEY`** to a password manager or sealed offline
   storage the moment you generate it.
2. **Export settings** periodically from `Settings → Backup & Recovery`
   — the export file is small JSON, easy to commit to a private secrets
   vault.
3. **Snapshot the `data/` volume** (Docker or host filesystem) on the
   same cadence as your other backups. The exported JSON covers the
   `settings` table, not the SQLite job history.

## What is and isn't recoverable

| Asset | Survives `ENCRYPTION_KEY` loss? | Notes |
|---|---|---|
| `data/db/voicesrt.db` plaintext rows (`jobs`, `cost_logs`, model prefs, glossary, pricing, refine prompts, tone references) | Yes | Stored unencrypted; readable as long as the DB file is intact |
| `data/db/voicesrt.db` encrypted rows (`api_key.*`) | **No** | Fernet ciphertext — unreadable without the original `ENCRYPTION_KEY` |
| `data/uploads/`, `data/audio/`, `data/srt/`, `data/peaks/` | Yes | No encryption; transcription output and source files are recoverable from disk |

Bottom line: the **only** disaster scenario that destroys data
permanently is losing `ENCRYPTION_KEY` itself (or rotating it without
following the procedure below). The exported settings file lets you
move encrypted rows between instances **only** if both instances share
the same `ENCRYPTION_KEY`.

## Settings export

`Settings → Backup & Recovery → Export settings` downloads a JSON file
containing every non-internal `Setting` row. Internal metadata rows
(`_meta.*` namespace, including the fingerprint stamp) are excluded
because they are owned by the destination instance.

The envelope shape is:

```json
{
  "schema_version": 1,
  "exported_at": "2026-05-19T00:00:00+00:00",
  "source_fingerprint": "<SHA-256 of source ENCRYPTION_KEY>",
  "settings": [
    {"key": "api_key.openai", "value": "<ciphertext>", "encrypted": true},
    {"key": "glossary", "value": "...", "encrypted": false}
  ]
}
```

Encrypted rows are exported **as ciphertext** — the export file does
not contain plaintext API keys. The file is only useful on an instance
running the same `ENCRYPTION_KEY` (enforced by the `source_fingerprint`
check on import).

## Settings import

`Settings → Backup & Recovery → Import settings` accepts a JSON file
produced by Export. The flow is two-stage:

1. **Preview**: file is parsed, schema and `source_fingerprint` are
   validated, and a summary is shown (`N settings, M encrypted, K
   plaintext, X would overwrite`). No DB writes yet.
2. **Confirm**: clicking the confirm action writes every row. Existing
   rows are overwritten; new rows are inserted. `_meta.*` rows are
   skipped defensively.

If the export's `source_fingerprint` does not match the current
instance's `ENCRYPTION_KEY` fingerprint, the preview step fails with
`IMPORT_FINGERPRINT_MISMATCH`. Restore the original `ENCRYPTION_KEY` in
`.env` before importing, or import on the source instance.

## Key rotation

`Settings → Backup & Recovery → Rotate Encryption Key` re-encrypts
every stored API key under a new `ENCRYPTION_KEY`. The flow:

1. Generate a new Fernet key:

       python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

2. **Back up the current `.env`** (or at least the current
   `ENCRYPTION_KEY` value) somewhere you can recover it from.
3. Enter the **current** key (proof of possession) and the **new** key
   in the rotation form. Click `Rotate key` and confirm.
4. On success, the response instructs you to:
   - Open `.env`
   - Replace `ENCRYPTION_KEY=<old>` with `ENCRYPTION_KEY=<new>`
   - Restart the app

The rotation does NOT rewrite `.env` automatically. This is
intentional: Docker bind mounts and host file permissions vary, and a
silent file rewrite there has bitten production deployments before. The
DB rows are re-encrypted in a single transaction; the new
`_meta.encryption_key_fingerprint` is stamped only when **every**
encrypted row was successfully re-encrypted.

### What happens on partial failure

If any row fails to decrypt under the old key (e.g., it was previously
encrypted under a different `ENCRYPTION_KEY` and never recovered), the
rotation aborts:

- The transaction is rolled back — no row values change.
- The stored fingerprint stays at the **old** value, so the existing
  rotation banner on the Settings page stays visible.
- Response carries `ROTATION_PARTIAL_FAILURE` with the list of
  un-decryptable keys.

Recovery: re-enter the affected keys via `Settings → API Keys`. Each
successful save under the active key will gradually clear the rotation
banner; once every key decrypts cleanly, you can rotate again.

## `data/` volume backup (Docker)

If you run VoiceSRT via the Docker image, the SQLite database, audio
files, and waveform caches all live in the bind-mounted `data/`
directory. A simple periodic backup:

```bash
# Stop the app to ensure a consistent SQLite snapshot
docker compose stop voicesrt

# Snapshot the data volume
tar czf voicesrt-data-$(date +%Y%m%d).tar.gz data/

# Restart
docker compose start voicesrt
```

For zero-downtime backups, use `sqlite3 data/db/voicesrt.db ".backup
data/db/voicesrt.db.bak"` while the app is running, then archive the
`.bak` file plus the rest of `data/`. The `.env`'s `ENCRYPTION_KEY`
**must** be backed up separately — without it, the `data/` archive is
unreadable for the encrypted rows.

## Error codes reference

| Code | Where | What it means |
|---|---|---|
| `ROTATION_WRONG_KEY` | `POST /api/settings/rotate-key` | The current-key field does not hash to the stored fingerprint. Verify you entered the correct existing `ENCRYPTION_KEY`. |
| `ROTATION_INVALID_NEW_KEY` | `POST /api/settings/rotate-key` | The new-key field is not a valid Fernet key. Generate one with the Python one-liner above. |
| `ROTATION_PARTIAL_FAILURE` | `POST /api/settings/rotate-key` | One or more rows failed to decrypt under the current key. Re-enter those keys, then retry. |
| `IMPORT_FINGERPRINT_MISMATCH` | `POST /api/settings/import/*` | Export was made under a different `ENCRYPTION_KEY` than the current instance. |
| `IMPORT_SCHEMA_UNSUPPORTED` | `POST /api/settings/import/*` | Export file's `schema_version` is not supported by this app version. |
