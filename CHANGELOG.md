# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.5] - 2026-05-19

**ENCRYPTION_KEY lifecycle completion** — rotation API + settings backup/recovery. Closes the disaster-recovery story opened by the encryption-batch family (v1.0.1–v1.0.4): operators can now rotate the `ENCRYPTION_KEY` without losing stored API keys, and back up / restore the full settings envelope without exposing plaintext credentials.

### Added
- **`POST /api/settings/rotate-encryption-key`** — re-encrypt every stored API key under a new `ENCRYPTION_KEY`. Proof-of-possession via fingerprint match (`compute_fingerprint(body.old_key) == stored_fingerprint`); partial-failure rollback leaves the rotation banner stale so residual undecryptable rows stay visible until each affected key is re-entered. `.env` update + restart is operator-driven — the response carries the instruction. (#85, closes #68)
- **`GET /api/settings/export`** — download a `schema_version=1` JSON envelope of all non-`_meta.*` Setting rows. Encrypted rows are exported as ciphertext (no plaintext credentials in the file). The envelope carries the source `ENCRYPTION_KEY` fingerprint so the import side can reject cross-key imports without trying to decrypt. (#85, closes #72)
- **`POST /api/settings/import/preview` + `POST /api/settings/import/apply`** — 2-stage flow. Preview validates schema + fingerprint and returns row counts without writing. Apply re-validates defensively (nothing structurally links it to preview) and upserts every non-`_meta.*` row. The `encrypted` flag on each row is derived from the key prefix via `_should_be_encrypted`, not trusted from the envelope — so a forged envelope with `encrypted=False` on an `api_key.*` row still lands as `encrypted=True`. (#85, closes #72)
- **First-run setup backup warning** — `/setup` page shows an amber banner until the `_meta.encryption_key_fingerprint` row is first stamped (via the first `save_key` call). Teaches operators to back up `ENCRYPTION_KEY` before they need disaster recovery. (#85)
- **`docs/backup-and-recovery.md`** — full operator procedure for export, import, and rotation, plus an error-code reference for the new `AppError` factories (`ROTATION_WRONG_KEY`, `ROTATION_INVALID_NEW_KEY`, `ROTATION_PARTIAL_FAILURE`, `EXPORT_FINGERPRINT_MISSING`, `IMPORT_FINGERPRINT_MISMATCH`, `IMPORT_FINGERPRINT_MISSING`, `IMPORT_SCHEMA_UNSUPPORTED`). README links to it. (#85)

### Changed
- **`compute_fingerprint(key)` is now the canonical SHA-256 helper** in `src/services/crypto.py`. `EncryptionService.get_fingerprint()` delegates to it. Endpoints and helpers that need to fingerprint a request-body key (e.g. rotation proof-of-possession) call this directly instead of inlining `hashlib.sha256(...)`. Single source of truth for the hashing strategy. (#85)
- **`META_KEY_PREFIX = "_meta."` promoted to `src/services/crypto.py`** as the canonical declaration of the reserved internal-metadata namespace. Removes stringly-typed `"_meta."` literals from `src/services/settings_io.py` and `tests/test_settings_io.py`. (#85)

### Tests
- **`tests/test_settings_io.py` (new)** — 19 service-layer unit tests covering envelope shape, schema versioning, fingerprint mismatch / missing / unset paths, `_meta.*` exclusion on both export and import, `encrypted` flag invariant on both INSERT and UPDATE branches, and full export-import round-trip. (#85)
- **`tests/test_settings_api.py` (+8)** — endpoint integration tests for rotate-key (POP correct / wrong / legacy / invalid Fernet format / partial-failure preserves stale fingerprint) and export/import (JSON download headers, preview counts, fingerprint-mismatch rejection, apply overwrites). (#85)

## [1.0.4] - 2026-05-19

**Encryption-key safety + external-API timeout hardening** — a cluster of fixes around ENCRYPTION_KEY mismatch detection, decrypt-error containment, and explicit timeouts on every OpenAI/Gemini call to satisfy the project's async-first rule. Also unblocks the SRT editor on jobs whose audio container reports media offsets, and unifies the glossary placeholder format.

### Fixed
- **API key validation no longer hangs the event loop** — `POST /api/settings/keys/{provider}/test` (Google branch) was calling `client.models.list()` synchronously inside an async route handler. Under concurrent "Test key" presses, the entire FastAPI loop blocked for the duration of the round-trip. The call is now routed through `call_gemini_with_timeout` with a 30-second budget. (#84, closes #74 / #75)
- **Indefinite hangs on OpenAI and Gemini API calls** — every external LLM call now has an explicit timeout. New `call_gemini_with_timeout` helper in `src/services/utils.py` wraps `asyncio.wait_for(asyncio.to_thread(...))` for the blocking google-genai SDK; `create_openai_compatible_client` now sets an `httpx.Timeout(600s, connect=10s)`. Cheap RPCs (file deletion, key validation) get a 30-second `SHORT_RPC_TIMEOUT_SEC` so a stuck lightweight call cannot stall job teardown for 10 minutes. (#84, closes #74 / #75)
- **Uploaded Gemini files no longer leak when transcription raises** — `transcribe_with_gemini` was running `client.files.delete` only on the success path; an exception from `generate_content` or `parse_json_response` skipped cleanup. Restructured into `try/finally` per the project's "always clean up in `finally` blocks" rule. (#84)
- **SRT editor audio drifts against subtitle timeline** — videos whose container had a non-zero edit-list offset (elst) reported a `start_time` in `ffprobe` but WaveSurfer played from `0`, so every subtitle ended up shifted. The editor now extracts the canonical audio track to a peaks-aligned source and threads the offset through the timeline. (#83, closes #73)
- **InvalidToken errors during decrypt no longer regenerate ENCRYPTION_KEY** — the recovery path used to silently mint a fresh Fernet key when `_get_credential()` hit `InvalidToken`, which then corrupted every other stored credential. Decrypt failures now propagate as `DecryptionError`; `EncryptionService.api_key_status` surfaces the mismatch in the UI so the operator can re-enter the affected keys. (#81, closes #67 / #76 — initial detection landed in #79 for #66 / #69)
- **`_has_api_keys()` can detect decrypt-failed rows** — previously it only checked whether the row existed, so a row with an undecryptable value still counted as "configured". Now uses `EncryptionService.all_api_keys_decrypt()` to require successful decryption. (#81, closes #76)
- **Glossary placeholder format unified to `reading:term`** — both UI and parser now expect `読み:漢字` ordering. The previous mixed `term:reading` / `reading:term` lookup silently dropped half the entries depending on the active locale. (#80, closes #77)

### Changed
- **Encryption logic consolidated into `EncryptionService`** — `src/services/crypto.py` now exposes a class that owns `encrypt` / `decrypt_credential` / fingerprint / `all_api_keys_decrypt` / `validate_stored_keys` / `api_key_status` / `reencrypt_all`. Module-level shims remain as backward-compat wrappers; new code should prefer the class. (#82, closes #70)
- **`ENCRYPTED_KEY_PREFIXES` is now the canonical declaration of sensitive settings** — `_upsert_setting` derives the `encrypted` flag from the key prefix by default, and raises `ValueError` if a caller explicitly tries to store an `api_key.*` value with `encrypted=False`. To add a new encrypted-by-default namespace, extend `ENCRYPTED_KEY_PREFIXES` rather than passing `encrypted=True` at every call site. (#82, closes #71)

### Added
- **Timeout policy constants** in `src/services/utils.py` — `OPENAI_TIMEOUT_SEC=600`, `OPENAI_CONNECT_TIMEOUT_SEC=10`, `GEMINI_TIMEOUT_SEC=600`, `SHORT_RPC_TIMEOUT_SEC=30`. (#84)
- **`tests/test_timeout.py`** — 10 unit tests covering the new helper, the OpenAI client timeout policy, the short-RPC budget, and timeout-firing behavior. (#84)
- **`httpx>=0.27.0,<1.0.0` to runtime dependencies** — promoted from `[project.optional-dependencies].dev` so production installs no longer rely on `openai`'s transitive `httpx` to satisfy our module-level import. (#84)

### CI
- **ffmpeg-mocked peak test cases** — `tests/test_peaks.py` now exercises a synthetic int16 PCM stream and zero-duration error path so the new `src/services/peaks.py` module stays above the project coverage gate even on CI runners without the ffmpeg binary. (5071f41, 4742963, 6a0762c)

## [1.0.3] - 2026-05-09

**SRT editor stability + metadata provider routing** — fixes a browser freeze on large media and a misrouted LLM call when picking a different provider for metadata than for transcription.

### Fixed
- **Browser tab freeze on large media** — opening the SRT editor on a multi-GB MP4 froze the tab because WaveSurfer's default `media: audio` path re-fetches the source URL and runs `decodeAudioData()` on the full audio track to compute the waveform. The editor now precomputes a small amplitude envelope server-side via ffmpeg (`/api/jobs/{id}/peaks`, ~50 KB JSON, ~1.4 s cold for a 1.65 GB / 28-min sample, cached under `data/peaks/`) and passes `peaks` + `duration` to WaveSurfer so the in-browser fetch+decode is skipped entirely.
- **Editor blocked while waveform loads** — `audioReady` previously required both `<audio>.canplay` and `wavesurfer.ready`, so a slow waveform held playback and editing hostage. Playback and editing now unlock as soon as `<audio>` fires `canplay`; only the waveform region stays gated on its own readiness.
- **Metadata generation routed to the wrong LLM when a provider override was set** — picking OpenAI for metadata on a Gemini-transcribed job (or vice versa) sent the override-provider's API key to the original-provider's SDK, surfacing as Google's `API_KEY_INVALID` even though the key was valid. `_run_metadata_generation` now threads the resolved provider through to both the LLM call and the cost log; the in-pipeline transcription path defaults to `job.provider` and is unchanged.

### Added
- **`src/services/peaks.py`** — memory-bounded ffmpeg-based peak extraction with per-job `asyncio.Lock` and on-disk cache.

## [1.0.2] - 2026-04-26

**Metadata generation reliability** — keep YouTube metadata aligned with the actual SRT and the JSON contract OpenAI requires.

### Fixed
- **OpenAI 400 `'messages' must contain the word 'json'`** — `METADATA_SYSTEM_PROMPT` (and preventively `REFINE_SYSTEM_PROMPT` / `VERIFY_SYSTEM_PROMPT`) now always include the keyword so a user-supplied custom prompt that omits it no longer breaks the request (#65)
- **Empty generation result with custom prompts** — append a JSON schema reminder after `custom_prompt` so responses always use the canonical English keys (`titles` / `description` / `tags` / `chapters`) regardless of the user's output-format spec (#65)
- **Generated metadata not reflecting the SRT** — `OPTIMIZE_PROMPT` now forbids the LLM from baking video-specific values (chapter timestamps, episode-only guests, dialogue excerpts) from `meta_context.notes` into the optimized template, treating it as a reusable channel-level template (#65)
- **Stale error message persisted after a successful retry** — clear `job.error_message` / `job.error_detail` at the start of metadata regeneration so the UI no longer surfaces past failures after a successful run (#65)

## [1.0.1] - 2026-04-22

**SRT editor stability** — data-loss race, state bleed, playback boundaries, and loading UX.

### Fixed
- **Save no longer silently drops edits during slow saves** — re-queue via `_saveDirty` + debounceSave (#63)
- **Segment DOM state stays anchored** — stable `_uid` keying on `x-for` so textarea focus, error badges, and suggestion dropdowns no longer bleed across neighbours after add/delete/merge (#63)
- **Waveform region DOM no longer stacks during playback** — diff-based rendering keyed on `_uid` with `setOptions` in-place updates (#63)
- **Segment preview pauses at the true audio boundary** — `_previewEnd` polled in `onTimeUpdate` handles rate changes, seeks, and startup jitter that setTimeout alone could not (#63)
- **Single-segment preview no longer yanks the viewport** — auto-scroll suppressed while previewing (#63)
- **Start-time `−` nudge no longer silently creates overlap** — `updateStart` rejects overlap with the previous segment and `start >= end`, mirrors `updateEnd`'s pattern (#63)
- **Rapid `+/−` feels responsive** — `renderRegions` coalesced via `requestAnimationFrame` (#63)
- **`[` / `]` keyboard shortcuts `preventDefault`** for consistency (#63)

### Changed
- **Default playback rate locked to 1x** — removed `localStorage` persistence so the select always starts at 1x (#63)
- **Loading UX** — `audioReady` now requires both audio `canplay` and wavesurfer `ready`; skeleton + `animate-pulse` + disabled buttons until both fire (#63)

### Added
- **Speaker-tag progress counter** on the speakers button — `X/Y` badge, amber while incomplete, emerald when every segment is tagged (#63)

## [1.0.0] - 2026-04-14

**Production Ready** — performance, robustness, observability, and mobile responsive.

### Added
- **Streaming SRT editor**: Append segments per chunk as transcription progresses — no more waiting for completion (#50)
- **Silence-aware chunk boundaries**: Audio splitting at silence gaps instead of fixed intervals for cleaner transcription (#49)
- **Mobile responsive layout**: Hamburger menu, responsive grids, hidden table columns, touch targets ≥44px across all pages (#24)

### Changed
- **LLM model pre-flight validation**: Validate model name before job submission to fail fast on typos or unavailable models (#53)
- **Raw API error preservation**: `error_detail` field now stores the original provider error for debugging (#54)
- **Error detail panel redesign**: Inline diagnostic console with design token alignment (#57)

### Closed (deferred)
- SRT Editor compact mode (#15) — deferred: revisit when users report segment overload
- Batch processing (#23) — deferred: too large for v1.0.0 scope, revisit in v1.1+

## [0.6.0] - 2026-04-07

**Visual & Discovery** — surface what the app does at a glance and make audio structure visible.

### Added
- **Landing page with persona-based use cases**: `/` now shows a hero, three persona cards (YouTubers, Meetings/Interviews, Subtitle Editors), a provider comparison table, and a "get started in 2 minutes" guide. Each persona deep-links to `/upload?persona=...` which pre-selects refine settings tuned for the use case (caption / verbatim / standard) and shows a hint banner. The upload form moved to `/upload`; bookmarked `/?job=xxx` URLs still work via a 307 redirect (#18)
- **Waveform visualization in the SRT editor**: Replace the thin progress bar with a wavesurfer.js v7 waveform that surfaces audio structure (silence vs speech, loudness peaks) at a glance. Each segment is overlaid as a clickable region tinted by its assigned speaker so the speaker palette in the dot/badge UI matches the waveform. Click-to-seek, dark mode color sync via `MutationObserver`, and full responsiveness (#20)
- **Playback speed control**: 0.5x–2x speed selector next to the play button in the SRT editor, persisted to `localStorage` under `voicesrt.playbackRate`. `playSegment` scales its stop timer by `playbackRate` so previewing a segment at 2x stops at the segment end instead of overshooting
- **Dark mode**: Class-based Tailwind dark mode toggle in the nav, persisted to `localStorage` and synced to `prefers-color-scheme` on first load. Pre-paint script avoids the flash of light content. Every template has explicit `dark:` variants for backgrounds, borders, text, and form controls (#22)
- **2-minute mp3 test fixture** at `tests/fixtures/test.mp3` for end-to-end transcription smoke tests against live providers
- **Playwright UI verification step** in `/self-review`: when `src/templates/`, `src/static/`, or `src/i18n/` change, the workflow now walks through launching a dev uvicorn on a non-conflicting port and using the Playwright MCP browser tools to verify rendering, Alpine state, and console errors

### Changed
- **Speaker palette unified**: `SPEAKER_COLORS` in `speaker-manager.js` now carries a `tint` field (RGBA) used for waveform regions, eliminating drift between badges, dots, borders, and waveform tints
- **Nav Upload link**: now points to `/upload` (logo still links home to the new landing page)

### Fixed
- **`speakerMap` reindexing on structural edits**: Pre-existing bug where `deleteSegment`, `addSegmentAfter`, and `mergeSelected` left `speakerMap` keyed to the old segment indices, silently miscoloring segment row borders. Exposed by waveform regions and fixed via a new `_remapSpeakers(remap)` helper on the speaker manager
- **Meta editor null `audio_duration` guard**: Prevents the cost panel from crashing on jobs that finished before duration tracking was added (#45)
- **Bookmarked `/?job=xxx` upload links**: 307-redirect to `/upload?job=xxx` so old bookmarks keep working after the landing-page move
- **Address bar / page mismatch in upload**: `history.replaceState` writes `/upload` and `/upload?job=...` instead of `/` and `/?job=...`, so the URL matches the served page and a refresh no longer hits the legacy redirect
- **`.mcp.json` gitignored**: prevents accidental commit of MCP bearer tokens

## [0.5.0] - 2026-04-06

### Added
- **Real-time job status via SSE**: New `GET /api/jobs/{id}/stream` endpoint with in-memory `JobStatusManager` pub/sub. Frontend `JobStatusClient` uses EventSource with auto-reconnect and polling fallback. Replaces `setInterval` polling on upload and metadata pages and fixes a memory leak in the meta editor (#29)
- **SRT editor keyboard shortcuts**: 12 power-user shortcuts (Arrow/Tab navigation, Space playback, `[`/`]` time nudge, `Ctrl+S/M/D/Enter` save/merge/delete/suggest, `?` help modal). Scope-aware so they don't hijack typing in textareas. Cross-platform (`Ctrl`/`Cmd`). Help modal with `role="dialog"` and ARIA labels (#19)

### Changed
- **SRT editor extracted into ES modules**: 377 lines of inline JS split into 6 modules under `src/static/js/srt-editor/` (`time-utils`, `audio-controller`, `segment-editor`, `speaker-manager`, `suggestion-manager`, `save-manager`, `keyboard-shortcuts`). Template reduced from 648 → 327 lines. Loaded via a new `head_scripts` block before Alpine to guarantee `srtEditor` is defined when Alpine processes `x-data` (#25)
- **Shared model-loader utility**: 4 duplicate `available-models` fetch implementations (settings, upload, meta-editor, history) replaced with a single `window.ModelLoader` IIFE that caches responses and dedupes concurrent requests (#28)
- **`onTimeUpdate` no-op guard**: Round audio current time to 0.1s and bail when unchanged — eliminates per-frame Alpine reactivity churn at 60Hz
- **`STATUS_VERIFYING` constant**: Added to `src/constants.py`; all transcribe pipeline status writes use the constants instead of raw strings

### Fixed
- **SRT editor empty-component race**: Inline ES modules executed after Alpine started, leaving `x-data="srtEditor()"` bound to an empty proxy. Module now loads before Alpine via the new `head_scripts` block — caught by Playwright verification, would have shipped a broken editor otherwise
- **SSE TOCTOU race**: Subscribers arriving between status check and queue registration hung for 30s on the keepalive timeout. `JobStatusManager` now caches the last terminal event (bounded LRU, 256 entries) so late subscribers receive completion immediately
- **SSE long-lived DB session**: `stream_job_status` no longer holds an `AsyncSession` for the lifetime of the stream; uses a short-lived session for the initial lookup
- **Polling fallback payload mismatch**: `JobStatusClient.handleData` normalizes `error_message` → `detail` so SSE and polling deliver the same shape
- **i18n HTML escaping**: SRT editor i18n strings now use `|tojson` instead of quoted Jinja expressions, preventing apostrophes (e.g. `segment's`) from rendering as `&#39;`
- **Keyboard shortcut case sensitivity**: Letter keys are normalized with `toLowerCase` so `Ctrl+S/M/D` work with Caps Lock or Shift held
- **Modal-open shortcut leakage**: Arrow/Tab/Space/bracket keys are blocked while the help modal is visible
- **Editable target detection**: Shortcuts now skip `BUTTON`, `SELECT`, `A`, and `contenteditable` elements — not just `TEXTAREA`/`INPUT` — to avoid hijacking native keyboard behavior

## [0.4.0] - 2026-04-06

### Added
- **Setup wizard**: First-time user onboarding — choose provider, enter API key, verify, start uploading (#14)
- **Toast notifications**: Actionable error messages with context-aware guidance and retry hints (#16)
- **Playwright E2E tests**: 5 browser-level smoke tests covering setup wizard, settings, upload, navigation, language switching (#21)
- **CI E2E job**: Separate GitHub Actions job with Chromium, screenshot artifacts on failure

### Changed
- **Structured error responses**: All API errors now return `{"error": {"code": "...", "message": "..."}}` via `AppError` — no more raw `HTTPException` (#27)
- **Test fixtures centralized**: Shared helpers (`create_test_job`, `segment_factory`, `mock_openai_response`) extracted to `tests/helpers.py` (#30)
- **E2E test isolation**: E2E tests use a temporary data directory, never touching the dev DB

### Documentation
- Architecture guide, user guide, troubleshooting guide, contributing guide (#31, #32, #33, #34)

## [0.3.0] - 2026-04-05

### Added
- **Ollama (Local LLM)**: Use local Ollama models for refine, metadata, catchphrase, quiz generation
- **SRT Editor — Speaker management**: Register speakers, assign per-segment, auto-coloring (8-color palette)
- **SRT Editor — Segment operations**: Merge, delete, add segments with time validation
- **SRT Editor — Time controls**: Editable timestamps, ±0.1s nudge buttons, end→next start auto-link
- **SRT Editor — Audio playback**: Player bar, click-to-play per segment, active segment highlighting
- **SRT Editor — Per-segment AI suggestions**: Glossary-aware, Qwen3 /no_think optimization
- **Speaker-filtered download**: Download SRT/VTT per speaker via split button dropdown
- **LLM model selector**: Choose provider + model on Upload, History (catchphrase/quiz), and Meta Editor pages
- **Multi-title generation**: Default prompt generates 2-3 title options with different angles
- **Available models API**: `GET /api/settings/available-models` with dynamic Ollama model listing
- **Job glossary API**: `PUT /api/jobs/{id}/glossary` for per-job glossary persistence
- **Speakers API**: `PUT /api/jobs/{id}/speakers` for speaker list and per-segment assignments
- **Media endpoint**: `GET /api/jobs/{id}/media` for audio playback in SRT Editor
- **Provider normalization**: Safe mapping of UI provider names to internal provider identifiers
- **Alembic migrations**: `speakers`, `speaker_map`, `model_override` columns
- **Codecov config**: Relaxed patch coverage target for UI-heavy changes
- 45 new tests (145 → 190 total)

### Changed
- Upload page: "Provider" renamed to "Transcription Engine", Ollama removed (STT only: Whisper/Gemini)
- Upload page: Post-processing model selector shown when refine is enabled
- Settings: LLM model section restructured — "Default Models" + "Refine Models (optional)"
- Settings: All model selectors changed to dropdowns (OpenAI, Gemini, Ollama)
- Settings: Ollama model section removed (consolidated into LLM Models)
- Settings: Page load parallelized (9 API calls via Promise.all)
- Settings: Tone reference labels clarified — "Past YouTube Posts" / "過去の投稿スタイル"
- Meta Editor: LLM selector moved to Prompt header (applies to Optimize and Generate)
- Meta Editor: Optimize with AI restyled as secondary button, grouped with Reset
- History: Meta preview button icon changed from ▶ to eye icon
- History: Model selector moved from page header into modal regenerate area
- SRT Editor: End time shrink no longer auto-syncs next segment's start
- Content-Disposition headers use RFC 5987 UTF-8 encoding for non-ASCII filenames
- README.md / README.ja.md fully rewritten with Ollama, SRT Editor, model selection features
- docs/api.md updated with all new endpoints

### Fixed
- Docker Ollama: Auto-resolve `localhost` → `host.docker.internal` in containers
- Ollama test button: Uses resolved URL in Docker environments
- Settings: `structuredClone` crash on Alpine.js proxy (caused all textareas blank)
- Settings: Dropdown values correctly selected after async load ($nextTick fix)
- Settings: Tone references anchor link now scrolls to correct section
- Translation: Preset/model save toast messages properly interpolate placeholders
- Meta Editor: Buttons disabled until model is selected
- LLM title output: Sanitize non-string/null elements in titles array
- Re-refine feature removed (replaced by per-segment AI suggestions)

## [0.2.0] - 2026-03-27

### Added
- VTT (WebVTT) export support: download as .vtt from history and SRT editor
- GitHub Actions CI pipeline (lint, format check, test with coverage)
- 63 new tests (82 → 145 total, coverage 43% → 57%)
- pytest-cov dependency for coverage reporting

### Changed
- CI badges added to README.md and README.ja.md (CI status, Python, License)

### Fixed
- CI: create data directories and run Alembic migrations before tests
- Ruff format applied to all source files for consistency

## [0.1.0] - 2026-03-27

Initial release.

### Added
- AI transcription with OpenAI Whisper API and Google Gemini API
- Multi-format support: MP4, MP3, WAV, MOV, AVI, MKV, M4A, FLAC, OGG, WebM
- LLM post-processing with 3 refine modes (Verbatim / Standard / Caption)
- Verify pass for full-text consistency check (proper nouns, place names, kanji)
- SRT editor with per-segment AI suggestions, auto-save, and verification highlights
- YouTube metadata generation (title, description with chapters, tags)
- Tone reference feature for consistent channel style
- Thumbnail catchphrase generation (5 suggestions with style classification)
- YouTube quiz generation (5 multiple-choice questions)
- Cost dashboard with per-provider, per-model, monthly tracking
- Glossary support (global + per-job) for proper noun accuracy
- Custom refine prompts per mode
- Model presets (Quality / Balanced / Budget)
- Internationalization (English / Japanese)
- Docker deployment (single container)
- Alembic database migrations (auto-run on startup)
- API key encryption (Fernet)
- Audio chunking for large files (Whisper 10-min chunks, Gemini 10-min chunks)
- Gemini API async with 10-min timeout to prevent hanging
