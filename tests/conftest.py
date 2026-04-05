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
