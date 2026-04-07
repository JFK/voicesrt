import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.database import init_db
from src.errors import AppError

logger = logging.getLogger(__name__)


async def _warn_on_default_model_drift() -> None:
    """At startup, warn (non-fatal) if a configured default LLM model is missing
    from its provider's catalog. Skips silently when keys aren't configured."""
    import asyncio

    from sqlalchemy import select

    from src.config import settings
    from src.constants import KEY_API_GOOGLE, KEY_API_OPENAI
    from src.database import async_session
    from src.models import Setting
    from src.services.crypto import decrypt
    from src.services.model_validator import ModelNotAvailableError, validate_model

    async def _check_one(db_key: str, api_provider: str, model: str) -> None:
        async with async_session() as session:
            row = (await session.execute(select(Setting).where(Setting.key == db_key))).scalar_one_or_none()
        if row is None:
            return
        try:
            api_key = decrypt(row.value)
        except Exception:
            return
        try:
            await validate_model(api_provider, model, api_key)
        except ModelNotAvailableError:
            logger.warning(
                "Default %s model %r is not in the provider catalog — "
                "users will see MODEL_NOT_AVAILABLE until they pick a valid one in Settings.",
                api_provider,
                model,
            )
        except Exception as e:
            logger.debug("Startup model check for %s skipped: %s", api_provider, e)

    await asyncio.gather(
        _check_one(KEY_API_OPENAI, "openai", settings.default_openai_model),
        _check_one(KEY_API_GOOGLE, "gemini", settings.default_gemini_model),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    try:
        await _warn_on_default_model_drift()
    except Exception as e:
        logger.debug("Default-model drift check failed: %s", e)
    yield


app = FastAPI(title="VoiceSRT", lifespan=lifespan)


@app.exception_handler(AppError)
async def app_error_handler(request, exc: AppError):
    error: dict = {"code": exc.code, "message": exc.message}
    if getattr(exc, "payload", None):
        error.update(exc.payload)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": error},
        headers=getattr(exc, "headers", None),
    )


# Static files
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Register routers
from src.api.costs import router as costs_router  # noqa: E402
from src.api.jobs import router as jobs_router  # noqa: E402
from src.api.pages import router as pages_router  # noqa: E402
from src.api.settings import router as settings_router  # noqa: E402

app.include_router(pages_router)
app.include_router(jobs_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(costs_router, prefix="/api")
