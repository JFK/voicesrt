# User Guide

VoiceSRT generates SRT subtitle files from video/audio using AI transcription, with optional LLM post-processing and YouTube metadata generation.

## Quick Start

1. Open VoiceSRT in your browser (default: http://localhost:8000)
2. Go to **Settings** and enter your API key (OpenAI or Google Gemini)
3. Click **Upload**, select a file, choose provider and options
4. Wait for processing to complete
5. Edit subtitles in the SRT Editor, then download

---

## Upload & Transcription

### Supported Formats

MP4, MP3, WAV, MOV, AVI, MKV, M4A, FLAC, OGG, WebM

### Providers

| Provider | Best for | Requires |
|----------|----------|----------|
| **Whisper** (OpenAI) | Fast, accurate speech-to-text | OpenAI API key |
| **Gemini** (Google) | Long files, multilingual | Google API key |
| **Ollama** (local) | Privacy, no API costs | Ollama running locally |

### Language

Choose the spoken language or select **Auto Detect**. Available: Japanese, English, Chinese, Korean.

Specifying the correct language improves accuracy, especially for multilingual content.

### Processing Pipeline

```
Upload → Audio Extraction → Transcription → Refinement → Verification → SRT Output
                                               (optional)    (optional)
```

Each optional step is **non-fatal** — if refinement or verification fails, the job continues with the previous result. You'll see a warning but still get usable subtitles.

---

## Refine

Refinement is LLM post-processing that cleans up the raw transcription. VoiceSRT uses a single **verbatim** mode, which keeps the transcription faithful to the spoken audio:

- Fixes only misrecognized words, proper nouns, and technical terms
- **Preserves all filler words**: "um", "uh", "えー", "あのー"
- **Preserves timestamps and segment boundaries**, so the SRT stays aligned with the audio
- Does not change sentence boundaries or punctuation
- Best for: any subtitle work where the on-screen text must line up with what was said

> Earlier versions also offered `standard` and `caption` modes, but they shifted the SRT timing — `caption` re-segmented and redistributed timestamps, and `standard` dropped fillers and could desync the displayed text from the audio — so they were removed in v1.1.0. Jobs created before then are read back as `verbatim`.

### Custom Prompt

Admins can override the built-in verbatim prompt via **Settings → Refine Prompts**. This is useful for domain-specific requirements (e.g., medical terminology rules).

---

## Glossary

The glossary helps the AI correctly transcribe and refine specialized terms, proper nouns, and technical vocabulary.

### Format

One entry per line. Use a colon to separate the term from its reading or pronunciation:

```
漢字:かんじ
OpenAI:オープンエーアイ
Kubernetes:クベルネテス
GitHub
```

- Both half-width (`:`) and full-width (`：`) colons are accepted
- Lines without a colon are included as-is
- Maximum **5,000 characters**
- You can also use `→` for explicit corrections: `誤字→正字`

### How It Works

The glossary is applied at multiple stages:

1. **Transcription** — Terms and readings are passed to the speech recognition model as hints. For Whisper, the prompt is limited to 800 characters, so put the most important terms first.
2. **Refinement** — The LLM uses the glossary to correct misrecognized words with high priority.
3. **AI Suggest** — Per-segment suggestions apply matching glossary corrections first.

### Global vs. Per-Job Glossary

- **Global glossary**: Set in Settings, applied to all jobs
- **Per-job glossary**: Set during upload or in the SRT Editor, merged with the global glossary
- Per-job entries are appended to the global glossary during processing

### Tips

- Put the most commonly misrecognized terms first (Whisper has a character limit)
- Include both the written form and pronunciation for non-obvious terms
- For names of people and places, include the reading to avoid kanji errors

---

## Verification

When enabled, verification performs a full-text consistency check after refinement:

- Detects inconsistent spellings of proper nouns across segments
- Catches remaining kanji errors and homophones
- Flags place names and technical terms that differ from the glossary

In the SRT Editor, verified segments are highlighted with the reason for each change.

---

## SRT Editor

After transcription completes, click the job to open the editor.

### Editing Segments

- Click any segment's text to edit it directly
- Adjust start/end timestamps in the time fields
- Segments must not overlap — the editor validates timing automatically

### AI Suggest

Click the suggest button on any segment to get an AI-powered improvement. The suggestion:
- Considers surrounding context (5 segments before and after)
- Applies glossary corrections with highest priority
- Shows a reason for the change

You can accept or dismiss each suggestion.

### Speaker Assignment

Assign speaker names to segments for multi-speaker content:
1. Define speakers (e.g., "Alice", "Bob")
2. Assign each segment to a speaker
3. Download SRT filtered by speaker — useful for per-speaker subtitle tracks

### Segment Operations

- **Merge**: Combine two adjacent segments into one
- **Split**: Divide a segment at a point (timestamps adjust proportionally)
- **Delete**: Remove a segment
- **Add**: Insert a new segment between existing ones

---

## YouTube Metadata

VoiceSRT can generate YouTube-ready metadata from your transcription.

### What's Generated

| Field | Details |
|-------|---------|
| **Title** | Max 60 characters, SEO-optimized |
| **Description** | 3-line summary, chapter timestamps, keywords/hashtags |
| **Tags** | 15–25 relevant tags |
| **Chapters** | Timestamped sections (MM:SS format, max 20 chars per title) |

### Tone References

Tone references help the AI match the style of your existing content. Set them in **Settings → Tone References**.

Paste examples of your previous video titles and descriptions:

```
Previous Video Title: "5 SHOCKING Productivity Hacks You Need"
Previous Description: "In this video, we reveal the top 5..."

Previous Video Title: "The TRUTH About AI in 2026"
Previous Description: "AI is changing everything..."
```

The AI will match the tone, formatting, and style of your examples when generating new metadata.

### Custom Prompt

You can provide a custom prompt for metadata generation per-job. The **Optimize Prompt** button uses AI to improve your current prompt based on your channel context.

### Fixed Footer

Text that's appended to every generated description without AI modification — useful for standard links, social media handles, or disclaimers.

---

## Catchphrase Generation

Generates 5 thumbnail text suggestions from your video content:
- Max 15 characters (Japanese) or 5 words (English)
- Styles: question, exclamation, statement, surprise, humor
- Cached — click regenerate for fresh suggestions

---

## Quiz Generation

Generates 5 multiple-choice questions from your video content:
- 4 options per question
- Useful for YouTube community posts or educational content
- Cached — click regenerate for fresh questions

---

## Cost Tracking

VoiceSRT tracks estimated API costs for every operation.

### Pricing

| Provider | Model | Cost |
|----------|-------|------|
| Whisper | whisper-1 | $0.006 / minute |
| Gemini | gemini-2.5-flash-lite | $0.10 / $0.40 per 1M tokens |
| Gemini | gemini-2.5-flash | $0.15 / $0.60 per 1M tokens |
| Gemini | gemini-2.5-pro | $1.25 / $10.00 per 1M tokens |
| Ollama | (any) | Free (local) |

Costs are tracked per operation: transcription, refinement, verification, metadata, suggest, catchphrase, quiz.

View totals on the **Costs** page. Admins can customize pricing in Settings.

---

## Settings

### API Keys

Enter and test your keys for OpenAI and Google Gemini. Keys are encrypted before storage — they never appear in logs or responses.

For Ollama, configure the base URL (default: `http://localhost:11434`). No API key needed.

### Default Models

Set the default model for each provider. You can override the model per-job during upload.

Separate settings for transcription models and refinement models — use a cheaper/faster model for refinement if cost is a concern.

### Global Glossary

Terms entered here apply to all jobs. See the [Glossary](#glossary) section for format details.

### Refine Prompts

View or override the built-in verbatim refine prompt. Click **Reset** to restore the default.

---

## Languages

The interface is available in **English** and **Japanese**. The language switches automatically based on your browser settings, or can be changed in the UI.

Transcription language (the spoken language in the audio) is set separately during upload.
