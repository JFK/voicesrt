import logging
import re
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import async_session, get_session
from src.models import Job
from src.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

MAX_UPLOAD_SIZE = settings.max_upload_size_gb * 1024 * 1024 * 1024

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
            job.status = "failed"
            job.error_message = str(e)[:500]
            await session.commit()


async def _embed_job(job_id: str, do_srt: bool, do_logo: bool) -> None:
    """Background task: embed subtitles and/or logo into video."""
    from src.services.video_edit import embed_video

    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return
        try:
            job.status = "editing_video"
            await session.commit()
            output_path = await embed_video(job, do_srt, do_logo)
            job.output_video_path = str(output_path)
            job.status = "completed"
            await session.commit()
        except Exception as e:
            logger.exception("Video embedding failed for job %s", job_id)
            job.status = "failed"
            job.error_message = f"Video editing failed: {str(e)[:400]}"
            await session.commit()


@router.post("")
async def create_job(
    file: UploadFile,
    provider: str = "whisper",
    language: str | None = None,
    enable_metadata: bool = False,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: AsyncSession = Depends(get_session),
):
    if not file.filename or not file.filename.lower().endswith(".mp4"):
        raise HTTPException(status_code=400, detail="Only MP4 files are supported")

    job_id = str(uuid.uuid4())
    upload_path = settings.uploads_dir / f"{job_id}.mp4"
    upload_path.parent.mkdir(parents=True, exist_ok=True)

    # Stream file to disk to handle large files without OOM
    file_size = 0
    try:
        async with aiofiles.open(upload_path, "wb") as out:
            while chunk := await file.read(8 * 1024 * 1024):  # 8MB chunks
                file_size += len(chunk)
                if file_size > MAX_UPLOAD_SIZE:
                    await out.close()
                    upload_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail=f"File too large. Max size is {MAX_UPLOAD_SIZE // (1024**3)}GB")
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
        "output_video_path": job.output_video_path,
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
        return templates.TemplateResponse("partials/job_status.html", {"request": request, "job": job})

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


@router.get("/{job_id}/download-video")
async def download_video(job_id: str, session: AsyncSession = Depends(get_session)):
    job = await _get_job_or_404(session, job_id)
    if not job.output_video_path:
        raise HTTPException(status_code=404, detail="Edited video not found")

    video_file = Path(job.output_video_path).resolve()
    if not video_file.exists():
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    download_name = Path(_safe_filename(job.filename)).stem + "_subtitled.mp4"
    return FileResponse(video_file, filename=download_name, media_type="video/mp4")


@router.post("/{job_id}/embed")
async def embed_subtitles(
    job_id: str,
    embed_srt: bool = True,
    embed_logo: bool = False,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: AsyncSession = Depends(get_session),
):
    """Start video editing (subtitle embedding + logo overlay)."""
    job = await _get_job_or_404(session, job_id)
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job must be completed before embedding")
    if not job.srt_path:
        raise HTTPException(status_code=400, detail="No SRT file available")

    background_tasks.add_task(_embed_job, job_id, embed_srt, embed_logo)
    return {"status": "editing_video"}


@router.delete("/{job_id}")
async def delete_job(job_id: str, session: AsyncSession = Depends(get_session)):
    job = await _get_job_or_404(session, job_id)

    # Delete DB record first, then clean up files
    await session.delete(job)
    await session.commit()

    # Clean up files (best effort)
    for path_str in [job.srt_path, job.output_video_path]:
        if path_str:
            Path(path_str).unlink(missing_ok=True)

    for pattern in [f"{job.id}.mp4", f"{job.id}.wav", f"{job.id}.mp3"]:
        for d in [settings.uploads_dir, settings.audio_dir]:
            (d / pattern).unlink(missing_ok=True)

    return {"deleted": True}
