# API Reference

Base URL: `http://localhost:8000`

## Jobs API (`/api/jobs`)

### Create Job
```
POST /api/jobs?provider=gemini&enable_refine=true&refine_mode=standard&enable_verify=true
Content-Type: multipart/form-data

file: <binary>
glossary: "term:reading\nOpenAI:oh-pen-ay-eye"  (optional, form field)
```

**Query Parameters:**
| Param | Type | Default | Description |
|---|---|---|---|
| provider | string | "whisper" | "whisper" or "gemini" |
| language | string? | null | "ja", "en", "zh", "ko" (null = auto-detect) |
| enable_refine | bool | false | Enable LLM post-processing |
| refine_mode | string? | null | "verbatim", "standard", or "caption" |
| enable_verify | bool | false | Enable full-text verification |

**Response:** `{"id": "uuid", "status": "pending"}`

### Get Job
```
GET /api/jobs/{job_id}
```

**Response:**
```json
{
  "id": "uuid",
  "filename": "video.mp4",
  "status": "completed",
  "provider": "gemini",
  "audio_duration": 1734.0,
  "youtube_title": "Generated Title",
  "youtube_description": "Generated description...",
  "youtube_tags": "[\"tag1\", \"tag2\"]"
}
```

### Get Job Status (HTMX partial)
```
GET /api/jobs/{job_id}/status
Headers: HX-Request: true
```

Returns HTML partial for status badge polling.

### Download SRT
```
GET /api/jobs/{job_id}/download
```

Returns SRT file as `text/plain` attachment.

### Delete Job
```
DELETE /api/jobs/{job_id}
```

Deletes job record and associated files (upload, audio, SRT).

### Generate Metadata
```
POST /api/jobs/{job_id}/generate-meta
Content-Type: application/json

{
  "custom_prompt": "...",
  "fixed_footer": "Channel links...",
  "use_tone_ref": true
}
```

Starts background metadata generation. Poll job status for completion.

### Optimize Prompt
```
POST /api/jobs/{job_id}/optimize-prompt
Content-Type: application/json

{
  "context": {
    "channelName": "My Channel",
    "genre": "Tech",
    "speakers": "John",
    "audience": "Developers",
    "notes": ""
  },
  "current_prompt": "...",
  "use_tone_ref": true
}
```

**Response:** `{"optimized_prompt": "improved prompt text..."}`

### Generate Catchphrases
```
POST /api/jobs/{job_id}/generate-catchphrase?regenerate=false
```

**Response:**
```json
{
  "catchphrases": [
    {"text": "Catchphrase text", "style": "question"},
    {"text": "Another one", "style": "exclamation"}
  ],
  "cached": false
}
```

### Generate Quiz
```
POST /api/jobs/{job_id}/generate-quiz?regenerate=false
```

**Response:**
```json
{
  "quiz": [
    {
      "question": "What is...?",
      "options": ["A", "B", "C", "D"],
      "answer_index": 2
    }
  ],
  "cached": false
}
```

### Get Segments
```
GET /api/jobs/{job_id}/segments
```

**Response:**
```json
{
  "segments": [
    {"start": 0.0, "end": 2.5, "text": "Hello, welcome."}
  ],
  "verified_indices": [3, 7],
  "verify_reasons": {"3": "Fixed kanji", "7": "Corrected name"}
}
```

### Update Segments
```
PUT /api/jobs/{job_id}/segments
Content-Type: application/json

{
  "segments": [
    {"start": 0.0, "end": 2.5, "text": "Updated text"}
  ]
}
```

### AI Suggestion
```
POST /api/jobs/{job_id}/segments/{index}/suggest
```

**Response:** `{"text": "suggested text", "reason": "Fixed proper noun"}`

## Settings API (`/api/settings`)

### API Keys
```
GET  /api/settings/keys                    # List configured keys
PUT  /api/settings/keys/{provider}         # Save key ({"key": "sk-..."})
DELETE /api/settings/keys/{provider}       # Delete key
POST /api/settings/keys/{provider}/test    # Test key validity
```

Providers: `openai`, `google`

### Models
```
GET  /api/settings/models                  # Get current models
PUT  /api/settings/models/{provider}       # Set model ({"model": "gpt-5.4"})
```

Providers: `openai`, `gemini`

### Glossary
```
GET  /api/settings/glossary                # Get glossary text
PUT  /api/settings/glossary                # Save ({"value": "term1\nterm2"})
```

### Tone References
```
GET  /api/settings/tone-references         # Get reference posts
PUT  /api/settings/tone-references         # Save ({"value": "---\nTitle: ..."})
```

### Pricing
```
GET  /api/settings/pricing                 # Get model pricing
PUT  /api/settings/pricing                 # Save ({"pricing": {...}})
```

### General Settings
```
GET  /api/settings/general                 # Get all general settings
PUT  /api/settings/general/{key}           # Set value ({"value": "10"})
```

### Refine Prompts
```
GET    /api/settings/refine-prompts           # Get all mode prompts
PUT    /api/settings/refine-prompts/{mode}    # Save custom prompt
DELETE /api/settings/refine-prompts/{mode}    # Reset to default
```

Modes: `verbatim`, `standard`, `caption`

## Costs API (`/api/costs`)

```
GET /api/costs
```

**Response:**
```json
{
  "total_cost": 0.826,
  "by_provider": {"gemini": 0.275, "openai": 0.030, "whisper": 0.520},
  "by_operation": {"transcription": 0.55, "refinement": 0.15, ...},
  "by_month": [{"month": "2026-03", "cost": 0.826}],
  "recent_logs": [...]
}
```
