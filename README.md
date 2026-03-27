# VoiceSRT

[日本語](README.ja.md)

AI-powered SRT subtitle generator with YouTube metadata, catchphrase, and quiz generation.

## Features

### Transcription & SRT
- **AI Transcription**: OpenAI Whisper API / Google Gemini API
- **Multi-format**: MP4, MP3, WAV, MOV, AVI, MKV, M4A, FLAC, OGG, WebM
- **LLM Post-processing**: 3 modes (Verbatim / Standard / Caption) with glossary support
- **Verify Pass**: Full-text consistency check for proper nouns, place names, kanji
- **SRT Editor**: Inline editing with per-segment AI suggestions

### YouTube Tools
- **Metadata Generation**: SEO-optimized title, description with chapters, 15-25 tags
- **Tone Reference**: Match previous videos' writing style for channel consistency
- **Catchphrase Generation**: 5 thumbnail text suggestions with style classification
- **Quiz Generation**: 5 multiple-choice questions from video content

### Management
- **Upload History**: 2-row layout with grouped action buttons and status indicators
- **Cost Dashboard**: Track API costs by provider, model, month, and operation
- **Settings**: API keys (encrypted), model presets, glossary, refine prompts, pricing

## Screenshots

### Upload
![Upload](docs/screenshots/upload.png)

### Cost Dashboard
![Cost Dashboard](docs/screenshots/costs.png)

### Settings
![Settings](docs/screenshots/settings.png)

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
Settings page → Enter OpenAI / Google API keys.

### 2. Upload & Transcribe
Upload page → Drag & drop file → Select provider & refine mode → Upload & Process.
Processing completes → Auto-redirect to Upload History.

### 3. Edit SRT
Upload History → **Edit** button → SRT Editor.
Edit segments, use AI suggestions, save & download.

### 4. Generate YouTube Metadata
Upload History → **Meta** button → Metadata Editor.
Set channel info, enable tone reference, generate title/description/chapters/tags.

### 5. Generate Catchphrases & Quiz
Upload History → **Catchphrase** / **Quiz** buttons → One-click generation.

## Tech Stack

- **Backend**: FastAPI (Python 3.11+), async/await
- **Frontend**: Jinja2 + HTMX + Alpine.js + Tailwind CSS (no build step)
- **Database**: SQLite (SQLAlchemy 2.0 async + aiosqlite + Alembic)
- **AI**: OpenAI Whisper/GPT, Google Gemini
- **Audio**: ffmpeg
- **Security**: Fernet encryption for API keys
- **i18n**: English / Japanese

## Provider Comparison

| | OpenAI Whisper | Google Gemini |
|---|---|---|
| Accuracy | High (dedicated ASR) | High (multimodal LLM) |
| Timestamps | Precise | Approximate |
| Cost | $0.006/min | ~$0.0005/min (Flash Lite) |
| File Limit | 25MB (auto-chunking) | 9.5 hours |

## License

MIT License
