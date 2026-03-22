import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import async_session, get_session
from src.models import Job

router = APIRouter(prefix="/jobs", tags=["jobs"])


async def _process_job(job_id: str) -> None:
    """Background task: extract audio → transcribe → generate metadata."""
    from src.services.transcribe import process_transcription

    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return

        try:
            await process_transcription(job, session)
        except Exception as e:
            job.status = "failed"
            job.error_message = str(e)
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

    content = await file.read()
    upload_path.write_bytes(content)

    job = Job(
        id=job_id,
        filename=file.filename,
        file_size=len(content),
        provider=provider,
        language=language,
        enable_metadata=enable_metadata,
    )
    session.add(job)
    await session.commit()

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
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
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
async def get_job_status(job_id: str, request=None, session: AsyncSession = Depends(get_session)):
    """HTMX partial for polling job status."""
    from src.templating import templates

    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if request and request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/job_status.html", {"request": request, "job": job})

    return {"status": job.status, "error_message": job.error_message}


@router.get("/{job_id}/download")
async def download_srt(job_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job or not job.srt_path:
        raise HTTPException(status_code=404, detail="SRT file not found")

    srt_file = Path(job.srt_path)
    if not srt_file.exists():
        raise HTTPException(status_code=404, detail="SRT file not found on disk")

    download_name = Path(job.filename).stem + ".srt"
    return FileResponse(srt_file, filename=download_name, media_type="text/plain")


@router.get("/{job_id}/download-video")
async def download_video(job_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job or not job.output_video_path:
        raise HTTPException(status_code=404, detail="Edited video not found")

    video_file = Path(job.output_video_path)
    if not video_file.exists():
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    download_name = Path(job.filename).stem + "_subtitled.mp4"
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
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job must be completed before embedding")
    if not job.srt_path:
        raise HTTPException(status_code=400, detail="No SRT file available")

    async def _embed(jid: str, do_srt: bool, do_logo: bool):
        from src.services.video_edit import embed_video

        async with async_session() as s:
            r = await s.execute(select(Job).where(Job.id == jid))
            j = r.scalar_one()
            try:
                j.status = "editing_video"
                await s.commit()
                output_path = await embed_video(j, do_srt, do_logo)
                j.output_video_path = str(output_path)
                j.status = "completed"
                await s.commit()
            except Exception as e:
                j.status = "failed"
                j.error_message = f"Video editing failed: {e}"
                await s.commit()

    background_tasks.add_task(_embed, job_id, embed_srt, embed_logo)
    return {"status": "editing_video"}


@router.delete("/{job_id}")
async def delete_job(job_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Clean up files
    for path_str in [job.srt_path, job.output_video_path]:
        if path_str:
            p = Path(path_str)
            if p.exists():
                p.unlink()

    upload_file = settings.uploads_dir / f"{job_id}.mp4"
    if upload_file.exists():
        upload_file.unlink()

    audio_file = settings.audio_dir / f"{job_id}.wav"
    if audio_file.exists():
        audio_file.unlink()

    await session.delete(job)
    await session.commit()
    return {"deleted": True}
