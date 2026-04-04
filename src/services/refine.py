"""LLM post-processing to refine SRT transcription accuracy."""

import json
import logging

from src.services.utils import create_openai_compatible_client, extract_gemini_tokens, parse_json_response

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
            validated.append(
                {
                    "start": float(seg["start"]),
                    "end": float(seg["end"]),
                    "text": str(seg["text"]).strip(),
                }
            )
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

    if provider in ("openai", "ollama"):
        return await _refine_openai_compat(prompt, api_key, model, provider)
    else:
        return await _refine_gemini(prompt, api_key, model)


async def _refine_openai_compat(
    prompt: str, credential: str, model: str, provider: str = "openai"
) -> tuple[list[dict], int, int]:
    client = create_openai_compatible_client(provider, credential)
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


# ---------------------------------------------------------------------------
# Verify: full-text review for consistency
# ---------------------------------------------------------------------------

VERIFY_SYSTEM_PROMPT = (
    "You are a professional proofreader specialising in transcription quality. "
    "You read an entire transcript and find inconsistencies in proper nouns, "
    "place names, kanji, and terminology."
)

VERIFY_PROMPT = """\
Below is a full transcript assembled from subtitle segments.
Each line is prefixed with its segment number in square brackets.

Read the ENTIRE text, understand the topic and story, then check for:
- Inconsistent proper nouns (same person/org spelled differently across segments)
- Incorrect place names
- Kanji homophone errors (同音異義語)
- Terms that contradict the glossary below
- Any phrase that seems contextually wrong

Return ONLY the segments that need correction.
If nothing needs fixing, return an empty corrections array.

You MUST return JSON in this exact format:
{{"corrections": [{{"index": 0, "text": "corrected text", "reason": "why this was changed"}}, ...]}}

The "index" field is the 0-based segment index (the number shown in brackets).
{glossary_section}
Transcript:
{full_text}"""


def _build_full_text(segments: list[dict]) -> str:
    """Join segment texts with index markers for full-text review."""
    return "\n".join(f"[{i}] {seg['text']}" for i, seg in enumerate(segments))


def _extract_corrections(result: object) -> list[dict]:
    """Extract corrections list from LLM response."""
    if isinstance(result, dict):
        corrections = result.get("corrections", [])
    elif isinstance(result, list):
        corrections = result
    else:
        raise RuntimeError(f"Unexpected verify response type: {type(result).__name__}")

    validated = []
    for c in corrections:
        if isinstance(c, dict) and "index" in c and "text" in c:
            validated.append(
                {
                    "index": int(c["index"]),
                    "text": str(c["text"]).strip(),
                    "reason": str(c.get("reason", "")),
                }
            )
        else:
            logger.warning("Skipping invalid correction: %s", repr(c)[:100])
    return validated


async def verify_segments(
    segments: list[dict],
    api_key: str,
    provider: str,
    model: str,
    glossary: str = "",
) -> tuple[list[dict], list[int], dict[int, str], int, int]:
    """Verify refined segments by full-text review.

    Returns (verified_segments, changed_indices, reasons, input_tokens, output_tokens).
    """
    full_text = _build_full_text(segments)
    glossary_section = ""
    if glossary.strip():
        glossary_section = f"""
IMPORTANT - Use this glossary to verify proper nouns, names, and technical terms:
{glossary.strip()}
"""
    prompt = VERIFY_PROMPT.format(full_text=full_text, glossary_section=glossary_section)

    if provider in ("openai", "ollama"):
        corrections, input_tokens, output_tokens = await _verify_openai_compat(prompt, api_key, model, provider)
    else:
        corrections, input_tokens, output_tokens = await _verify_gemini(prompt, api_key, model)

    # Merge corrections into segments
    verified = [dict(seg) for seg in segments]
    changed_indices: list[int] = []
    reasons: dict[int, str] = {}
    for c in corrections:
        idx = c["index"]
        if 0 <= idx < len(verified):
            verified[idx]["text"] = c["text"]
            changed_indices.append(idx)
            if c["reason"]:
                reasons[idx] = c["reason"]
        else:
            logger.warning("Verify correction index %d out of range (0-%d)", idx, len(verified) - 1)

    return verified, changed_indices, reasons, input_tokens, output_tokens


async def _verify_openai_compat(
    prompt: str, credential: str, model: str, provider: str = "openai"
) -> tuple[list[dict], int, int]:
    client = create_openai_compatible_client(provider, credential)
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": VERIFY_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )

    text = response.choices[0].message.content or "{}"
    result = parse_json_response(text, context="OpenAI verification")
    corrections = _extract_corrections(result)

    input_tokens = response.usage.prompt_tokens if response.usage else 0
    output_tokens = response.usage.completion_tokens if response.usage else 0
    return corrections, input_tokens, output_tokens


async def _verify_gemini(prompt: str, api_key: str, model: str) -> tuple[list[dict], int, int]:
    import asyncio

    from google import genai
    from google.genai.types import GenerateContentConfig

    client = genai.Client(api_key=api_key)
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model,
        contents=f"{VERIFY_SYSTEM_PROMPT}\n\n{prompt}",
        config=GenerateContentConfig(
            max_output_tokens=65536,
            response_mime_type="application/json",
        ),
    )

    result = parse_json_response(response.text or "{}", context="Gemini verification")
    corrections = _extract_corrections(result)
    input_tokens, output_tokens = extract_gemini_tokens(response)
    return corrections, input_tokens, output_tokens


# ---------------------------------------------------------------------------
# Suggest: per-segment AI suggestion
# ---------------------------------------------------------------------------

SUGGEST_SYSTEM_PROMPT = (
    "You are a professional subtitle editor. "
    "You suggest improved text for a single subtitle segment, "
    "considering its surrounding context."
)

SUGGEST_PROMPT = """\
Improve the following subtitle segment for readability and accuracy.

Context (surrounding segments for reference):
{context}

Target segment to improve:
{target_text}

{glossary_section}
Return JSON: {{"text": "improved text", "reason": "what was changed and why"}}
If no improvement is needed, return the original text unchanged."""


async def suggest_segment(
    segment: dict,
    context_before: list[dict],
    context_after: list[dict],
    api_key: str,
    provider: str,
    model: str,
    glossary: str = "",
) -> tuple[str, str, int, int]:
    """Suggest improvement for a single segment.

    Returns (suggested_text, reason, input_tokens, output_tokens).
    """
    context_lines = []
    for seg in context_before:
        context_lines.append(f"  (before) {seg['text']}")
    context_lines.append(f"  >>> {segment['text']} <<<")
    for seg in context_after:
        context_lines.append(f"  (after) {seg['text']}")
    context = "\n".join(context_lines)

    glossary_section = ""
    if glossary.strip():
        glossary_section = f"Glossary:\n{glossary.strip()}"

    prompt = SUGGEST_PROMPT.format(
        context=context,
        target_text=segment["text"],
        glossary_section=glossary_section,
    )

    if provider in ("openai", "ollama"):
        return await _suggest_openai_compat(prompt, api_key, model, provider)
    else:
        return await _suggest_gemini(prompt, api_key, model)


async def _suggest_openai_compat(
    prompt: str, credential: str, model: str, provider: str = "openai"
) -> tuple[str, str, int, int]:
    client = create_openai_compatible_client(provider, credential)
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SUGGEST_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )

    text = response.choices[0].message.content or "{}"
    result = parse_json_response(text, context="OpenAI suggestion")
    if not isinstance(result, dict):
        result = {}
    suggested = str(result.get("text", "")).strip()
    reason = str(result.get("reason", ""))

    input_tokens = response.usage.prompt_tokens if response.usage else 0
    output_tokens = response.usage.completion_tokens if response.usage else 0
    return suggested, reason, input_tokens, output_tokens


async def _suggest_gemini(prompt: str, api_key: str, model: str) -> tuple[str, str, int, int]:
    import asyncio

    from google import genai
    from google.genai.types import GenerateContentConfig

    client = genai.Client(api_key=api_key)
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model,
        contents=f"{SUGGEST_SYSTEM_PROMPT}\n\n{prompt}",
        config=GenerateContentConfig(
            max_output_tokens=4096,
            response_mime_type="application/json",
        ),
    )

    result = parse_json_response(response.text or "{}", context="Gemini suggestion")
    if not isinstance(result, dict):
        result = {}
    suggested = str(result.get("text", "")).strip()
    reason = str(result.get("reason", ""))
    input_tokens, output_tokens = extract_gemini_tokens(response)
    return suggested, reason, input_tokens, output_tokens
