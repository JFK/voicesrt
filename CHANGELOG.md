# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
