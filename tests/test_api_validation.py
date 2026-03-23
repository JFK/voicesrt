"""Tests for API input validation and security."""

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.fixture
def make_client():
    def _make():
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    return _make


@pytest.mark.asyncio
async def test_create_job_invalid_refine_mode(make_client):
    """Invalid refine_mode should return 400."""
    async with make_client() as c:
        resp = await c.post(
            "/api/jobs?provider=whisper&refine_mode=invalid",
            files={"file": ("test.mp3", b"fake", "audio/mpeg")},
        )
    assert resp.status_code == 400
    assert "Invalid refine_mode" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_job_valid_refine_modes(make_client):
    """Valid refine_modes should not cause validation error."""
    for mode in ("verbatim", "standard", "caption"):
        async with make_client() as c:
            resp = await c.post(
                f"/api/jobs?provider=whisper&refine_mode={mode}",
                files={"file": ("test.mp3", b"fake", "audio/mpeg")},
            )
        # Should pass validation (may fail later due to no real file, but not 400 for refine_mode)
        assert resp.status_code != 400 or "refine_mode" not in resp.json().get("detail", "")


@pytest.mark.asyncio
async def test_create_job_glossary_too_long(make_client):
    """Glossary exceeding 5000 chars should return 400."""
    long_glossary = "a" * 5001
    async with make_client() as c:
        resp = await c.post(
            "/api/jobs?provider=whisper",
            files={"file": ("test.mp3", b"fake", "audio/mpeg")},
            data={"glossary": long_glossary},
        )
    assert resp.status_code == 400
    assert "Glossary too long" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_job_glossary_at_limit(make_client):
    """Glossary at exactly 5000 chars should be accepted."""
    glossary = "a" * 5000
    async with make_client() as c:
        resp = await c.post(
            "/api/jobs?provider=whisper",
            files={"file": ("test.mp3", b"fake", "audio/mpeg")},
            data={"glossary": glossary},
        )
    # Should not fail due to glossary length
    assert resp.status_code != 400 or "Glossary" not in resp.json().get("detail", "")


@pytest.mark.asyncio
async def test_create_job_unsupported_format(make_client):
    """Unsupported file format should return 400."""
    async with make_client() as c:
        resp = await c.post(
            "/api/jobs?provider=whisper",
            files={"file": ("test.exe", b"fake", "application/octet-stream")},
        )
    assert resp.status_code == 400
    assert "Unsupported format" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_job_no_file(make_client):
    """Missing file should return 422."""
    async with make_client() as c:
        resp = await c.post("/api/jobs?provider=whisper")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_refine_prompt_invalid_mode(make_client):
    """Invalid refine prompt mode should return 400."""
    async with make_client() as c:
        resp = await c.put(
            "/api/settings/refine-prompts/invalid",
            json={"value": "test prompt"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_refine_prompt_valid_modes(make_client):
    """Valid modes should be accepted for refine prompt endpoints."""
    async with make_client() as c:
        resp = await c.get("/api/settings/refine-prompts")
    assert resp.status_code == 200
    data = resp.json()
    for mode in ("verbatim", "standard", "caption"):
        assert mode in data


@pytest.mark.asyncio
async def test_language_switch_sets_cookie(make_client):
    """Language switch endpoint should set cookie and redirect."""
    async with make_client() as c:
        resp = await c.get("/lang/ja", follow_redirects=False)
    assert resp.status_code == 307
    cookie = resp.headers.get("set-cookie", "")
    assert "lang=ja" in cookie


@pytest.mark.asyncio
async def test_language_switch_invalid_code(make_client):
    """Invalid language code should default to 'en'."""
    async with make_client() as c:
        resp = await c.get("/lang/xx", follow_redirects=False)
    assert resp.status_code == 307
    cookie = resp.headers.get("set-cookie", "")
    assert "lang=en" in cookie


@pytest.mark.asyncio
async def test_xss_in_language_cookie(make_client):
    """XSS attempt via language cookie should not be reflected."""
    async with make_client() as c:
        resp = await c.get("/", cookies={"lang": "<script>alert(1)</script>"})
    assert resp.status_code == 200
    assert "<script>alert(1)</script>" not in resp.text
