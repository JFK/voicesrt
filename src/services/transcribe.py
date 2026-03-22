import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models import Job, Setting
from src.services.audio import extract_audio, extract_audio_mp3, get_audio_duration, split_audio
from src.services.cost import estimate_gemini_cost, estimate_llm_cost, estimate_whisper_cost, log_cost
from src.services.crypto import decrypt
from src.services.srt import generate_srt, save_srt

logger = logging.getLogger(__name__)


async def _get_api_key(session: AsyncSession, provider: str) -> str:
    """Get decrypted API key for the given transcription provider."""
    key_name = "openai" if provider == "whisper" else "google"
    db_key = f"api_key.{key_name}"
    result = await session.execute(select(Setting).where(Setting.key == db_key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise RuntimeError(f"API key for {key_name} is not configured. Set it in Settings.")
    return decrypt(setting.value)


async def _get_model(session: AsyncSession, provider: str) -> str:
    """Get configured LLM model for the given provider."""
    model_key = "openai" if provider == "whisper" else "gemini"
    db_key = f"model.{model_key}"
    result = await session.execute(select(Setting).where(Setting.key == db_key))
    setting = result.scalar_one_or_none()
    if setting:
        return setting.value
    return settings.default_openai_model if provider == "whisper" else settings.default_gemini_model


async def process_transcription(job: Job, session: AsyncSession) -> None:
    """Main transcription pipeline: extract audio -> transcribe -> SRT -> metadata."""
    mp4_path = settings.uploads_dir / f"{job.id}.mp4"
    if not mp4_path.exists():
        raise FileNotFoundError(f"Upload file not found: {mp4_path}")

    api_key = await _get_api_key(session, job.provider)
    audio_path: Path | None = None

    try:
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

        segments = await _run_transcription(job, session, audio_path, api_key, duration)

        # Step 3: LLM post-processing (refine) if enabled
        if job.enable_refine:
            job.status = "refining"
            await session.commit()
            try:
                segments = await _run_refinement(job, session, segments, api_key)
            except Exception as e:
                logger.warning("Refinement failed for job %s: %s", job.id, e)
                job.error_message = f"Refinement failed, using raw transcription: {str(e)[:300]}"

        # Step 4: Generate and save SRT
        srt_content = generate_srt(segments)
        srt_path = settings.srt_dir / f"{job.id}.srt"
        save_srt(srt_content, srt_path)
        job.srt_path = str(srt_path)

        # Step 5: Generate metadata if enabled (non-fatal)
        if job.enable_metadata:
            job.status = "generating_metadata"
            await session.commit()
            try:
                await _run_metadata_generation(job, session, srt_content, api_key)
            except Exception as e:
                logger.warning("Metadata generation failed for job %s: %s", job.id, e)
                job.error_message = f"SRT generated, but metadata failed: {str(e)[:300]}"

        # Done
        job.status = "completed"
        job.completed_at = datetime.now(UTC)
        await session.commit()

    finally:
        # Cleanup temporary files regardless of success/failure
        _cleanup_temp_files(job.id, audio_path)


def _cleanup_temp_files(job_id: str, audio_path: Path | None) -> None:
    """Remove temporary audio files. MP4 is kept for video embedding."""
    if audio_path:
        audio_path.unlink(missing_ok=True)
        # Clean up chunks
        for chunk in audio_path.parent.glob(f"{audio_path.stem}_chunk*"):
            chunk.unlink(missing_ok=True)


async def _run_transcription(
    job: Job, session: AsyncSession, audio_path: Path, api_key: str, duration: float
) -> list[dict]:
    """Run transcription with the configured provider and log cost."""
    if job.provider == "whisper":
        segments = await _transcribe_whisper(audio_path, api_key, job.language)
        cost = estimate_whisper_cost(duration)
        await log_cost(session, job.id, "whisper", "whisper-1", "transcription", cost, audio_duration=duration)
    else:
        model = await _get_model(session, job.provider)
        from src.services.gemini import transcribe_with_gemini

        segments, input_tokens, output_tokens = await transcribe_with_gemini(
            audio_path, api_key, job.language, model
        )
        cost = estimate_gemini_cost(duration, output_tokens, model)
        await log_cost(
            session, job.id, "gemini", model, "transcription", cost,
            audio_duration=duration, input_tokens=input_tokens, output_tokens=output_tokens,
        )

    return segments


async def _transcribe_whisper(audio_path: Path, api_key: str, language: str | None) -> list[dict]:
    """Transcribe with Whisper, handling chunking for large files."""
    from src.services.whisper import transcribe_with_whisper

    chunks = await split_audio(audio_path)
    if len(chunks) == 1:
        return await transcribe_with_whisper(audio_path, api_key, language)

    all_segments: list[dict] = []
    offset = 0.0
    for chunk_path in chunks:
        chunk_duration = await get_audio_duration(chunk_path)
        segments = await transcribe_with_whisper(chunk_path, api_key, language)
        # Apply offset without mutating original segments
        for seg in segments:
            all_segments.append({
                "start": seg["start"] + offset,
                "end": seg["end"] + offset,
                "text": seg["text"],
            })
        offset += chunk_duration

    return all_segments


async def _run_metadata_generation(
    job: Job, session: AsyncSession, srt_content: str, api_key: str
) -> None:
    """Generate YouTube metadata using LLM and log cost."""
    from src.services.metadata import generate_youtube_metadata

    model = await _get_model(session, job.provider)
    result, input_tokens, output_tokens = await generate_youtube_metadata(
        srt_content, api_key, job.provider, model
    )

    job.youtube_title = result.get("title", "")
    job.youtube_description = result.get("description", "")
    tags = result.get("tags", [])
    job.youtube_tags = json.dumps(tags, ensure_ascii=False)

    provider_name = "openai" if job.provider == "whisper" else "gemini"
    cost = estimate_llm_cost(input_tokens, output_tokens, model, provider_name)
    await log_cost(
        session, job.id, provider_name, model, "metadata_generation", cost,
        input_tokens=input_tokens, output_tokens=output_tokens,
    )


async def _run_refinement(
    job: Job, session: AsyncSession, segments: list[dict], api_key: str
) -> list[dict]:
    """Refine segments using LLM post-processing and log cost."""
    from src.services.refine import refine_with_llm

    provider_name = "openai" if job.provider == "whisper" else "gemini"

    # Get refine model from settings
    refine_key = f"general.refine_model_{provider_name}"
    result = await session.execute(select(Setting).where(Setting.key == refine_key))
    setting = result.scalar_one_or_none()
    refine_model = setting.value if setting else ("gpt-5.4-nano" if provider_name == "openai" else "gemini-3.1-flash-lite")

    # Get glossary
    result = await session.execute(select(Setting).where(Setting.key == "glossary"))
    glossary_setting = result.scalar_one_or_none()
    glossary = glossary_setting.value if glossary_setting else ""

    refined, input_tokens, output_tokens = await refine_with_llm(
        segments, api_key, provider_name, refine_model, glossary
    )

    cost = estimate_llm_cost(input_tokens, output_tokens, refine_model, provider_name)
    await log_cost(
        session, job.id, provider_name, refine_model, "refinement", cost,
        input_tokens=input_tokens, output_tokens=output_tokens,
    )

    return refined
