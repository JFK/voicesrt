import logging
import re
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.constants import STATUS_COMPLETED, STATUS_FAILED, get_provider_name
from src.database import async_session, get_session
from src.models import Job
from src.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

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
        raise HTTPException(status_code=404, detail="Job not found")
    return job


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
            logger.exception("Job %s failed", job_id)
            job.status = STATUS_FAILED
            job.error_message = str(e)[:500]
            await session.commit()


VALID_REFINE_MODES = {"verbatim", "standard", "caption"}


@router.post("")
async def create_job(
    file: UploadFile,
    provider: str = "whisper",
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
        raise HTTPException(status_code=400, detail="Glossary too long. Max 5000 characters.")

    if refine_mode and refine_mode not in VALID_REFINE_MODES:
        valid = ", ".join(VALID_REFINE_MODES)
        raise HTTPException(status_code=400, detail=f"Invalid refine_mode. Must be one of: {valid}")

    supported = {".mp4", ".mp3", ".wav", ".mov", ".avi", ".mkv", ".m4a", ".flac", ".ogg", ".webm"}
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    ext = Path(file.filename).suffix.lower()
    if ext not in supported:
        fmts = ", ".join(sorted(supported))
        raise HTTPException(status_code=400, detail=f"Unsupported format. Supported: {fmts}")

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
                    raise HTTPException(status_code=413, detail=f"File too large. Max: {max_gb}GB")
                await out.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        upload_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

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
async def download_srt(job_id: str, session: AsyncSession = Depends(get_session)):
    job = await _get_job_or_404(session, job_id)
    if not job.srt_path:
        raise HTTPException(status_code=404, detail="SRT file not found")

    srt_file = Path(job.srt_path).resolve()
    if not srt_file.exists():
        raise HTTPException(status_code=404, detail="SRT file not found on disk")

    download_name = Path(_safe_filename(job.filename)).stem + ".srt"
    return FileResponse(srt_file, filename=download_name, media_type="text/plain")


@router.get("/{job_id}/download-vtt")
async def download_vtt(job_id: str, session: AsyncSession = Depends(get_session)):
    job = await _get_job_or_404(session, job_id)
    if not job.srt_path:
        raise HTTPException(status_code=404, detail="SRT file not found")

    srt_file = Path(job.srt_path).resolve()
    if not srt_file.exists():
        raise HTTPException(status_code=404, detail="SRT file not found on disk")

    from src.services.srt import srt_to_vtt

    srt_content = srt_file.read_text(encoding="utf-8")
    vtt_content = srt_to_vtt(srt_content)
    download_name = Path(_safe_filename(job.filename)).stem + ".vtt"

    from fastapi.responses import Response

    return Response(
        content=vtt_content,
        media_type="text/vtt",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
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
        raise HTTPException(status_code=404, detail="Media file not found")

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


@router.post("/{job_id}/re-refine")
async def re_refine(
    job_id: str,
    request: Request,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: AsyncSession = Depends(get_session),
):
    """Re-run LLM refinement on existing SRT."""
    job = await _get_job_or_404(session, job_id)
    if not job.srt_path:
        raise HTTPException(status_code=400, detail="No SRT file available")

    glossary = None
    try:
        body = await request.json()
        glossary = body.get("glossary")
    except Exception:
        pass

    background_tasks.add_task(_re_refine_job, job_id, glossary)
    return {"status": "refining"}


async def _re_refine_job(job_id: str, custom_glossary: str | None = None) -> None:
    """Background task: re-refine existing SRT."""
    from src.services.srt import generate_srt, parse_srt, save_srt
    from src.services.transcribe import _get_credential, _run_refinement, _run_verification

    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job or not job.srt_path:
            return

        try:
            job.status = "refining"
            job.error_message = None
            await session.commit()

            srt_content = Path(job.srt_path).read_text(encoding="utf-8")
            segments = parse_srt(srt_content)

            # Use custom glossary if provided, otherwise merge global + job glossary
            if custom_glossary is not None:
                glossary = custom_glossary
            else:
                from src.models import Setting

                r = await session.execute(select(Setting).where(Setting.key == "glossary"))
                gs = r.scalar_one_or_none()
                global_glossary = gs.value if gs else ""
                job_glossary = job.glossary or ""
                glossary = "\n".join(filter(None, [global_glossary.strip(), job_glossary.strip()]))

            api_key = await _get_credential(session, job.provider)

            segments = await _run_refinement(job, session, segments, api_key, glossary)

            # Verify if enabled
            if job.enable_verify:
                import json

                job.status = "verifying"
                await session.commit()
                segments, changed_indices, reasons = await _run_verification(job, session, segments, api_key, glossary)
                job.verified_indices = json.dumps(changed_indices)
                job.verify_reasons = json.dumps(reasons, ensure_ascii=False)

            # Save updated SRT
            srt_content = generate_srt(segments)
            save_srt(srt_content, Path(job.srt_path))

            job.status = STATUS_COMPLETED
            await session.commit()
            logger.info("Re-refine completed for job %s", job_id)
        except Exception as e:
            logger.exception("Re-refine failed for job %s", job_id)
            job.status = STATUS_COMPLETED
            job.error_message = f"Re-refine failed: {str(e)[:400]}"
            await session.commit()


@router.post("/{job_id}/generate-meta")
async def generate_meta(
    job_id: str,
    request: Request,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: AsyncSession = Depends(get_session),
):
    """Generate YouTube metadata with optional custom prompt."""
    job = await _get_job_or_404(session, job_id)
    if not job.srt_path:
        raise HTTPException(status_code=400, detail="No SRT file available")

    custom_prompt = None
    fixed_footer = ""
    use_tone_ref = True
    try:
        body = await request.json()
        custom_prompt = body.get("custom_prompt")
        fixed_footer = body.get("fixed_footer", "")
        use_tone_ref = body.get("use_tone_ref", True)
    except Exception:
        pass

    tone_references = await _get_tone_references(session) if use_tone_ref else None

    background_tasks.add_task(_generate_meta_job, job_id, custom_prompt, fixed_footer, tone_references)
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

    tone_references = await _get_tone_references(session) if use_tone_ref else None

    api_key = await _get_credential(session, job.provider)
    model = await _get_model(session, job.provider)

    optimized = await optimize_meta_prompt(
        current_prompt,
        context,
        api_key,
        get_provider_name(job.provider),
        model,
        tone_references,
    )
    return {"optimized_prompt": optimized}


async def _generate_meta_job(
    job_id: str,
    custom_prompt: str | None = None,
    fixed_footer: str = "",
    tone_references: str | None = None,
) -> None:
    """Background task: generate YouTube metadata from existing SRT."""
    from src.services.transcribe import _get_credential, _run_metadata_generation

    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job or not job.srt_path:
            return

        try:
            job.status = "generating_metadata"
            await session.commit()

            srt_content = Path(job.srt_path).read_text(encoding="utf-8")
            api_key = await _get_credential(session, job.provider)
            await _run_metadata_generation(job, session, srt_content, api_key, custom_prompt, tone_references)

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
    regenerate: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """Generate or retrieve thumbnail catchphrase suggestions."""
    import json as json_mod

    from src.services.catchphrase import generate_catchphrases
    from src.services.cost import estimate_llm_cost, log_cost
    from src.services.transcribe import _get_credential, _get_model

    job = await _get_job_or_404(session, job_id)
    if not job.srt_path:
        raise HTTPException(status_code=400, detail="No SRT file available")

    # Return cached if available and not regenerating
    if job.catchphrases and not regenerate:
        return {"catchphrases": json_mod.loads(job.catchphrases), "cached": True}

    try:
        srt_content = Path(job.srt_path).read_text(encoding="utf-8")
        api_key = await _get_credential(session, job.provider)
        model = await _get_model(session, job.provider)
        provider_name = get_provider_name(job.provider)

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
    regenerate: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """Generate or retrieve YouTube quiz."""
    import json as json_mod

    from src.services.cost import estimate_llm_cost, log_cost
    from src.services.quiz import generate_quiz
    from src.services.transcribe import _get_credential, _get_model

    job = await _get_job_or_404(session, job_id)
    if not job.srt_path:
        raise HTTPException(status_code=400, detail="No SRT file available")

    # Return cached if available and not regenerating
    if job.quiz and not regenerate:
        return {"quiz": json_mod.loads(job.quiz), "cached": True}

    try:
        srt_content = Path(job.srt_path).read_text(encoding="utf-8")
        api_key = await _get_credential(session, job.provider)
        model = await _get_model(session, job.provider)
        provider_name = get_provider_name(job.provider)

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
    if not job.srt_path:
        raise HTTPException(status_code=404, detail="SRT file not found")

    srt_file = Path(job.srt_path).resolve()
    if not srt_file.exists():
        raise HTTPException(status_code=404, detail="SRT file not found on disk")

    content = srt_file.read_text(encoding="utf-8")
    segments = parse_srt(content)

    verified_indices = json_mod.loads(job.verified_indices) if job.verified_indices else []
    verify_reasons = json_mod.loads(job.verify_reasons) if job.verify_reasons else {}

    return {
        "segments": segments,
        "verified_indices": verified_indices,
        "verify_reasons": verify_reasons,
        "glossary": job.glossary or "",
    }


@router.put("/{job_id}/segments")
async def update_segments(job_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    """Update SRT file from edited segments."""
    from src.services.srt import generate_srt, save_srt

    job = await _get_job_or_404(session, job_id)
    if not job.srt_path:
        raise HTTPException(status_code=400, detail="No SRT file available")

    body = await request.json()
    segments = body.get("segments", [])
    if not segments or not isinstance(segments, list):
        raise HTTPException(status_code=400, detail="No segments provided")

    # Validate segment structure
    for i, seg in enumerate(segments):
        if not isinstance(seg, dict) or "start" not in seg or "end" not in seg or "text" not in seg:
            raise HTTPException(status_code=400, detail=f"Invalid segment at index {i}")

    srt_content = generate_srt(segments)
    srt_path = Path(job.srt_path).resolve()
    save_srt(srt_content, srt_path)

    return {"status": "saved", "segment_count": len(segments)}


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
    if not job.srt_path:
        raise HTTPException(status_code=400, detail="No SRT file available")

    srt_file = Path(job.srt_path).resolve()
    if not srt_file.exists():
        raise HTTPException(status_code=404, detail="SRT file not found on disk")

    content = srt_file.read_text(encoding="utf-8")
    segments = parse_srt(content)

    if index < 0 or index >= len(segments):
        raise HTTPException(status_code=400, detail=f"Invalid segment index: {index}")

    api_key = await _get_credential(session, job.provider)
    model = await _get_model(session, job.provider)
    provider_name = get_provider_name(job.provider)

    # Get glossary
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
