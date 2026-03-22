"""LLM post-processing to refine SRT transcription accuracy."""

import json
import logging

from src.services.utils import strip_markdown_fence

logger = logging.getLogger(__name__)

REFINE_SYSTEM_PROMPT = (
    "You are a professional subtitle editor. "
    "Your job is to correct transcription errors while preserving timestamps exactly as given."
)

REFINE_USER_PROMPT = """Review and correct the following subtitle segments transcribed from audio.

Fix:
- Misrecognized words (especially proper nouns, technical terms)
- Homophones and kanji errors (for Japanese)
- Punctuation and readability
- Remove filler words (um, uh, えー, あのー) unless they are meaningful
- Split overly long segments (>50 chars) into natural reading units

Do NOT change:
- Timestamps (start/end values must remain exactly the same)
- The meaning or intent of what was said
- Segments that are already correct

You MUST return a JSON object with a "segments" key containing the corrected array.
Format: {{"segments": [{{"start": 0.0, "end": 2.5, "text": "corrected text"}}, ...]}}
{glossary_section}
Input segments:
{segments_json}"""


def _extract_segments(result: object) -> list[dict]:
    """Extract segments list from various LLM response formats."""
    if isinstance(result, list):
        # Direct array
        segments = result
    elif isinstance(result, dict):
        # Try common wrapper keys
        for key in ("segments", "data", "results", "subtitles"):
            if key in result and isinstance(result[key], list):
                segments = result[key]
                break
        else:
            raise RuntimeError(f"Cannot find segments array in response: {list(result.keys())}")
    else:
        raise RuntimeError(f"Unexpected response type: {type(result).__name__}")

    # Validate each segment has required fields
    validated = []
    for seg in segments:
        if isinstance(seg, dict) and "start" in seg and "end" in seg and "text" in seg:
            validated.append({
                "start": float(seg["start"]),
                "end": float(seg["end"]),
                "text": str(seg["text"]).strip(),
            })
        else:
            logger.warning("Skipping invalid segment: %s", repr(seg)[:100])

    return validated


async def refine_with_llm(
    segments: list[dict],
    api_key: str,
    provider: str,
    model: str,
    glossary: str = "",
) -> tuple[list[dict], int, int]:
    """Refine SRT segments using LLM post-processing.

    Returns (refined_segments, input_tokens, output_tokens).
    """
    segments_json = json.dumps(segments, ensure_ascii=False, indent=2)
    glossary_section = ""
    if glossary.strip():
        glossary_section = f"""
IMPORTANT - Use this glossary to correct proper nouns, names, and technical terms:
{glossary.strip()}
"""
    prompt = REFINE_USER_PROMPT.format(segments_json=segments_json, glossary_section=glossary_section)

    if provider == "openai":
        return await _refine_openai(prompt, api_key, model)
    else:
        return await _refine_gemini(prompt, api_key, model)


async def _refine_openai(prompt: str, api_key: str, model: str) -> tuple[list[dict], int, int]:
    import openai

    client = openai.AsyncOpenAI(api_key=api_key)
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": REFINE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )

    text = response.choices[0].message.content or "{}"
    try:
        result = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"LLM returned invalid JSON during refinement: {e}. Response: {text[:200]}")

    segments = _extract_segments(result)

    input_tokens = response.usage.prompt_tokens if response.usage else 0
    output_tokens = response.usage.completion_tokens if response.usage else 0

    return segments, input_tokens, output_tokens


async def _refine_gemini(prompt: str, api_key: str, model: str) -> tuple[list[dict], int, int]:
    import asyncio

    from google import genai

    client = genai.Client(api_key=api_key)
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model,
        contents=f"{REFINE_SYSTEM_PROMPT}\n\n{prompt}",
    )

    text = strip_markdown_fence(response.text)
    try:
        result = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini returned invalid JSON during refinement: {e}. Response: {text[:200]}")

    segments = _extract_segments(result)

    input_tokens = 0
    output_tokens = 0
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

    return segments, input_tokens, output_tokens
