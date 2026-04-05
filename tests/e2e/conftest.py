import os
import shutil
import socket
import tempfile
import threading
import time

import pytest
import uvicorn

# Use a temporary data directory so E2E tests never touch the dev DB
_tmp_data = tempfile.mkdtemp(prefix="voicesrt_e2e_")
os.environ["DATA_DIR"] = _tmp_data

# Set test encryption key before importing app modules
os.environ["ENCRYPTION_KEY"] = "dGVzdC1lbmNyeXB0aW9uLWtleS0xMjM0NTY3ODkwMTI="

from src.database import Base, engine, ensure_dirs  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _create_tables():
    """Create all tables synchronously (no alembic needed for E2E tests)."""
    import asyncio

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())


class _Server:
    """Uvicorn server that runs in a background thread."""

    def __init__(self, port: int):
        config = uvicorn.Config(
            "src.main:app",
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self):
        self.thread.start()
        while not self.server.started:
            time.sleep(0.05)

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)


@pytest.fixture(scope="session")
def _e2e_server():
    """Start a live server for the entire E2E test session."""
    ensure_dirs()
    _create_tables()
    port = _free_port()
    server = _Server(port)
    server.start()
    yield port
    server.stop()
    shutil.rmtree(_tmp_data, ignore_errors=True)


@pytest.fixture(scope="session")
def base_url(_e2e_server):
    """Base URL for the running test server (overrides pytest-playwright's base_url)."""
    return f"http://127.0.0.1:{_e2e_server}"
