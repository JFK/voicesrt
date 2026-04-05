# VoiceSRT - Development Guide

## Project Overview

Web application that generates SRT subtitle files from video/audio files using AI transcription, with LLM post-processing, YouTube metadata/quiz generation.

**Supported formats**: MP4, MP3, WAV, MOV, AVI, MKV, M4A, FLAC, OGG, WebM

## Tech Stack

- **Backend**: FastAPI (Python 3.11+)
- **UI**: Jinja2 + HTMX + Alpine.js + Tailwind CSS (CDN)
- **DB**: SQLite (SQLAlchemy 2.0 async + aiosqlite)
- **Transcription**: OpenAI Whisper API / Google Gemini API
- **Metadata Generation**: OpenAI GPT / Google Gemini
- **Audio Processing**: ffmpeg
- **Deployment**: Docker (single container)

## Setup Instructions

When asked to set up this project, follow these steps:

### Prerequisites
- Python 3.11+
- ffmpeg (`apt-get install ffmpeg` or `brew install ffmpeg`)


### Steps

1. **Install dependencies**
   ```bash
   pip install -e ".[dev]"
   ```

2. **Generate encryption key and create .env**
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   Create `.env` file with:
   ```
   ENCRYPTION_KEY=<generated key>
   ```

3. **Start the dev server**
   ```bash
   uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
   ```

4. **Open http://localhost:8000** and configure API keys in Settings page

### Docker (recommended for WSL)

WSL環境ではDocker Desktopの利用を推奨します。ffmpegなどの依存がコンテナに含まれるため、ホスト側へのインストールが不要です。

```bash
cp .env.example .env
# Edit .env and set ENCRYPTION_KEY
docker compose up --build
```

ポートが使用中の場合は `HOST_PORT` で変更可能:
```bash
HOST_PORT=8001 docker compose up --build
```

## Directory Structure

```
src/
├── main.py          # FastAPI app, exception handlers
├── config.py        # pydantic-settings
├── constants.py     # Status enums, provider mapping
├── database.py      # SQLAlchemy
├── errors.py        # Structured error codes (AppError)
├── templating.py    # Jinja2 templates
├── models/          # ORM models (Job, Setting, CostLog)
├── services/        # Business logic
│   ├── audio.py     # ffmpeg audio extraction
│   ├── whisper.py   # OpenAI Whisper API
│   ├── gemini.py    # Google Gemini API
│   ├── transcribe.py # Orchestrator
│   ├── refine.py    # LLM post-processing (verbatim/standard/caption)
│   ├── srt.py       # SRT generation
│   ├── metadata.py  # YouTube metadata generation
│   ├── catchphrase.py # Thumbnail catchphrase generation
│   ├── quiz.py      # YouTube quiz generation
│   ├── crypto.py    # API key encryption
│   ├── cost.py      # Cost calculation
│   └── utils.py     # Shared utilities
├── api/             # API routers
│   ├── pages.py     # HTML pages
│   ├── jobs.py      # Job CRUD
│   ├── settings.py  # Settings management
│   └── costs.py     # Cost dashboard
├── i18n/            # Translations (en.json, ja.json)
└── templates/       # Jinja2 templates
```

## Coding Conventions

- **Python**: Type hints required, ruff for formatting/linting
- **Naming**: snake_case (functions/variables), PascalCase (classes)
- **Async**: Use async/await (SQLAlchemy async, asyncio subprocess)
- **Tests**: pytest + pytest-asyncio
- **Language**: Code and comments in English
- **Logging**: `logger = logging.getLogger(__name__)` per module
- **Timestamps**: `datetime.now(UTC)` — always UTC, never naive datetime
- **Paths**: `pathlib.Path` over string paths, `.glob()` for file discovery
- **Error handling**: Graceful degradation — non-fatal pipeline steps catch exceptions and continue
- **API errors**: Use `AppError` from `src/errors.py` — never raw `HTTPException`. Response format: `{"error": {"code": "ERROR_CODE", "message": "..."}}`
- **Temp files**: Always clean up in `finally` blocks
- **LLM responses**: Use `_repair_truncated_json()` (utils.py) for robustness

## Commit Messages

Conventional Commits format:

```
<type>(<scope>): <subject>

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

Type: feat, fix, refactor, test, docs, chore
Scope: api, service, ui, db, infra

## Database Migrations (Alembic)

Migrations run automatically on app startup. When changing models:

```bash
# Generate migration after model changes
alembic revision --autogenerate -m "description of change"

# Apply manually (also runs on startup)
alembic upgrade head

# Check current version
alembic current
```

## Testing

```bash
pytest                    # Run tests
pytest --cov              # Coverage
ruff check src/           # Lint
ruff format src/          # Format
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| ENCRYPTION_KEY | Fernet encryption key | Yes |

API keys are configured via the Settings page in the web UI (stored encrypted in DB).
