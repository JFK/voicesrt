# VoiceSRT

[![CI](https://github.com/JFK/voicesrt/actions/workflows/ci.yml/badge.svg)](https://github.com/JFK/voicesrt/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[日本語](README.ja.md)

Generate SRT subtitles from audio/video with AI transcription, then refine, edit, and export — all in one place. Mobile-friendly, real-time streaming, and production-ready.

## Features

### Transcription
- **AI Transcription**: OpenAI Whisper API / Google Gemini API
- **Streaming Editor**: Segments appear in real-time as transcription progresses — no waiting for completion
- **Multi-format**: MP4, MP3, WAV, MOV, AVI, MKV, M4A, FLAC, OGG, WebM
- **Silence-aware Chunking**: Audio splits at silence gaps for cleaner segment boundaries
- **LLM Post-processing**: 3 refine modes (Verbatim / Standard / Caption) with glossary
- **Verify Pass**: Full-text consistency check for proper nouns and kanji
- **Ollama Support**: Use local LLM models (Qwen3, etc.) for post-processing

### SRT Editor
- **Inline Editing**: Edit text, timestamps, and segment structure in-browser
- **Waveform Visualization**: wavesurfer.js waveform with speaker-colored regions, click-to-seek
- **Speaker Management**: Register speakers, assign per segment, auto-coloring (8 colors)
- **Segment Operations**: Merge, delete, add segments with time overlap validation
- **Time Controls**: Editable timestamps with ±0.1s nudge buttons
- **Audio Playback**: Integrated player bar with speed control (0.5x–2x)
- **AI Suggestions**: Per-segment AI corrections using glossary (supports Ollama)
- **Speaker-filtered Export**: Download SRT/VTT for a specific speaker only
- **Keyboard Shortcuts**: 12 power-user shortcuts for navigation, playback, and editing

### YouTube Tools
- **Metadata**: SEO-optimized title, description with chapters, 15-25 tags
- **Tone Reference**: Match previous videos' writing style
- **Catchphrases**: 5 thumbnail text suggestions with style classification
- **Quiz**: 5 multiple-choice questions from video content

### Model Selection
- **Per-task model choice**: Select provider + model when generating (Upload, History, Meta Editor)
- **Settings defaults**: Configure default models per provider, with optional refine model override
- **Ollama integration**: Dropdown populated from local Ollama instance, auto-resolves Docker networking

### Management
- **Upload History**: Grouped actions, status indicators, inline modal preview
- **Cost Dashboard**: Track API costs by provider, model, month, and operation
- **Settings**: Encrypted API keys, model presets, glossary, refine prompts, pricing config
- **i18n**: English / Japanese
- **Mobile Responsive**: Hamburger menu, responsive grids, touch-friendly controls on all pages

## Quick Start

### Docker (Recommended)

```bash
git clone https://github.com/JFK/voicesrt.git
cd voicesrt
cp .env.example .env
# Set ENCRYPTION_KEY in .env
docker compose up --build
# Open http://localhost:8000 → Settings → Configure API keys
```

### Docker + Ollama (Local LLM)

```bash
# Start Ollama on host first: ollama serve
# Pull a model: ollama pull qwen3:8b
docker compose up --build
# Settings → Ollama Base URL: http://localhost:11434
# (Auto-resolved to host.docker.internal inside the container)
```

### Docker on WSL2 (Windows)

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) with WSL 2 engine enabled
2. Settings → Resources → WSL Integration → Enable for your distro
3. In WSL terminal:
```bash
git clone https://github.com/JFK/voicesrt.git
cd voicesrt
cp .env.example .env
# Set ENCRYPTION_KEY in .env
docker compose up --build
```

### Local

```bash
# Prerequisites: Python 3.11+, ffmpeg
pip install -e ".[dev]"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
cp .env.example .env
# Set ENCRYPTION_KEY in .env
uvicorn src.main:app --reload --port 8000
```

## Usage

### 1. Configure API Keys
Settings → Enter OpenAI / Google API keys. For Ollama, set the base URL and select a model.

### 2. Upload & Transcribe
Upload → Drag & drop a file → Select transcription engine (Whisper / Gemini) → Choose post-processing model if refine is enabled → Upload & Process.

### 3. Edit SRT
History → **Edit** → SRT Editor. Edit segments, assign speakers, use AI suggestions, merge/split segments, adjust timestamps. Download full SRT/VTT or per-speaker exports.

### 4. Generate YouTube Metadata
History → **Meta** → Metadata Editor. Set channel info, choose LLM model, generate title/description/chapters/tags.

### 5. Catchphrases & Quiz
History → **Catchphrase** / **Quiz** → Select model in modal → Generate.

## Tech Stack

- **Backend**: FastAPI (Python 3.11+), async/await
- **Frontend**: Jinja2 + HTMX + Alpine.js + Tailwind CSS (no build step)
- **Database**: SQLite (SQLAlchemy 2.0 async + aiosqlite + Alembic)
- **AI**: OpenAI Whisper/GPT, Google Gemini, Ollama (local)
- **Audio**: ffmpeg
- **Security**: Fernet encryption for API keys
- **i18n**: English / Japanese

## Provider Comparison

| | OpenAI Whisper | Google Gemini | Ollama (Local) |
|---|---|---|---|
| Transcription | Yes (dedicated ASR) | Yes (multimodal LLM) | No (uses Whisper) |
| Post-processing | GPT models | Gemini models | Any local model |
| Cost | $0.006/min (STT) + LLM | ~$0.0005/min (Flash Lite) | Free (local hardware) |
| File Limit | 25MB (auto-chunking) | 9.5 hours | N/A |
| Privacy | Cloud | Cloud | Fully local |

## License

MIT License
