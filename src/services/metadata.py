import json

from src.services.utils import strip_markdown_fence

METADATA_SYSTEM_PROMPT = (
    "You are an expert at generating YouTube video metadata. "
    "Generate optimal metadata for YouTube from the given video transcription."
)

METADATA_USER_PROMPT = """Generate YouTube metadata from the following video transcription (SRT format).

## Output Format
Return ONLY a JSON object, no other text or markdown:

{{
  "title": "SEO-optimized title (max 60 characters)",
  "description": "Video description text",
  "tags": ["tag1", "tag2", ...],
  "chapters": [
    {{"time": "00:00", "title": "Chapter title"}},
    ...
  ]
}}

## Description Structure
1. First 3 lines: Video summary (shown in search results)
2. Blank line
3. Chapter index (MM:SS timestamps)
4. Blank line
5. Related keywords and hashtags

## Chapter Rules
- Analyze timestamps and content boundaries in the transcription
- Set chapters at topic change points
- First chapter must be 00:00
- Each chapter title max 20 characters

## Tags
- 15-25 tags
- Related to the main topics of the video
- Match the language of the video content

---

Transcription:
{srt_content}"""



async def generate_youtube_metadata(
    srt_content: str,
    api_key: str,
    provider: str,
    model: str,
) -> tuple[dict, int, int]:
    """Generate YouTube metadata from SRT content.

    Returns (metadata_dict, input_tokens, output_tokens).
    """
    prompt = METADATA_USER_PROMPT.format(srt_content=srt_content)

    if provider == "whisper":
        return await _generate_openai(prompt, api_key, model)
    else:
        return await _generate_gemini(prompt, api_key, model)


async def _generate_openai(prompt: str, api_key: str, model: str) -> tuple[dict, int, int]:
    import openai

    client = openai.AsyncOpenAI(api_key=api_key)
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": METADATA_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
    )

    text = response.choices[0].message.content or "{}"
    try:
        metadata = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"OpenAI returned invalid JSON: {e}. Response: {text[:200]}")

    input_tokens = response.usage.prompt_tokens if response.usage else 0
    output_tokens = response.usage.completion_tokens if response.usage else 0

    return _build_description(metadata), input_tokens, output_tokens


async def _generate_gemini(prompt: str, api_key: str, model: str) -> tuple[dict, int, int]:
    import asyncio

    from google import genai

    client = genai.Client(api_key=api_key)
    # Run synchronous Gemini client in thread pool to avoid blocking event loop
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model,
        contents=f"{METADATA_SYSTEM_PROMPT}\n\n{prompt}",
    )

    text = strip_markdown_fence(response.text)
    try:
        metadata = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini returned invalid JSON: {e}. Response: {text[:200]}")

    input_tokens = 0
    output_tokens = 0
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

    return _build_description(metadata), input_tokens, output_tokens


def _build_description(metadata: dict) -> dict:
    """Ensure chapters are embedded in the description."""
    chapters = metadata.get("chapters", [])
    if not chapters:
        return metadata

    description = metadata.get("description", "")

    # Skip if chapters already in description
    if any(ch.get("time", "") in description for ch in chapters[:2]):
        return metadata

    chapter_lines = "\n".join(f'{ch["time"]} {ch["title"]}' for ch in chapters)
    if chapter_lines:
        description = description.rstrip() + "\n\n" + chapter_lines

    metadata["description"] = description
    return metadata
