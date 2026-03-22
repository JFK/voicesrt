import json


METADATA_SYSTEM_PROMPT = """あなたはYouTube動画のメタデータ生成の専門家です。
与えられた動画の文字起こしテキストから、YouTube投稿に最適なメタデータを生成してください。"""

METADATA_USER_PROMPT = """以下の動画の文字起こし（SRT形式）から、YouTube投稿用のメタデータを生成してください。

## 出力形式
必ず以下のJSON形式のみを返してください。他のテキストやmarkdownは不要です。

{{
  "title": "SEOを意識した60文字以内のタイトル",
  "description": "概要欄テキスト",
  "tags": ["タグ1", "タグ2", ...],
  "chapters": [
    {{"time": "00:00", "title": "チャプタータイトル"}},
    ...
  ]
}}

## 概要欄の構成
1. 冒頭3行: 動画の要約（検索結果に表示される部分）
2. 空行
3. チャプターインデックス（00:00 形式のタイムスタンプ）
4. 空行
5. 関連キーワード・ハッシュタグ

## チャプター生成ルール
- 文字起こしのタイムスタンプと内容の区切りを分析
- 話題が変わるポイントでチャプターを設定
- 最初のチャプターは必ず 00:00
- 各チャプタータイトルは20文字以内

## タグ
- 15-25個
- 日本語と英語を混ぜる
- 動画の主要トピックに関連するもの

---

文字起こし:
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
        # Use OpenAI
        return await _generate_openai(prompt, api_key, model)
    else:
        # Use Gemini
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
    metadata = json.loads(text)

    input_tokens = response.usage.prompt_tokens if response.usage else 0
    output_tokens = response.usage.completion_tokens if response.usage else 0

    # Build description with chapters
    metadata = _build_description(metadata)

    return metadata, input_tokens, output_tokens


async def _generate_gemini(prompt: str, api_key: str, model: str) -> tuple[dict, int, int]:
    from google import genai

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=f"{METADATA_SYSTEM_PROMPT}\n\n{prompt}",
    )

    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3].strip()

    metadata = json.loads(text)

    input_tokens = 0
    output_tokens = 0
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

    metadata = _build_description(metadata)

    return metadata, input_tokens, output_tokens


def _build_description(metadata: dict) -> dict:
    """Ensure chapters are embedded in the description."""
    chapters = metadata.get("chapters", [])
    if not chapters:
        return metadata

    description = metadata.get("description", "")

    # Check if chapters are already in description
    if any(ch.get("time", "") in description for ch in chapters[:2]):
        return metadata

    # Append chapter index to description
    chapter_lines = "\n".join(f'{ch["time"]} {ch["title"]}' for ch in chapters)
    if chapter_lines:
        description = description.rstrip() + "\n\n" + chapter_lines

    metadata["description"] = description
    return metadata
