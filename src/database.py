from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.config import settings


def utcnow() -> datetime:
    """UTC timestamp for model defaults."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.db_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    for d in [
        settings.data_dir / "db",
        settings.uploads_dir,
        settings.audio_dir,
        settings.srt_dir,
        settings.output_dir,
        settings.assets_dir,
    ]:
        d.mkdir(parents=True, exist_ok=True)

    # Run Alembic migrations (creates tables + applies schema changes)
    from alembic.config import Config

    from alembic import command

    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")

    # Load custom pricing from DB
    from src.services.cost import load_pricing_from_db

    async with async_session() as session:
        await load_pricing_from_db(session)


async def get_session():
    async with async_session() as session:
        yield session
