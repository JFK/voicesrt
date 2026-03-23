import logging
from pathlib import Path
from typing import Any

import openai

logger = logging.getLogger(__name__)


async def transcribe_with_whisper(
    audio_path: Path,
    api_key: str,
    language: str | None = None,
    prompt: str | None = None,
) -> list[dict]:
    """Transcribe audio using OpenAI Whisper API.

    Returns list of segments: [{"start": float, "end": float, "text": str}, ...]
    """
    client = openai.AsyncOpenAI(api_key=api_key)

    kwargs: dict[str, Any] = {
        "model": "whisper-1",
        "response_format": "verbose_json",
        "timestamp_granularities": ["segment"],
    }
    if language:
        kwargs["language"] = language
    if prompt:
        # Whisper prompt is limited to ~224 tokens; truncate if needed
        if len(prompt) > 800:
            logger.warning("Whisper prompt truncated from %d to 800 chars", len(prompt))
            prompt = prompt[:800]
        kwargs["prompt"] = prompt

    with open(audio_path, "rb") as f:
        kwargs["file"] = f
        response = await client.audio.transcriptions.create(**kwargs)

    segments = []
    raw_segments = getattr(response, "segments", None)
    seg_type = type(raw_segments).__name__ if raw_segments else "None"
    logger.debug("Whisper response type: %s, segments type: %s", type(response).__name__, seg_type)
    for seg in (raw_segments or []):
        logger.debug("Segment type: %s, value: %s", type(seg).__name__, repr(seg)[:200])
        if isinstance(seg, dict):
            segments.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"].strip(),
            })
        else:
            segments.append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
            })

    return segments
