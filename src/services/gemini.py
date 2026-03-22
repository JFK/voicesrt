import json
from pathlib import Path

from google import genai


async def transcribe_with_gemini(
    audio_path: Path,
    api_key: str,
    language: str | None = None,
    model: str = "gemini-2.5-flash",
) -> tuple[list[dict], int, int]:
    """Transcribe audio using Google Gemini API.

    Returns (segments, input_tokens, output_tokens).
    Segments: [{"start": float, "end": float, "text": str}, ...]
    """
    client = genai.Client(api_key=api_key)

    # Upload file
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

    # Parse response
    text = response.text.strip()
    # Remove markdown code block if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3].strip()

    segments = json.loads(text)

    # Extract token counts
    input_tokens = 0
    output_tokens = 0
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

    # Clean up uploaded file
    try:
        client.files.delete(name=uploaded.name)
    except Exception:
        pass

    return segments, input_tokens, output_tokens
