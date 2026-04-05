import logging
import re
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.constants import STATUS_COMPLETED, STATUS_FAILED, get_provider_name
from src.database import async_session, get_session
from src.errors import (
    AppError,
    file_too_large,
    glossary_too_long,
    invalid_provider,
    invalid_refine_mode,
    invalid_segment,
    invalid_segment_index,
    job_not_found,
    media_not_found,
    no_file_provided,
    no_segments_provided,
    no_speaker_segments,
    segment_overlap,
    segment_time_order,
    segment_timing_invalid,
    srt_file_missing,
    srt_not_available,
    srt_not_found,
    unsupported_format,
    upload_failed,
)
from src.models import Job
from src.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

# UI sends "openai"/"gemini"/"ollama"; backend expects "whisper"/"gemini"/"ollama"
_PROVIDER_ALIASES = {"openai": "whisper", "whisper": "whisper", "gemini": "gemini", "ollama": "ollama"}


def _normalize_provider(provider: str | None) -> str | None:
    """Normalize UI provider name to internal provider name."""
    if provider is None:
        return None
    normalized = _PROVIDER_ALIASES.get(provider.strip().lower())
    if normalized is None:
        raise invalid_provider(provider)
    return normalized


DEFAULT_MAX_UPLOAD_SIZE = settings.max_upload_size_gb * 1024 * 1024 * 1024


async def _get_max_upload_size(session: AsyncSession) -> int:
    """Get max upload size from DB settings, fallback to config default."""
    from src.models import Setting

    result = await session.execute(select(Setting).where(Setting.key == "general.max_upload_size_gb"))
    setting = result.scalar_one_or_none()
    if setting:
        try:
            return int(setting.value) * 1024 * 1024 * 1024
        except ValueError:
            pass
    return DEFAULT_MAX_UPLOAD_SIZE


# Sanitize filenames to prevent path traversal
_SAFE_FILENAME_RE = re.compile(r"[^\w\s\-.]", re.UNICODE)


def _safe_filename(name: str) -> str:
    return _SAFE_FILENAME_RE.sub("_", Path(name).name)


async def _get_job_or_404(session: AsyncSession, job_id: str) -> Job:
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise job_not_found()
    return job


def _resolve_srt_file(job: Job) -> Path:
    """Validate SRT path exists in DB and on disk, return resolved Path."""
    if not job.srt_path:
        raise srt_not_found()
    p = Path(job.srt_path).resolve()
    if not p.exists():
        raise srt_file_missing()
    return p


def _require_srt(job: Job) -> None:
    """Raise if job has no SRT file available (for generation endpoints)."""
    if not job.srt_path:
        raise srt_not_available()


async def _process_job(job_id: str) -> None:
    """Background task: extract audio, transcribe, generate metadata."""
    from src.services.transcribe import process_transcription

    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return

        try:
            await process_transcription(job, session)
        except Exception as e:
            from src.errors import classify_error

            logger.exception("Job %s failed", job_id)
            job.status = STATUS_FAILED
            job.error_message = classify_error(e)[:500]
            await session.commit()


VALID_REFINE_MODES = {"verbatim", "standard", "caption"}


@router.post("")
async def create_job(
    file: UploadFile,
    provider: str = "whisper",
    model: str | None = None,
    language: str | None = None,
    enable_metadata: bool = False,
    enable_refine: bool = False,
    enable_verify: bool = False,
    refine_mode: str | None = Query(None),
    glossary: str | None = Form(None),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: AsyncSession = Depends(get_session),
):
    if glossary and len(glossary) > 5000:
        raise glossary_too_long()

    if refine_mode and refine_mode not in VALID_REFINE_MODES:
        valid = ", ".join(VALID_REFINE_MODES)
        raise invalid_refine_mode(valid)

    supported = {".mp4", ".mp3", ".wav", ".mov", ".avi", ".mkv", ".m4a", ".flac", ".ogg", ".webm"}
    if not file.filename:
        raise no_file_provided()
    ext = Path(file.filename).suffix.lower()
    if ext not in supported:
        fmts = ", ".join(sorted(supported))
        raise unsupported_format(fmts)

    job_id = str(uuid.uuid4())
    upload_path = settings.uploads_dir / f"{job_id}{ext}"
    upload_path.parent.mkdir(parents=True, exist_ok=True)

    # Stream file to disk to handle large files without OOM
    max_size = await _get_max_upload_size(session)
    file_size = 0
    try:
        async with aiofiles.open(upload_path, "wb") as out:
            while chunk := await file.read(8 * 1024 * 1024):  # 8MB chunks
                file_size += len(chunk)
                if file_size > max_size:
                    await out.close()
                    upload_path.unlink(missing_ok=True)
                    max_gb = max_size // (1024**3)
                    raise file_too_large(max_gb)
                await out.write(chunk)
    except AppError:
        raise
    except Exception as e:
        logger.error("Upload failed for file %s: %s", file.filename, e)
        upload_path.unlink(missing_ok=True)
        raise upload_failed()

    try:
        job = Job(
            id=job_id,
            filename=_safe_filename(file.filename),
            file_size=file_size,
            provider=provider,
            language=language,
            enable_metadata=enable_metadata,
            enable_refine=enable_refine,
            enable_verify=enable_verify,
            glossary=glossary.strip() if glossary else None,
            refine_mode=refine_mode,
            model_override=model,
        )
        session.add(job)
        await session.commit()
    except Exception:
        upload_path.unlink(missing_ok=True)
        raise

    background_tasks.add_task(_process_job, job_id)
    return {"id": job_id, "status": "pending"}


@router.get("")
async def list_jobs(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Job).order_by(Job.created_at.desc()))
    jobs = result.scalars().all()
    return [
        {
            "id": j.id,
            "filename": j.filename,
            "status": j.status,
            "provider": j.provider,
            "audio_duration": j.audio_duration,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        }
        for j in jobs
    ]


@router.get("/{job_id}")
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)):
    job = await _get_job_or_404(session, job_id)
    return {
        "id": job.id,
        "filename": job.filename,
        "status": job.status,
        "error_message": job.error_message,
        "provider": job.provider,
        "language": job.language,
        "audio_duration": job.audio_duration,
        "srt_path": job.srt_path,
        "youtube_title": job.youtube_title,
        "youtube_description": job.youtube_description,
        "youtube_tags": job.youtube_tags,
        "enable_metadata": job.enable_metadata,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.get("/{job_id}/status")
async def get_job_status(job_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    """HTMX partial for polling job status."""
    job = await _get_job_or_404(session, job_id)

    if request.headers.get("HX-Request"):
        from src.templating import get_lang, get_translator

        t = get_translator(get_lang(request))
        return templates.TemplateResponse(request, "partials/job_status.html", {"job": job, "t": t})

    return {"status": job.status, "error_message": job.error_message}


@router.get("/{job_id}/download")
async def download_srt(
    job_id: str,
    speaker: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    import json as json_mod
    from urllib.parse import quote

    from fastapi.responses import Response

    from src.services.srt import generate_srt, parse_srt

    job = await _get_job_or_404(session, job_id)
    srt_file = _resolve_srt_file(job)

    stem = Path(_safe_filename(job.filename)).stem

    if not speaker:
        download_name = f"{stem}.srt"
        return FileResponse(srt_file, filename=download_name, media_type="text/plain")

    # Filter segments by speaker
    speaker_map = json_mod.loads(job.speaker_map) if job.speaker_map else {}
    segments = parse_srt(srt_file.read_text(encoding="utf-8"))
    filtered = [seg for i, seg in enumerate(segments) if speaker_map.get(str(i)) == speaker]
    if not filtered:
        raise no_speaker_segments(speaker)

    srt_content = generate_srt(filtered)
    download_name = f"{stem}_{speaker}.srt"
    encoded_name = quote(download_name, safe="")
    return Response(
        content=srt_content,
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


@router.get("/{job_id}/download-vtt")
async def download_vtt(
    job_id: str,
    speaker: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    import json as json_mod
    from urllib.parse import quote

    from fastapi.responses import Response

    from src.services.srt import generate_vtt, parse_srt, srt_to_vtt

    job = await _get_job_or_404(session, job_id)
    srt_file = _resolve_srt_file(job)

    stem = Path(_safe_filename(job.filename)).stem

    if not speaker:
        vtt_content = srt_to_vtt(srt_file.read_text(encoding="utf-8"))
        download_name = f"{stem}.vtt"
    else:
        speaker_map = json_mod.loads(job.speaker_map) if job.speaker_map else {}
        segments = parse_srt(srt_file.read_text(encoding="utf-8"))
        filtered = [seg for i, seg in enumerate(segments) if speaker_map.get(str(i)) == speaker]
        if not filtered:
            raise no_speaker_segments(speaker)
        vtt_content = generate_vtt(filtered)
        download_name = f"{stem}_{speaker}.vtt"

    encoded_name = quote(download_name, safe="")
    return Response(
        content=vtt_content,
        media_type="text/vtt",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


@router.get("/{job_id}/media")
async def get_media(job_id: str, session: AsyncSession = Depends(get_session)):
    """Serve the original uploaded media file for audio playback."""
    job = await _get_job_or_404(session, job_id)

    # Find uploaded file
    media_path = None
    for f in settings.uploads_dir.glob(f"{job.id}.*"):
        media_path = f
        break
    if not media_path or not media_path.exists():
        raise media_not_found()

    ext = media_path.suffix.lower()
    media_types = {
        ".mp4": "video/mp4",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".webm": "audio/webm",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
    }
    return FileResponse(media_path, media_type=media_types.get(ext, "application/octet-stream"))


@router.post("/{job_id}/generate-meta")
async def generate_meta(
    job_id: str,
    request: Request,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: AsyncSession = Depends(get_session),
):
    """Generate YouTube metadata with optional custom prompt."""
    job = await _get_job_or_404(session, job_id)
    _require_srt(job)

    custom_prompt = None
    fixed_footer = ""
    use_tone_ref = True
    override_provider = None
    override_model = None
    try:
        body = await request.json()
        custom_prompt = body.get("custom_prompt")
        fixed_footer = body.get("fixed_footer", "")
        use_tone_ref = body.get("use_tone_ref", True)
        override_provider = body.get("provider")
        override_model = body.get("model")
    except Exception:
        pass

    tone_references = await _get_tone_references(session) if use_tone_ref else None

    background_tasks.add_task(
        _generate_meta_job, job_id, custom_prompt, fixed_footer, tone_references, override_provider, override_model
    )
    return {"status": "generating_metadata"}


async def _get_tone_references(session: AsyncSession) -> str | None:
    """Fetch tone references from settings, or None if empty."""
    from src.models import Setting

    result = await session.execute(select(Setting).where(Setting.key == "tone_references"))
    setting = result.scalar_one_or_none()
    if setting and setting.value and setting.value.strip():
        return setting.value.strip()
    return None


@router.post("/{job_id}/optimize-prompt")
async def optimize_prompt(
    job_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Use LLM to optimize the metadata generation prompt."""
    from src.services.metadata import optimize_meta_prompt
    from src.services.transcribe import _get_credential, _get_model

    job = await _get_job_or_404(session, job_id)
    body = await request.json()
    context = body.get("context", {})
    current_prompt = body.get("current_prompt", "")
    use_tone_ref = body.get("use_tone_ref", True)

    override_provider = body.get("provider")
    override_model = body.get("model")

    tone_references = await _get_tone_references(session) if use_tone_ref else None

    provider = _normalize_provider(override_provider) or job.provider
    api_key = await _get_credential(session, provider)
    model = override_model or await _get_model(session, provider)

    optimized = await optimize_meta_prompt(
        current_prompt,
        context,
        api_key,
        get_provider_name(provider),
        model,
        tone_references,
    )
    return {"optimized_prompt": optimized}


async def _generate_meta_job(
    job_id: str,
    custom_prompt: str | None = None,
    fixed_footer: str = "",
    tone_references: str | None = None,
    override_provider: str | None = None,
    override_model: str | None = None,
) -> None:
    """Background task: generate YouTube metadata from existing SRT."""
    from src.services.transcribe import _get_credential, _get_model, _run_metadata_generation

    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job or not job.srt_path:
            return

        try:
            job.status = "generating_metadata"
            await session.commit()

            provider = _normalize_provider(override_provider) or job.provider
            srt_content = Path(job.srt_path).read_text(encoding="utf-8")
            api_key = await _get_credential(session, provider)
            model = override_model or await _get_model(session, provider)
            await _run_metadata_generation(job, session, srt_content, api_key, custom_prompt, tone_references, model)

            # Append fixed footer to description (not processed by AI)
            if fixed_footer and fixed_footer.strip() and job.youtube_description:
                job.youtube_description = job.youtube_description.rstrip() + "\n\n" + fixed_footer.strip()
                await session.commit()

            job.status = STATUS_COMPLETED
            await session.commit()
            logger.info("Metadata generated for job %s", job_id)
        except Exception as e:
            logger.exception("Metadata generation failed for job %s", job_id)
            job.status = STATUS_FAILED
            job.error_message = f"Metadata generation failed: {str(e)[:400]}"
            await session.commit()


@router.post("/{job_id}/generate-catchphrase")
async def generate_catchphrase_endpoint(
    job_id: str,
    request: Request,
    regenerate: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """Generate or retrieve thumbnail catchphrase suggestions."""
    import json as json_mod

    from src.services.catchphrase import generate_catchphrases
    from src.services.cost import estimate_llm_cost, log_cost
    from src.services.transcribe import _get_credential, _get_model

    job = await _get_job_or_404(session, job_id)
    _require_srt(job)

    # Return cached if available and not regenerating
    if job.catchphrases and not regenerate:
        return {"catchphrases": json_mod.loads(job.catchphrases), "cached": True}

    # Parse optional provider/model override
    override_provider = None
    override_model = None
    try:
        body = await request.json()
        override_provider = body.get("provider")
        override_model = body.get("model")
    except Exception:
        pass

    try:
        provider = _normalize_provider(override_provider) or job.provider
        srt_content = Path(job.srt_path).read_text(encoding="utf-8")
        api_key = await _get_credential(session, provider)
        model = override_model or await _get_model(session, provider)
        provider_name = get_provider_name(provider)

        phrases, input_tokens, output_tokens = await generate_catchphrases(srt_content, api_key, provider_name, model)

        # Save to DB
        job.catchphrases = json_mod.dumps(phrases, ensure_ascii=False)
        await session.commit()

        cost = estimate_llm_cost(input_tokens, output_tokens, model, provider_name)
        await log_cost(
            session,
            job.id,
            provider_name,
            model,
            "catchphrase_generation",
            cost,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        return {"catchphrases": phrases}
    except Exception as e:
        logger.exception("Catchphrase generation failed for job %s", job_id)
        return {"catchphrases": None, "error": str(e)[:300]}


@router.post("/{job_id}/generate-quiz")
async def generate_quiz_endpoint(
    job_id: str,
    request: Request,
    regenerate: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """Generate or retrieve YouTube quiz."""
    import json as json_mod

    from src.services.cost import estimate_llm_cost, log_cost
    from src.services.quiz import generate_quiz
    from src.services.transcribe import _get_credential, _get_model

    job = await _get_job_or_404(session, job_id)
    _require_srt(job)

    # Return cached if available and not regenerating
    if job.quiz and not regenerate:
        return {"quiz": json_mod.loads(job.quiz), "cached": True}

    # Parse optional provider/model override
    override_provider = None
    override_model = None
    try:
        body = await request.json()
        override_provider = body.get("provider")
        override_model = body.get("model")
    except Exception:
        pass

    try:
        provider = _normalize_provider(override_provider) or job.provider
        srt_content = Path(job.srt_path).read_text(encoding="utf-8")
        api_key = await _get_credential(session, provider)
        model = override_model or await _get_model(session, provider)
        provider_name = get_provider_name(provider)

        quiz, input_tokens, output_tokens = await generate_quiz(srt_content, api_key, provider_name, model)

        # Save to DB
        job.quiz = json_mod.dumps(quiz, ensure_ascii=False)
        await session.commit()

        cost = estimate_llm_cost(input_tokens, output_tokens, model, provider_name)
        await log_cost(
            session,
            job.id,
            provider_name,
            model,
            "quiz_generation",
            cost,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        return {"quiz": quiz}
    except Exception as e:
        logger.exception("Quiz generation failed for job %s", job_id)
        return {"quiz": None, "error": str(e)[:300]}


@router.get("/{job_id}/segments")
async def get_segments(job_id: str, session: AsyncSession = Depends(get_session)):
    """Get parsed SRT segments with verification highlights."""
    import json as json_mod

    from src.services.srt import parse_srt

    job = await _get_job_or_404(session, job_id)
    srt_file = _resolve_srt_file(job)

    content = srt_file.read_text(encoding="utf-8")
    segments = parse_srt(content)

    verified_indices = json_mod.loads(job.verified_indices) if job.verified_indices else []
    verify_reasons = json_mod.loads(job.verify_reasons) if job.verify_reasons else {}

    return {
        "segments": segments,
        "verified_indices": verified_indices,
        "verify_reasons": verify_reasons,
        "glossary": job.glossary or "",
        "speakers": json_mod.loads(job.speakers) if job.speakers else [],
        "speaker_map": json_mod.loads(job.speaker_map) if job.speaker_map else {},
    }


@router.put("/{job_id}/segments")
async def update_segments(job_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    """Update SRT file from edited segments."""
    from src.services.srt import generate_srt, save_srt

    job = await _get_job_or_404(session, job_id)
    _require_srt(job)

    body = await request.json()
    segments = body.get("segments", [])
    if not segments or not isinstance(segments, list):
        raise no_segments_provided()

    # Validate segment structure and timing
    previous_end = None
    for i, seg in enumerate(segments):
        if not isinstance(seg, dict) or "start" not in seg or "end" not in seg or "text" not in seg:
            raise invalid_segment(i)
        try:
            start = float(seg["start"])
            end = float(seg["end"])
        except (TypeError, ValueError):
            raise segment_timing_invalid(i + 1)
        if start >= end:
            raise segment_time_order(i + 1)
        if previous_end is not None and start < previous_end:
            raise segment_overlap(i + 1)
        previous_end = end

    srt_content = generate_srt(segments)
    srt_path = Path(job.srt_path).resolve()
    save_srt(srt_content, srt_path)

    return {"status": "saved", "segment_count": len(segments)}


@router.put("/{job_id}/glossary")
async def update_job_glossary(job_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    """Update the job-specific glossary."""
    job = await _get_job_or_404(session, job_id)
    body = await request.json()
    glossary = body.get("glossary", "")
    if len(glossary) > 5000:
        raise glossary_too_long()
    job.glossary = glossary.strip() if glossary else None
    await session.commit()
    return {"saved": True}


@router.put("/{job_id}/speakers")
async def update_speakers(job_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    """Update speaker list and per-segment speaker assignments."""
    import json as json_mod

    job = await _get_job_or_404(session, job_id)
    body = await request.json()
    speakers = body.get("speakers", [])
    speaker_map = body.get("speaker_map", {})
    job.speakers = json_mod.dumps(speakers, ensure_ascii=False) if speakers else None
    job.speaker_map = json_mod.dumps(speaker_map, ensure_ascii=False) if speaker_map else None
    await session.commit()
    return {"saved": True}


@router.post("/{job_id}/segments/{index}/suggest")
async def suggest_segment_endpoint(
    job_id: str,
    index: int,
    session: AsyncSession = Depends(get_session),
):
    """Get AI suggestion for a single segment."""
    from src.services.cost import estimate_llm_cost, log_cost
    from src.services.refine import suggest_segment
    from src.services.srt import parse_srt
    from src.services.transcribe import _get_credential, _get_model

    job = await _get_job_or_404(session, job_id)
    srt_file = _resolve_srt_file(job)

    content = srt_file.read_text(encoding="utf-8")
    segments = parse_srt(content)

    if index < 0 or index >= len(segments):
        raise invalid_segment_index(index)

    api_key = await _get_credential(session, job.provider)
    model = await _get_model(session, job.provider)
    provider_name = get_provider_name(job.provider)

    # Merge global glossary + job glossary from DB
    from src.models import Setting

    result = await session.execute(select(Setting).where(Setting.key == "glossary"))
    glossary_setting = result.scalar_one_or_none()
    global_glossary = glossary_setting.value if glossary_setting else ""
    job_glossary = job.glossary or ""
    combined_glossary = "\n".join(filter(None, [global_glossary.strip(), job_glossary.strip()]))

    # Context: 5 segments before/after
    ctx_before = segments[max(0, index - 5) : index]
    ctx_after = segments[index + 1 : index + 6]

    suggested, reason, input_tokens, output_tokens = await suggest_segment(
        segments[index],
        ctx_before,
        ctx_after,
        api_key,
        provider_name,
        model,
        combined_glossary,
    )

    cost = estimate_llm_cost(input_tokens, output_tokens, model, provider_name)
    await log_cost(
        session,
        job.id,
        provider_name,
        model,
        "suggestion",
        cost,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

    return {"text": suggested, "reason": reason}


@router.delete("/{job_id}")
async def delete_job(job_id: str, session: AsyncSession = Depends(get_session)):
    job = await _get_job_or_404(session, job_id)

    # Delete DB record first, then clean up files
    await session.delete(job)
    await session.commit()

    # Clean up files (best effort)
    for path_str in [job.srt_path]:
        if path_str:
            Path(path_str).unlink(missing_ok=True)

    # Clean up upload and audio files (any extension)
    for d in [settings.uploads_dir, settings.audio_dir]:
        for f in d.glob(f"{job.id}.*"):
            f.unlink(missing_ok=True)

    return {"deleted": True}
