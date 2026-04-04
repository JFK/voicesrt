"""Generate thumbnail catchphrase suggestions from SRT content."""

import logging

from src.services.utils import create_openai_compatible_client, extract_gemini_tokens, parse_json_response

logger = logging.getLogger(__name__)

CATCHPHRASE_PROMPT = """Based on the following video transcription, generate 5 catchy thumbnail text suggestions.

Requirements:
- Short and impactful (max 15 characters each for Japanese, max 5 words for English)
- Eye-catching, makes viewers want to click
- Captures the key message or surprise of the video
- Varies in style: question, exclamation, provocative statement, etc.

Return ONLY a JSON object:
{{"catchphrases": [
  {{"text": "catchphrase text", "style": "question/exclamation/statement/surprise/humor"}},
  ...
]}}

Transcription:
{srt_content}"""


async def generate_catchphrases(
    srt_content: str,
    api_key: str,
    provider: str,
    model: str,
) -> tuple[list[dict], int, int]:
    """Generate thumbnail catchphrase suggestions.

    Returns (catchphrase_list, input_tokens, output_tokens).
    """
    prompt = CATCHPHRASE_PROMPT.format(srt_content=srt_content)

    if provider in ("openai", "ollama"):
        return await _generate_openai_compat(prompt, api_key, model, provider)
    else:
        return await _generate_gemini(prompt, api_key, model)


async def _generate_openai_compat(
    prompt: str, credential: str, model: str, provider: str = "openai"
) -> tuple[list[dict], int, int]:
    client = create_openai_compatible_client(provider, credential)
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9,
        response_format={"type": "json_object"},
    )

    text = response.choices[0].message.content or "{}"
    result = parse_json_response(text, context="OpenAI catchphrase")
    phrases = result.get("catchphrases", [])
    input_tokens = response.usage.prompt_tokens if response.usage else 0
    output_tokens = response.usage.completion_tokens if response.usage else 0
    return phrases, input_tokens, output_tokens


async def _generate_gemini(prompt: str, api_key: str, model: str) -> tuple[list[dict], int, int]:
    import asyncio

    from google import genai

    client = genai.Client(api_key=api_key)
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model,
        contents=prompt,
    )

    result = parse_json_response(response.text, context="Gemini catchphrase")
    phrases = result.get("catchphrases", [])
    input_tokens, output_tokens = extract_gemini_tokens(response)
    return phrases, input_tokens, output_tokens
