from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import Job
from src.services.crypto import EncryptionService
from src.templating import get_lang, get_translator, templates

router = APIRouter()


def _i18n_context(request: Request) -> dict:
    """Build i18n context vars for templates."""
    lang = get_lang(request)
    return {"t": get_translator(lang), "lang": lang}


async def _has_api_keys(session: AsyncSession) -> bool:
    has_decryptable, _ = await EncryptionService(session).api_key_status()
    return has_decryptable


@router.get("/")
async def landing_page(request: Request, session: AsyncSession = Depends(get_session)):
    if not await _has_api_keys(session):
        return RedirectResponse("/setup")
    # Preserve bookmarked job-restore links: /?job=xxx -> /upload?job=xxx
    if request.query_params.get("job"):
        return RedirectResponse(f"/upload?{request.query_params}")
    return templates.TemplateResponse(request, "landing.html", {"active_page": "landing", **_i18n_context(request)})


@router.get("/upload")
async def upload_page(request: Request, session: AsyncSession = Depends(get_session)):
    if not await _has_api_keys(session):
        return RedirectResponse("/setup")
    return templates.TemplateResponse(request, "upload.html", {"active_page": "upload", **_i18n_context(request)})


@router.get("/setup")
async def setup_page(request: Request, session: AsyncSession = Depends(get_session)):
    # `has_undecryptable_keys` names what we actually measure (≥1 api_key.%
    # row fails to decrypt) rather than calling it "key_mismatch" — that
    # name belongs to the fingerprint-based signal in /api/settings/keys,
    # which is strictly stronger. The /setup banner uses the looser signal
    # so that single-row corruption still surfaces the recovery flow, not
    # just full-key rotation.
    service = EncryptionService(session)
    _, has_undecryptable_keys = await service.api_key_status()
    # First-run vs returning-user signal: when the fingerprint row has never
    # been stamped, this is a fresh install — show the ENCRYPTION_KEY backup
    # warning. After the first save_key, the row exists and the banner stops
    # showing on subsequent setup-page visits (e.g. partial-recovery flows).
    has_stamped_fingerprint = (await service.get_stored_fingerprint()) is not None
    ctx = {
        "active_page": "settings",
        "has_undecryptable_keys": has_undecryptable_keys,
        "has_stamped_fingerprint": has_stamped_fingerprint,
        **_i18n_context(request),
    }
    return templates.TemplateResponse(request, "setup.html", ctx)


@router.get("/history")
async def history_page(request: Request, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Job).order_by(Job.created_at.desc()).limit(100))
    jobs = result.scalars().all()
    ctx = {"active_page": "history", "jobs": jobs, **_i18n_context(request)}
    return templates.TemplateResponse(request, "history.html", ctx)


@router.get("/meta/{job_id}")
async def meta_editor_page(job_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        return RedirectResponse("/history")
    ctx = {"active_page": "history", "job": job, **_i18n_context(request)}
    return templates.TemplateResponse(request, "meta_editor.html", ctx)


@router.get("/srt/{job_id}")
async def srt_editor_page(job_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        return RedirectResponse("/history")
    is_streaming = job.enable_refine and not job.enable_verify and not job.srt_path
    ctx = {"active_page": "history", "job": job, "is_streaming": is_streaming, **_i18n_context(request)}
    return templates.TemplateResponse(request, "srt_editor.html", ctx)


@router.get("/costs")
async def costs_page(request: Request):
    return templates.TemplateResponse(request, "costs.html", {"active_page": "costs", **_i18n_context(request)})


@router.get("/settings")
async def settings_page(request: Request):
    return templates.TemplateResponse(request, "settings.html", {"active_page": "settings", **_i18n_context(request)})


@router.get("/lang/{code}")
async def switch_lang(code: str, request: Request):
    """Switch UI language via cookie."""
    referer = request.headers.get("referer", "/")
    response = RedirectResponse(referer)
    response.set_cookie("lang", code if code in ("en", "ja") else "en", max_age=365 * 24 * 3600)
    return response
