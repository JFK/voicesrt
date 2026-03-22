import json
import logging
from pathlib import Path

from google import genai

from src.services.utils import strip_markdown_fence

logger = logging.getLogger(__name__)


async def transcribe_with_gemini(
    audio_path: Path,
    api_key: str,
    language: str | None = None,
    model: str = "gemini-2.5-flash",
) -> tuple[list[dict], int, int]:
    """Transcribe audio using Google Gemini API.

    Returns (segments, input_tokens, output_tokens).
    """
    client = genai.Client(api_key=api_key)

    uploaded = client.files.upload(file=str(audio_path))

    lang_hint = f" The audio is in {language}." if language else ""
    prompt = f"""Transcribe this audio file with precise timestamps.{lang_hint}

Return ONLY a JSON array, no other text or markdown. Each element must have:
- "start": start time in seconds (float, e.g. 1.5)
- "end": end time in seconds (float, e.g. 4.2)
- "text": the spoken text for that segment

Keep segments at natural sentence boundaries, roughly 1-10 seconds each.
Example: [{{"start": 0.0, "end": 2.5, "text": "Hello, welcome."}}]"""

    response = client.models.generate_content(
        model=model,
        contents=[uploaded, prompt],
    )

    text = strip_markdown_fence(response.text)
    try:
        segments = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini returned invalid JSON: {e}. Response: {text[:200]}")

    input_tokens = 0
    output_tokens = 0
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

    # Clean up uploaded file
    try:
        client.files.delete(name=uploaded.name)
    except Exception:
        logger.warning("Failed to delete uploaded file: %s", uploaded.name)

    return segments, input_tokens, output_tokens
