"""Tests for model selection, provider normalization, and available-models API."""

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.jobs import _normalize_provider
from src.main import app
from src.services.utils import _resolve_ollama_url


@pytest.fixture
def make_client():
    def _make():
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    return _make


# ---------------------------------------------------------------------------
# _normalize_provider
# ---------------------------------------------------------------------------


def test_normalize_provider_openai():
    assert _normalize_provider("openai") == "whisper"


def test_normalize_provider_whisper():
    assert _normalize_provider("whisper") == "whisper"


def test_normalize_provider_gemini():
    assert _normalize_provider("gemini") == "gemini"


def test_normalize_provider_ollama():
    assert _normalize_provider("ollama") == "ollama"


def test_normalize_provider_none():
    assert _normalize_provider(None) is None


def test_normalize_provider_case_insensitive():
    assert _normalize_provider("OpenAI") == "whisper"
    assert _normalize_provider("GEMINI") == "gemini"


def test_normalize_provider_invalid():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        _normalize_provider("invalid")
    assert exc_info.value.status_code == 400


def test_normalize_provider_with_whitespace():
    assert _normalize_provider("  ollama  ") == "ollama"


# ---------------------------------------------------------------------------
# _resolve_ollama_url
# ---------------------------------------------------------------------------


def test_resolve_ollama_url_no_docker(monkeypatch):
    """Outside Docker, URLs pass through unchanged."""
    from pathlib import Path

    monkeypatch.setattr(Path, "exists", lambda self: False)
    assert _resolve_ollama_url("http://localhost:11434") == "http://localhost:11434"


def test_resolve_ollama_url_in_docker(monkeypatch):
    """Inside Docker, localhost is rewritten."""
    from pathlib import Path

    monkeypatch.setattr(Path, "exists", lambda self: True)
    assert _resolve_ollama_url("http://localhost:11434") == "http://host.docker.internal:11434"


def test_resolve_ollama_url_127(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(Path, "exists", lambda self: True)
    assert _resolve_ollama_url("http://127.0.0.1:11434") == "http://host.docker.internal:11434"


def test_resolve_ollama_url_no_port(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(Path, "exists", lambda self: True)
    assert _resolve_ollama_url("http://localhost/v1") == "http://host.docker.internal/v1"


def test_resolve_ollama_url_non_localhost(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(Path, "exists", lambda self: True)
    assert _resolve_ollama_url("http://myhost:11434") == "http://myhost:11434"


# ---------------------------------------------------------------------------
# Available models API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_available_models_endpoint(make_client, monkeypatch):
    """Mock httpx to avoid real Ollama network call."""
    import httpx

    class MockResponse:
        status_code = 200

        def json(self):
            return {"models": [{"name": "qwen3:8b"}]}

    original_get = httpx.AsyncClient.get

    async def mock_get(self, url, **kwargs):
        if "api/tags" in url:
            return MockResponse()
        return await original_get(self, url, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    async with make_client() as c:
        resp = await c.get("/api/settings/available-models")
    assert resp.status_code == 200
    data = resp.json()
    assert "available" in data
    assert "configured" in data
    assert "has_key" in data
    assert "openai" in data["available"]
    assert "gemini" in data["available"]
    assert "ollama" in data["available"]


# ---------------------------------------------------------------------------
# Segment validation edge cases
# ---------------------------------------------------------------------------


async def _create_test_job(make_client) -> str:
    async with make_client() as c:
        resp = await c.post(
            "/api/jobs?provider=whisper",
            files={"file": ("test.mp3", b"fake", "audio/mpeg")},
        )
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["id"]

    from src.config import settings

    srt_dir = settings.srt_dir
    srt_dir.mkdir(parents=True, exist_ok=True)
    srt_path = srt_dir / f"{job_id}.srt"
    srt_path.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n\n2\n00:00:02,000 --> 00:00:04,000\nWorld\n\n")

    from sqlalchemy import select

    from src.database import async_session
    from src.models import Job

    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one()
        job.srt_path = str(srt_path)
        job.status = "completed"
        await session.commit()

    return job_id


async def _cleanup_job(make_client, job_id: str) -> None:
    async with make_client() as c:
        await c.delete(f"/api/jobs/{job_id}")


@pytest.mark.asyncio
async def test_update_segments_non_numeric(make_client):
    """Non-numeric start/end should return 400."""
    job_id = await _create_test_job(make_client)
    try:
        async with make_client() as c:
            resp = await c.put(
                f"/api/jobs/{job_id}/segments",
                json={"segments": [{"start": "abc", "end": 2.0, "text": "Hello"}]},
            )
        assert resp.status_code == 400
        assert "numeric" in resp.json()["detail"]
    finally:
        await _cleanup_job(make_client, job_id)


@pytest.mark.asyncio
async def test_glossary_crud(make_client):
    """Test job glossary save and retrieve."""
    job_id = await _create_test_job(make_client)
    try:
        async with make_client() as c:
            # Save glossary
            resp = await c.put(
                f"/api/jobs/{job_id}/glossary",
                json={"glossary": "wrong → correct"},
            )
            assert resp.status_code == 200

            # Verify in segments response
            resp = await c.get(f"/api/jobs/{job_id}/segments")
            assert resp.status_code == 200
            assert resp.json()["glossary"] == "wrong → correct"

            # Clear glossary
            resp = await c.put(
                f"/api/jobs/{job_id}/glossary",
                json={"glossary": ""},
            )
            assert resp.status_code == 200
    finally:
        await _cleanup_job(make_client, job_id)


@pytest.mark.asyncio
async def test_glossary_too_long(make_client):
    job_id = await _create_test_job(make_client)
    try:
        async with make_client() as c:
            resp = await c.put(
                f"/api/jobs/{job_id}/glossary",
                json={"glossary": "x" * 5001},
            )
            assert resp.status_code == 400
    finally:
        await _cleanup_job(make_client, job_id)


@pytest.mark.asyncio
async def test_speakers_crud(make_client):
    """Test speaker save and retrieve."""
    job_id = await _create_test_job(make_client)
    try:
        async with make_client() as c:
            resp = await c.put(
                f"/api/jobs/{job_id}/speakers",
                json={"speakers": ["Alice", "Bob"], "speaker_map": {"0": "Alice"}},
            )
            assert resp.status_code == 200

            resp = await c.get(f"/api/jobs/{job_id}/segments")
            assert resp.status_code == 200
            data = resp.json()
            assert data["speakers"] == ["Alice", "Bob"]
            assert data["speaker_map"] == {"0": "Alice"}
    finally:
        await _cleanup_job(make_client, job_id)
