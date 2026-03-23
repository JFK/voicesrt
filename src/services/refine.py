"""LLM post-processing to refine SRT transcription accuracy."""

import json
import logging

from src.services.utils import extract_gemini_tokens, parse_json_response

logger = logging.getLogger(__name__)

REFINE_SYSTEM_PROMPT = (
    "You are a professional subtitle editor. "
    "Your job is to correct transcription errors while preserving timestamps exactly as given."
)

# --- Verbatim mode: minimal corrections only ---
REFINE_VERBATIM_PROMPT = """Review and correct the following subtitle segments transcribed from audio.

Fix ONLY:
- Misrecognized words (especially proper nouns, technical terms)
- Homophones and kanji errors (for Japanese)

Do NOT change:
- Timestamps (start/end values must remain exactly the same)
- The meaning or intent of what was said
- Filler words (um, uh, えー, あのー) - keep them as-is
- Sentence boundaries or segment splits - keep original segmentation
- Punctuation style - keep as-is unless clearly wrong
- Segments that are already correct

Priority: verbatim accuracy. Keep the transcription as close to the spoken words as possible.

You MUST return a JSON object with a "segments" key containing the corrected array.
Format: {{"segments": [{{"start": 0.0, "end": 2.5, "text": "corrected text"}}, ...]}}
{glossary_section}
Input segments:
{segments_json}"""

# --- Standard mode: error correction + filler removal ---
REFINE_STANDARD_PROMPT = """Review and correct the following subtitle segments transcribed from audio.

Fix:
- Misrecognized words (especially proper nouns, technical terms)
- Homophones and kanji errors (for Japanese)
- Punctuation and readability
- Remove filler words (um, uh, えー, あのー) unless they are meaningful

Do NOT change:
- Timestamps (start/end values must remain exactly the same)
- The meaning or intent of what was said
- Sentence boundaries or segment splits - keep original segmentation
- Segments that are already correct

You MUST return a JSON object with a "segments" key containing the corrected array.
Format: {{"segments": [{{"start": 0.0, "end": 2.5, "text": "corrected text"}}, ...]}}
{glossary_section}
Input segments:
{segments_json}"""

# --- Caption mode: readability-optimized ---
REFINE_CAPTION_PROMPT = """\
Review and correct the following subtitle segments transcribed from audio \
for use as readable captions.

Fix:
- Misrecognized words (especially proper nouns, technical terms)
- Homophones and kanji errors (for Japanese)
- Punctuation and readability
- Remove all filler words (um, uh, えー, あのー, その, まあ)
- Smooth out stutters and repeated words
- Complete incomplete sentences for readability
- Split overly long segments (>40 chars) into natural reading units

When splitting a segment, divide the original start/end time proportionally among the new segments.
For example, a segment from 0.0-6.0 split into 2 parts becomes 0.0-3.0 and 3.0-6.0.

Do NOT change:
- The meaning or intent of what was said

Priority: readability. Make captions easy to read at a glance.

You MUST return a JSON object with a "segments" key containing the corrected array.
Format: {{"segments": [{{"start": 0.0, "end": 2.5, "text": "corrected text"}}, ...]}}
{glossary_section}
Input segments:
{segments_json}"""

_PROMPT_MAP = {
    "verbatim": REFINE_VERBATIM_PROMPT,
    "standard": REFINE_STANDARD_PROMPT,
    "caption": REFINE_CAPTION_PROMPT,
}


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
    refine_mode: str = "standard",
    custom_prompts: dict[str, str] | None = None,
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
    if custom_prompts and refine_mode in custom_prompts:
        template = custom_prompts[refine_mode]
    else:
        template = _PROMPT_MAP.get(refine_mode, REFINE_STANDARD_PROMPT)
    prompt = template.format(segments_json=segments_json, glossary_section=glossary_section)

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
    result = parse_json_response(text, context="OpenAI refinement")

    segments = _extract_segments(result)

    input_tokens = response.usage.prompt_tokens if response.usage else 0
    output_tokens = response.usage.completion_tokens if response.usage else 0

    return segments, input_tokens, output_tokens


async def _refine_gemini(prompt: str, api_key: str, model: str) -> tuple[list[dict], int, int]:
    import asyncio

    from google import genai
    from google.genai.types import GenerateContentConfig

    client = genai.Client(api_key=api_key)
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model,
        contents=f"{REFINE_SYSTEM_PROMPT}\n\n{prompt}",
        config=GenerateContentConfig(
            max_output_tokens=65536,
            response_mime_type="application/json",
        ),
    )

    result = parse_json_response(response.text, context="Gemini refinement")
    segments = _extract_segments(result)
    input_tokens, output_tokens = extract_gemini_tokens(response)

    return segments, input_tokens, output_tokens
