import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.constants import (
    KEY_API_GOOGLE,
    KEY_API_OPENAI,
    KEY_MODEL_GEMINI,
    KEY_MODEL_OLLAMA,
    KEY_MODEL_OPENAI,
    KEY_OLLAMA_BASE_URL,
    get_provider_name,
)
from src.models import Job, Setting
from src.services.audio import extract_audio, extract_audio_mp3, get_audio_duration, split_audio
from src.services.cost import estimate_gemini_cost, estimate_llm_cost, estimate_whisper_cost, log_cost
from src.services.crypto import decrypt
from src.services.srt import generate_srt, save_srt

logger = logging.getLogger(__name__)


async def _get_credential(session: AsyncSession, provider: str) -> str:
    """Get decrypted API key for the given transcription provider.

    For ollama, returns the base URL instead (no API key needed).
    """
    if provider == "ollama":
        result = await session.execute(select(Setting).where(Setting.key == KEY_OLLAMA_BASE_URL))
        setting = result.scalar_one_or_none()
        return setting.value if setting else settings.default_ollama_base_url

    db_key = KEY_API_OPENAI if provider == "whisper" else KEY_API_GOOGLE
    result = await session.execute(select(Setting).where(Setting.key == db_key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise RuntimeError(f"API key ({db_key}) is not configured. Set it in Settings.")
    return decrypt(setting.value)


async def _get_model(session: AsyncSession, provider: str, override: str | None = None) -> str:
    """Get configured LLM model for the given provider. Override takes precedence."""
    if override:
        return override
    if provider == "ollama":
        result = await session.execute(select(Setting).where(Setting.key == KEY_MODEL_OLLAMA))
        setting = result.scalar_one_or_none()
        return setting.value if setting else settings.default_ollama_model

    db_key = KEY_MODEL_OPENAI if provider == "whisper" else KEY_MODEL_GEMINI
    result = await session.execute(select(Setting).where(Setting.key == db_key))
    setting = result.scalar_one_or_none()
    if setting:
        return setting.value
    return settings.default_openai_model if provider == "whisper" else settings.default_gemini_model


async def process_transcription(job: Job, session: AsyncSession) -> None:
    """Main transcription pipeline: extract audio -> transcribe -> SRT -> metadata."""
    # Find uploaded file (any supported extension)
    upload_path = None
    for f in settings.uploads_dir.glob(f"{job.id}.*"):
        upload_path = f
        break
    if not upload_path or not upload_path.exists():
        raise FileNotFoundError(f"Upload file not found for job {job.id}")

    # Ollama can't do audio transcription; use Whisper (OpenAI) for STT
    transcription_provider = "whisper" if job.provider == "ollama" else job.provider
    api_key = await _get_credential(session, transcription_provider)
    audio_path: Path | None = None

    try:
        # Step 1: Extract audio
        job.status = "extracting"
        await session.commit()

        if transcription_provider == "whisper":
            audio_path = settings.audio_dir / f"{job.id}.wav"
            duration = await extract_audio(upload_path, audio_path)
        else:
            audio_path = settings.audio_dir / f"{job.id}.mp3"
            duration = await extract_audio_mp3(upload_path, audio_path)

        job.audio_duration = duration
        await session.commit()

        # Merge global glossary (from Settings) with per-job glossary
        result = await session.execute(select(Setting).where(Setting.key == "glossary"))
        glossary_setting = result.scalar_one_or_none()
        global_glossary = glossary_setting.value if glossary_setting else ""
        job_glossary = job.glossary or ""
        combined_glossary = "\n".join(filter(None, [global_glossary.strip(), job_glossary.strip()]))

        # Step 2: Transcribe
        job.status = "transcribing"
        await session.commit()

        segments = await _run_transcription(
            job, session, audio_path, api_key, duration, combined_glossary, transcription_provider
        )

        # For post-processing, use the job's own provider (may differ from transcription)
        pp_api_key = await _get_credential(session, job.provider) if job.provider != transcription_provider else api_key

        # Step 3: LLM post-processing (refine) if enabled
        if job.enable_refine:
            job.status = "refining"
            await session.commit()
            try:
                segments = await _run_refinement(job, session, segments, pp_api_key, combined_glossary)
            except Exception as e:
                logger.warning("Refinement failed for job %s: %s", job.id, e)
                job.error_message = f"Refinement failed, using raw transcription: {str(e)[:300]}"

        # Step 3.5: Verify (full-text consistency check) if enabled
        if job.enable_verify:
            job.status = "verifying"
            await session.commit()
            try:
                segments, changed_indices, reasons = await _run_verification(
                    job,
                    session,
                    segments,
                    pp_api_key,
                    combined_glossary,
                )
                job.verified_indices = json.dumps(changed_indices)
                job.verify_reasons = json.dumps(reasons, ensure_ascii=False)
            except Exception as e:
                logger.warning("Verification failed for job %s: %s", job.id, e)
                job.error_message = f"Verification failed, using refined transcription: {str(e)[:300]}"

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
                await _run_metadata_generation(job, session, srt_content, pp_api_key)
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
    job: Job,
    session: AsyncSession,
    audio_path: Path,
    api_key: str,
    duration: float,
    glossary: str = "",
    transcription_provider: str | None = None,
) -> list[dict]:
    """Run transcription with the configured provider and log cost."""
    effective_provider = transcription_provider or job.provider
    # Build Whisper prompt from glossary (extract terms as hints)
    whisper_prompt = _build_whisper_prompt(glossary) if glossary else None

    if effective_provider == "whisper":
        segments = await _transcribe_whisper(audio_path, api_key, job.language, whisper_prompt)
        cost = estimate_whisper_cost(duration)
        await log_cost(session, job.id, "whisper", "whisper-1", "transcription", cost, audio_duration=duration)
    else:
        model = await _get_model(session, effective_provider, job.model_override)
        segments, input_tokens, output_tokens = await _transcribe_gemini(
            audio_path, api_key, job.language, model, glossary
        )
        cost = estimate_gemini_cost(duration, output_tokens, model)
        await log_cost(
            session,
            job.id,
            "gemini",
            model,
            "transcription",
            cost,
            audio_duration=duration,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    return segments


def _build_whisper_prompt(glossary: str) -> str:
    """Extract terms from glossary lines (term:reading) as comma-separated hints for Whisper."""
    terms = []
    for line in glossary.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Extract both the term and reading
        if ":" in line or "：" in line:
            parts = line.replace("：", ":").split(":", 1)
            terms.append(parts[0].strip())
            if parts[1].strip():
                terms.append(parts[1].strip())
        else:
            terms.append(line)
    return "、".join(terms) if terms else ""


async def _transcribe_whisper(
    audio_path: Path, api_key: str, language: str | None, prompt: str | None = None
) -> list[dict]:
    """Transcribe with Whisper, handling chunking for large files."""
    from src.services.whisper import transcribe_with_whisper

    chunks = await split_audio(audio_path)
    if len(chunks) == 1:
        return await transcribe_with_whisper(audio_path, api_key, language, prompt)

    all_segments: list[dict] = []
    offset = 0.0
    for chunk_path in chunks:
        chunk_duration = await get_audio_duration(chunk_path)
        segments = await transcribe_with_whisper(chunk_path, api_key, language, prompt)
        # Apply offset without mutating original segments
        for seg in segments:
            all_segments.append(
                {
                    "start": seg["start"] + offset,
                    "end": seg["end"] + offset,
                    "text": seg["text"],
                }
            )
        offset += chunk_duration

    return all_segments


async def _transcribe_gemini(
    audio_path: Path,
    api_key: str,
    language: str | None,
    model: str = "gemini-2.5-flash",
    glossary: str = "",
) -> tuple[list[dict], int, int]:
    """Transcribe with Gemini, handling chunking for large files."""
    from src.services.gemini import transcribe_with_gemini

    chunks = await split_audio(audio_path)
    if len(chunks) == 1:
        return await transcribe_with_gemini(audio_path, api_key, language, model, glossary)

    logger.info("Splitting audio into %d chunks for Gemini transcription", len(chunks))
    all_segments: list[dict] = []
    total_input_tokens = 0
    total_output_tokens = 0
    offset = 0.0
    for chunk_path in chunks:
        chunk_duration = await get_audio_duration(chunk_path)
        segments, input_tokens, output_tokens = await transcribe_with_gemini(
            chunk_path, api_key, language, model, glossary
        )
        for seg in segments:
            all_segments.append(
                {
                    "start": seg["start"] + offset,
                    "end": seg["end"] + offset,
                    "text": seg["text"],
                }
            )
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens
        offset += chunk_duration

    return all_segments, total_input_tokens, total_output_tokens


async def _run_metadata_generation(
    job: Job,
    session: AsyncSession,
    srt_content: str,
    api_key: str,
    custom_prompt: str | None = None,
    tone_references: str | None = None,
    model: str | None = None,
) -> None:
    """Generate YouTube metadata using LLM and log cost."""
    from src.services.metadata import generate_youtube_metadata

    if not model:
        model = await _get_model(session, job.provider)
    result, input_tokens, output_tokens = await generate_youtube_metadata(
        srt_content, api_key, job.provider, model, custom_prompt, tone_references
    )

    job.youtube_title = result.get("title", "")
    job.youtube_description = result.get("description", "")
    tags = result.get("tags", [])
    job.youtube_tags = json.dumps(tags, ensure_ascii=False)

    provider_name = get_provider_name(job.provider)
    cost = estimate_llm_cost(input_tokens, output_tokens, model, provider_name)
    await log_cost(
        session,
        job.id,
        provider_name,
        model,
        "metadata_generation",
        cost,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


_DEFAULT_REFINE_MODELS = {
    "openai": "gpt-5.4-nano",
    "gemini": "gemini-2.5-flash-lite",
    "ollama": settings.default_ollama_model,
}


async def _get_refine_model(session: AsyncSession, provider_name: str) -> str:
    """Get refine/verify model from settings or provider default."""
    refine_key = f"general.refine_model_{provider_name}"
    result = await session.execute(select(Setting).where(Setting.key == refine_key))
    setting = result.scalar_one_or_none()
    return setting.value if setting else _DEFAULT_REFINE_MODELS.get(provider_name, "gpt-5.4-nano")


async def _run_refinement(
    job: Job,
    session: AsyncSession,
    segments: list[dict],
    api_key: str,
    glossary: str = "",
) -> list[dict]:
    """Refine segments using LLM post-processing and log cost."""
    from src.services.refine import refine_with_llm

    provider_name = get_provider_name(job.provider)
    refine_model = await _get_refine_model(session, provider_name)

    refine_mode = job.refine_mode or "standard"

    # Load custom prompts from DB
    custom_prompts = {}
    for mode in ("verbatim", "standard", "caption"):
        key = f"general.refine_prompt_{mode}"
        result = await session.execute(select(Setting).where(Setting.key == key))
        setting = result.scalar_one_or_none()
        if setting:
            custom_prompts[mode] = setting.value

    refined, input_tokens, output_tokens = await refine_with_llm(
        segments,
        api_key,
        provider_name,
        refine_model,
        glossary,
        refine_mode,
        custom_prompts=custom_prompts or None,
    )

    cost = estimate_llm_cost(input_tokens, output_tokens, refine_model, provider_name)
    await log_cost(
        session,
        job.id,
        provider_name,
        refine_model,
        "refinement",
        cost,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

    return refined


async def _run_verification(
    job: Job,
    session: AsyncSession,
    segments: list[dict],
    api_key: str,
    glossary: str = "",
) -> tuple[list[dict], list[int], dict[int, str]]:
    """Verify segments using full-text review and log cost."""
    from src.services.refine import verify_segments

    provider_name = get_provider_name(job.provider)
    verify_model = await _get_refine_model(session, provider_name)

    verified, changed_indices, reasons, input_tokens, output_tokens = await verify_segments(
        segments,
        api_key,
        provider_name,
        verify_model,
        glossary,
    )

    cost = estimate_llm_cost(input_tokens, output_tokens, verify_model, provider_name)
    await log_cost(
        session,
        job.id,
        provider_name,
        verify_model,
        "verification",
        cost,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

    return verified, changed_indices, reasons
