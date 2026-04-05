import os
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

# Set test encryption key before importing app modules
os.environ["ENCRYPTION_KEY"] = "dGVzdC1lbmNyeXB0aW9uLWtleS0xMjM0NTY3ODkwMTI="

from src.database import ensure_dirs, run_migrations  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _reset_db():
    """Remove existing test DB so each test run starts fresh."""
    db_path = Path("data/db/voicesrt.db")
    for suffix in ("", "-wal", "-shm"):
        (db_path.parent / (db_path.name + suffix)).unlink(missing_ok=True)


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
    _reset_db()
    ensure_dirs()
    run_migrations()
    port = _free_port()
    server = _Server(port)
    server.start()
    yield port
    server.stop()


@pytest.fixture(scope="session")
def base_url(_e2e_server):
    """Base URL for the running test server (overrides pytest-playwright's base_url)."""
    return f"http://127.0.0.1:{_e2e_server}"
