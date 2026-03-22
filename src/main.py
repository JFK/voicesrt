from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="VideoSRT", lifespan=lifespan)

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
