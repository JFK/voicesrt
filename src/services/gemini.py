import asyncio
import logging
from pathlib import Path

from google import genai
from google.genai.types import GenerateContentConfig

from src.services.utils import extract_gemini_tokens, parse_json_response

logger = logging.getLogger(__name__)

GEMINI_TIMEOUT_SEC = 600  # 10 minutes


async def transcribe_with_gemini(
    audio_path: Path,
    api_key: str,
    language: str | None = None,
    model: str = "gemini-2.5-flash",
    glossary: str = "",
) -> tuple[list[dict], int, int]:
    """Transcribe audio using Google Gemini API.

    Returns (segments, input_tokens, output_tokens).
    """
    client = genai.Client(api_key=api_key)

    uploaded = await asyncio.to_thread(client.files.upload, file=str(audio_path))

    lang_hint = f" The audio is in {language}." if language else ""
    glossary_hint = ""
    if glossary.strip():
        glossary_hint = f"""

Use this glossary for accurate transcription of proper nouns and technical terms:
{glossary.strip()}
"""
    prompt = f"""Transcribe this audio file with precise timestamps.{lang_hint}

Return ONLY a JSON array, no other text or markdown. Each element must have:
- "start": start time in seconds (float, e.g. 1.5)
- "end": end time in seconds (float, e.g. 4.2)
- "text": the spoken text for that segment

Keep segments at natural sentence boundaries, roughly 1-10 seconds each.
Example: [{{"start": 0.0, "end": 2.5, "text": "Hello, welcome."}}]{glossary_hint}"""

    response = await asyncio.wait_for(
        asyncio.to_thread(
            client.models.generate_content,
            model=model,
            contents=[uploaded, prompt],
            config=GenerateContentConfig(
                max_output_tokens=65536,
                response_mime_type="application/json",
            ),
        ),
        timeout=GEMINI_TIMEOUT_SEC,
    )

    segments = parse_json_response(response.text, context="Gemini transcription")
    input_tokens, output_tokens = extract_gemini_tokens(response)

    # Clean up uploaded file
    try:
        await asyncio.to_thread(client.files.delete, name=uploaded.name)
    except Exception:
        logger.warning("Failed to delete uploaded file: %s", uploaded.name)

    return segments, input_tokens, output_tokens
