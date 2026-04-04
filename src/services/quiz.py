"""Generate YouTube quiz questions from SRT content."""

import logging

from src.services.utils import create_openai_compatible_client, extract_gemini_tokens, parse_json_response

logger = logging.getLogger(__name__)

QUIZ_PROMPT = """Based on the following video transcription, generate 5 quiz questions for YouTube's quiz feature.

Each question must have:
- A clear, engaging question about the video content
- 4 answer options (A, B, C, D)
- The correct answer index (0-3)

Return ONLY a JSON object:
{{"quiz": [
  {{"question": "...", "options": ["A", "B", "C", "D"], "answer_index": 0}},
  ...
]}}

Transcription:
{srt_content}"""


async def generate_quiz(
    srt_content: str,
    api_key: str,
    provider: str,
    model: str,
) -> tuple[list[dict], int, int]:
    """Generate quiz questions from SRT content.

    Returns (quiz_list, input_tokens, output_tokens).
    """
    prompt = QUIZ_PROMPT.format(srt_content=srt_content)

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
        temperature=0.7,
        response_format={"type": "json_object"},
    )

    text = response.choices[0].message.content or "{}"
    result = parse_json_response(text, context="OpenAI quiz")

    quiz = result.get("quiz", [])
    input_tokens = response.usage.prompt_tokens if response.usage else 0
    output_tokens = response.usage.completion_tokens if response.usage else 0
    return quiz, input_tokens, output_tokens


async def _generate_gemini(prompt: str, api_key: str, model: str) -> tuple[list[dict], int, int]:
    import asyncio

    from google import genai

    client = genai.Client(api_key=api_key)
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model,
        contents=prompt,
    )

    result = parse_json_response(response.text, context="Gemini quiz")
    quiz = result.get("quiz", [])
    input_tokens, output_tokens = extract_gemini_tokens(response)
    return quiz, input_tokens, output_tokens
