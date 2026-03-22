from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models import Job, Setting
from src.services.audio import extract_audio, extract_audio_mp3, get_audio_duration, split_audio
from src.services.cost import estimate_gemini_cost, estimate_whisper_cost, log_cost
from src.services.crypto import decrypt
from src.services.srt import generate_srt, save_srt


async def _get_api_key(session: AsyncSession, provider: str) -> str:
    """Get decrypted API key for provider."""
    key_name = "openai" if provider == "whisper" else "google"
    db_key = f"api_key.{key_name}"
    result = await session.execute(select(Setting).where(Setting.key == db_key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise RuntimeError(f"API key for {key_name} is not configured. Please set it in Settings.")
    return decrypt(setting.value)


async def _get_model(session: AsyncSession, provider: str) -> str:
    """Get configured LLM model for provider."""
    model_key = "openai" if provider == "whisper" else "gemini"
    db_key = f"model.{model_key}"
    result = await session.execute(select(Setting).where(Setting.key == db_key))
    setting = result.scalar_one_or_none()
    if setting:
        return setting.value
    return settings.default_openai_model if provider == "whisper" else settings.default_gemini_model


async def process_transcription(job: Job, session: AsyncSession) -> None:
    """Main transcription pipeline."""
    mp4_path = settings.uploads_dir / f"{job.id}.mp4"
    if not mp4_path.exists():
        raise FileNotFoundError(f"Upload file not found: {mp4_path}")

    api_key = await _get_api_key(session, job.provider)

    # Step 1: Extract audio
    job.status = "extracting"
    await session.commit()

    if job.provider == "whisper":
        audio_path = settings.audio_dir / f"{job.id}.wav"
        duration = await extract_audio(mp4_path, audio_path)
    else:
        audio_path = settings.audio_dir / f"{job.id}.mp3"
        duration = await extract_audio_mp3(mp4_path, audio_path)

    job.audio_duration = duration
    await session.commit()

    # Step 2: Transcribe
    job.status = "transcribing"
    await session.commit()

    if job.provider == "whisper":
        segments = await _transcribe_whisper(audio_path, api_key, job.language, duration)
        cost = estimate_whisper_cost(duration)
        await log_cost(session, job.id, "whisper", "whisper-1", "transcription", cost, audio_duration=duration)
    else:
        model = await _get_model(session, job.provider)
        segments, input_tokens, output_tokens = await _transcribe_gemini(audio_path, api_key, job.language, model)
        cost = estimate_gemini_cost(duration, output_tokens, model)
        await log_cost(
            session, job.id, "gemini", model, "transcription", cost,
            audio_duration=duration, input_tokens=input_tokens, output_tokens=output_tokens,
        )

    # Step 3: Generate and save SRT
    srt_content = generate_srt(segments)
    srt_path = settings.srt_dir / f"{job.id}.srt"
    save_srt(srt_content, srt_path)
    job.srt_path = str(srt_path)

    # Step 4: Generate metadata if enabled
    if job.enable_metadata:
        job.status = "generating_metadata"
        await session.commit()
        await _generate_metadata(job, session, srt_content, api_key)

    # Done
    job.status = "completed"
    job.completed_at = datetime.now(UTC)
    await session.commit()

    # Cleanup temporary files
    for p in [audio_path, mp4_path]:
        if p.exists():
            p.unlink()
    # Clean up chunks
    for chunk in audio_path.parent.glob(f"{audio_path.stem}_chunk*"):
        chunk.unlink()


async def _transcribe_whisper(
    audio_path: Path, api_key: str, language: str | None, duration: float
) -> list[dict]:
    """Transcribe with Whisper, handling chunking for large files."""
    from src.services.whisper import transcribe_with_whisper

    chunks = await split_audio(audio_path)
    if len(chunks) == 1:
        return await transcribe_with_whisper(audio_path, api_key, language)

    all_segments = []
    offset = 0.0
    for chunk_path in chunks:
        chunk_duration = await get_audio_duration(chunk_path)
        segments = await transcribe_with_whisper(chunk_path, api_key, language)
        for seg in segments:
            seg["start"] += offset
            seg["end"] += offset
        all_segments.extend(segments)
        offset += chunk_duration

    return all_segments


async def _transcribe_gemini(
    audio_path: Path, api_key: str, language: str | None, model: str
) -> tuple[list[dict], int, int]:
    """Transcribe with Gemini."""
    from src.services.gemini import transcribe_with_gemini

    return await transcribe_with_gemini(audio_path, api_key, language, model)


async def _generate_metadata(job: Job, session: AsyncSession, srt_content: str, api_key: str) -> None:
    """Generate YouTube metadata using LLM."""
    from src.services.metadata import generate_youtube_metadata

    model = await _get_model(session, job.provider)
    result, input_tokens, output_tokens = await generate_youtube_metadata(
        srt_content, api_key, job.provider, model
    )

    job.youtube_title = result.get("title", "")
    job.youtube_description = result.get("description", "")
    tags = result.get("tags", [])
    import json
    job.youtube_tags = json.dumps(tags, ensure_ascii=False)

    # Log metadata generation cost
    from src.services.cost import estimate_llm_cost

    provider_name = "openai" if job.provider == "whisper" else "gemini"
    cost = estimate_llm_cost(input_tokens, output_tokens, model, provider_name)
    await log_cost(
        session, job.id, provider_name, model, "metadata_generation", cost,
        input_tokens=input_tokens, output_tokens=output_tokens,
    )
