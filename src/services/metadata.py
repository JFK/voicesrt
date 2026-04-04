from src.constants import get_provider_name
from src.services.utils import create_openai_compatible_client, extract_gemini_tokens, parse_json_response

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
    custom_prompt: str | None = None,
    tone_references: str | None = None,
) -> tuple[dict, int, int]:
    """Generate YouTube metadata from SRT content.

    Returns (metadata_dict, input_tokens, output_tokens).
    """
    tone_section = ""
    if tone_references:
        tone_section = (
            "\n\n## Tone Reference (match this style)\n"
            "The following are titles and descriptions from previously published videos.\n"
            "Match their tone, writing style, and formatting conventions:\n\n"
            f"{tone_references}"
        )

    if custom_prompt:
        prompt = custom_prompt + tone_section + f"\n\n---\n\nTranscription:\n{srt_content}"
    else:
        if tone_section:
            # Insert tone section before the transcription divider
            base = METADATA_USER_PROMPT.split("\n---\n\nTranscription:\n{srt_content}")[0]
            prompt = base + tone_section + f"\n\n---\n\nTranscription:\n{srt_content}"
        else:
            prompt = METADATA_USER_PROMPT.format(srt_content=srt_content)

    provider_name = get_provider_name(provider)
    if provider_name in ("openai", "ollama"):
        return await _generate_openai_compat(prompt, api_key, model, provider_name)
    else:
        return await _generate_gemini(prompt, api_key, model)


OPTIMIZE_PROMPT = """\
You are a YouTube SEO expert. Improve the following metadata generation prompt \
based on the channel context provided.

Make the prompt more specific and effective for generating:
- Click-worthy titles (with SEO keywords)
- Engaging descriptions (with chapter index format)
- Relevant tags

Channel context:
- Channel: {channel_name}
- Genre: {genre}
- Speakers: {speakers}
- Target audience: {audience}
- Notes: {notes}
{tone_ref_section}
Current prompt:
{current_prompt}

Return ONLY the improved prompt text. Do not include any explanation or markdown."""


async def optimize_meta_prompt(
    current_prompt: str,
    context: dict,
    api_key: str,
    provider: str,
    model: str,
    tone_references: str | None = None,
) -> str:
    """Use LLM to optimize the metadata generation prompt."""
    tone_ref_section = ""
    if tone_references:
        tone_ref_section = f"\nPrevious video metadata (for tone reference):\n{tone_references}\n"

    prompt = OPTIMIZE_PROMPT.format(
        channel_name=context.get("channelName", ""),
        genre=context.get("genre", ""),
        speakers=context.get("speakers", ""),
        audience=context.get("audience", ""),
        notes=context.get("notes", ""),
        current_prompt=current_prompt,
        tone_ref_section=tone_ref_section,
    )

    if provider in ("openai", "ollama"):
        client = create_openai_compatible_client(provider, api_key)
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return response.choices[0].message.content or current_prompt
    else:
        import asyncio

        from google import genai

        client = genai.Client(api_key=api_key)
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model,
            contents=prompt,
        )
        return response.text.strip() or current_prompt


async def _generate_openai_compat(
    prompt: str, credential: str, model: str, provider: str = "openai"
) -> tuple[dict, int, int]:
    client = create_openai_compatible_client(provider, credential)
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
    metadata = parse_json_response(text, context="OpenAI metadata")

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

    metadata = parse_json_response(response.text, context="Gemini metadata")
    input_tokens, output_tokens = extract_gemini_tokens(response)

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

    chapter_lines = "\n".join(f"{ch['time']} {ch['title']}" for ch in chapters)
    if chapter_lines:
        description = description.rstrip() + "\n\n" + chapter_lines

    metadata["description"] = description
    return metadata
