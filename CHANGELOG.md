# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
