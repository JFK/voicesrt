from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.database import init_db
from src.errors import AppError


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="VoiceSRT", lifespan=lifespan)


@app.exception_handler(AppError)
async def app_error_handler(request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
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
