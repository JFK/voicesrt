import os

import pytest
from httpx import ASGITransport, AsyncClient

# Set test encryption key before importing app modules
os.environ["ENCRYPTION_KEY"] = "dGVzdC1lbmNyeXB0aW9uLWtleS0xMjM0NTY3ODkwMTI="

from src.main import app  # noqa: E402


@pytest.fixture
def sample_segments():
    return [
        {"start": 0.0, "end": 2.5, "text": "Hello, welcome to the video."},
        {"start": 3.0, "end": 5.8, "text": "Today we will discuss Python."},
        {"start": 6.0, "end": 10.2, "text": "Let's get started."},
    ]


@pytest.fixture
def make_client():
    def _make():
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    return _make


@pytest.fixture(autouse=True, scope="session")
async def _seed_api_key():
    """Insert a dummy API key so GET / doesn't redirect to /setup in CI."""
    from sqlalchemy import select

    from src.database import async_session, engine
    from src.models import Setting
    from src.services.crypto import encrypt

    async with engine.begin() as conn:
        from src.database import Base

        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        result = await session.execute(select(Setting).where(Setting.key == "api_key.openai"))
        if result.first() is None:
            session.add(Setting(key="api_key.openai", value=encrypt("sk-test"), encrypted=True))
            await session.commit()
