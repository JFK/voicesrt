# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
