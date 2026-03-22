from pathlib import Path

import openai


async def transcribe_with_whisper(
    audio_path: Path,
    api_key: str,
    language: str | None = None,
) -> list[dict]:
    """Transcribe audio using OpenAI Whisper API.

    Returns list of segments: [{"start": float, "end": float, "text": str}, ...]
    """
    client = openai.AsyncOpenAI(api_key=api_key)

    with open(audio_path, "rb") as f:
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
            language=language,
        )

    segments = []
    if hasattr(response, "segments") and response.segments:
        for seg in response.segments:
            segments.append({
                "start": seg.start if hasattr(seg, "start") else seg["start"],
                "end": seg.end if hasattr(seg, "end") else seg["end"],
                "text": (seg.text if hasattr(seg, "text") else seg["text"]).strip(),
            })

    return segments
