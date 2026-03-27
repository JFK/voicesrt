# Architecture

## System Overview

```
┌─────────────────────────────────────────────┐
│  Browser (HTMX + Alpine.js + Tailwind CSS)  │
└──────────────────┬──────────────────────────┘
                   │ HTTP
┌──────────────────▼──────────────────────────┐
│  FastAPI (Python 3.11+, async/await)        │
│  ├── API Routes (/api/jobs, /api/settings)  │
│  ├── Page Routes (/, /history, /srt, /meta) │
│  ├── Jinja2 Templates (SSR + i18n)          │
│  └── Background Tasks                       │
│       ├── ffmpeg (audio extraction/chunking) │
│       ├── Whisper / Gemini (transcription)   │
│       ├── LLM Refine + Verify               │
│       └── LLM Metadata / Quiz / Catchphrase │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│  SQLite (async via aiosqlite)               │
│  ├── Job          (transcription jobs)      │
│  ├── Setting      (API keys, config)        │
│  └── CostLog      (API cost tracking)       │
└─────────────────────────────────────────────┘
```

## Processing Pipeline

```
Upload → Extract Audio → Transcribe → [Refine] → [Verify] → Save SRT → [Metadata]
         (ffmpeg)        (Whisper/     (LLM 3     (LLM        (file)     (LLM)
                          Gemini)       modes)     full-text)
```

Each step updates `Job.status`:
`pending` → `extracting` → `transcribing` → `refining` → `verifying` → `completed`

Failures at refine/verify/metadata are non-fatal: the SRT is still saved.

## Key Design Decisions

### Frontend: HTMX + Alpine.js (No Build Step)

No React/Vue/webpack. The entire frontend is server-rendered HTML with:
- **HTMX**: Partial page updates, status polling, delete actions
- **Alpine.js**: Client-side state (forms, modals, editor)
- **Tailwind CSS**: Utility-first styling via CDN

This eliminates the build step entirely. All JS/CSS is loaded from CDNs.

### Database: SQLite

Single-user tool, so SQLite is sufficient. Data persists via Docker volume mount (`./data:/app/data`). Alembic migrations run automatically on startup via `start.sh`.

### Provider Abstraction

Whisper and Gemini have different APIs but are abstracted behind a common interface in `transcribe.py`. The provider is selected per-job, and all downstream processing (refine, verify, metadata) uses the same provider's LLM.

### Audio Chunking

Large audio files are split into 10-minute chunks before transcription:
- **Whisper**: 25MB file size limit requires chunking
- **Gemini**: No hard limit but single requests on long audio cause timeouts

Chunks are processed sequentially with timestamp offset accumulation.

### Async Architecture

- FastAPI's `BackgroundTasks` for job processing (non-blocking uploads)
- `asyncio.to_thread` wraps synchronous SDK calls (Gemini, file uploads)
- `asyncio.wait_for` adds timeouts to prevent hanging (10-min for Gemini)
- `asyncio.create_subprocess_exec` for ffmpeg operations

### Security

- API keys encrypted with Fernet symmetric encryption before DB storage
- Filenames sanitized with regex to prevent path traversal
- PreToolUse hooks block `.env` modifications, detect hardcoded secrets and SQL injection

## Directory Structure

```
src/
├── main.py              # FastAPI app, lifespan hooks
├── config.py            # Pydantic Settings (env vars)
├── constants.py         # Status enums, provider key mapping
├── database.py          # SQLAlchemy engine, session, migrations
├── templating.py        # Jinja2 config, i18n translation loader
├── models/
│   ├── job.py           # Job ORM (transcription state + results)
│   ├── setting.py       # Key-value settings (encrypted flag)
│   └── cost_log.py      # Per-operation cost records
├── services/
│   ├── transcribe.py    # Pipeline orchestrator
│   ├── audio.py         # ffmpeg: extract, split, duration
│   ├── whisper.py       # OpenAI Whisper API client
│   ├── gemini.py        # Google Gemini API client
│   ├── refine.py        # LLM post-processing (3 modes + verify + suggest)
│   ├── srt.py           # SRT parse/generate/save
│   ├── metadata.py      # YouTube metadata + prompt optimization
│   ├── catchphrase.py   # Thumbnail text generation
│   ├── quiz.py          # Quiz question generation
│   ├── cost.py          # Pricing DB, cost estimation, logging
│   ├── crypto.py        # Fernet encrypt/decrypt
│   └── utils.py         # JSON repair, token extraction
├── api/
│   ├── pages.py         # HTML page routes
│   ├── jobs.py          # Job CRUD, generate-meta, suggest, quiz, catchphrase
│   ├── settings.py      # API keys, models, glossary, pricing, tone refs
│   └── costs.py         # Cost dashboard data
├── i18n/
│   ├── en.json          # English translations
│   └── ja.json          # Japanese translations
└── templates/           # Jinja2 HTML templates
    ├── base.html
    ├── upload.html
    ├── history.html
    ├── srt_editor.html
    ├── meta_editor.html
    ├── settings.html
    ├── costs.html
    └── partials/
        └── job_status.html
```

## Data Model

### Job
| Field | Type | Description |
|---|---|---|
| id | UUID | Primary key |
| filename | String | Sanitized upload filename |
| status | String | Pipeline state (pending → completed/failed) |
| provider | String | "whisper" or "gemini" |
| language | String? | Language hint (ja, en, zh, ko) |
| srt_path | String? | Path to generated SRT file |
| youtube_title | String? | Generated metadata |
| youtube_description | String? | Generated description with chapters |
| youtube_tags | JSON String? | Tag array |
| catchphrases | JSON String? | Cached catchphrase results |
| quiz | JSON String? | Cached quiz results |
| enable_refine | Boolean | LLM post-processing enabled |
| refine_mode | String? | verbatim / standard / caption |
| enable_verify | Boolean | Full-text verification enabled |
| glossary | String? | Per-job glossary terms |
| audio_duration | Float? | Duration in seconds |
| error_message | String? | Error details (non-fatal errors) |

### Setting
| Field | Type | Description |
|---|---|---|
| key | String | Setting identifier (e.g., `api_key.openai`) |
| value | String | Value (encrypted if `encrypted=True`) |
| encrypted | Boolean | Whether value is Fernet-encrypted |

### CostLog
| Field | Type | Description |
|---|---|---|
| job_id | String | Associated job |
| provider | String | openai / gemini / whisper |
| model | String | Model name |
| operation | String | transcription / refinement / metadata_generation / etc. |
| input_tokens | Integer? | Input token count |
| output_tokens | Integer? | Output token count |
| estimated_cost | Float | USD cost estimate |
