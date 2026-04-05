from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import Job
from src.templating import get_lang, get_translator, templates

router = APIRouter()


def _i18n_context(request: Request) -> dict:
    """Build i18n context vars for templates."""
    lang = get_lang(request)
    return {"t": get_translator(lang), "lang": lang}


@router.get("/")
async def upload_page(request: Request, session: AsyncSession = Depends(get_session)):
    from src.models import Setting

    result = await session.execute(select(Setting).where(Setting.key.like("api_key.%"), Setting.encrypted.is_(True)))
    has_keys = result.first() is not None
    if not has_keys:
        return RedirectResponse("/setup")
    return templates.TemplateResponse(request, "upload.html", {"active_page": "upload", **_i18n_context(request)})


@router.get("/setup")
async def setup_page(request: Request):
    return templates.TemplateResponse(request, "setup.html", {"active_page": "settings", **_i18n_context(request)})


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
    ctx = {"active_page": "history", "job": job, **_i18n_context(request)}
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
