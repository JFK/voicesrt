from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import Job
from src.services.crypto import DecryptionError, decrypt_credential
from src.templating import get_lang, get_translator, templates

router = APIRouter()


def _i18n_context(request: Request) -> dict:
    """Build i18n context vars for templates."""
    lang = get_lang(request)
    return {"t": get_translator(lang), "lang": lang}


async def _api_key_status(session: AsyncSession) -> tuple[bool, bool]:
    """Return (has_decryptable, has_undecryptable) for stored api_key.% rows.

    A row is "undecryptable" when DecryptionError is raised — typically because
    ENCRYPTION_KEY was changed after the row was written. Both flags surface so
    callers can distinguish "no keys at all" from "keys exist but the active
    ENCRYPTION_KEY can't decrypt them" — the latter needs a user-visible warning,
    not a silent /setup redirect followed by a later crash in _get_credential().
    """
    from src.models import Setting

    result = await session.execute(select(Setting).where(Setting.key.like("api_key.%"), Setting.encrypted.is_(True)))
    has_decryptable = False
    has_undecryptable = False
    for row in result.scalars():
        # Fernet decrypt does signature verification — stop as soon as both
        # flags are set so request-path callers (landing, upload) don't burn
        # cycles on every additional row when the answer is already decided.
        if has_decryptable and has_undecryptable:
            break
        try:
            decrypt_credential(row.value)
            has_decryptable = True
        except DecryptionError:
            has_undecryptable = True
    return has_decryptable, has_undecryptable


async def _has_api_keys(session: AsyncSession) -> bool:
    has_decryptable, _ = await _api_key_status(session)
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
    _, key_mismatch = await _api_key_status(session)
    ctx = {"active_page": "settings", "key_mismatch": key_mismatch, **_i18n_context(request)}
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
