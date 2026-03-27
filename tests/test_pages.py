"""Tests for HTML page routes."""

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
async def test_upload_page(make_client):
    async with make_client() as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert "VoiceSRT" in resp.text


@pytest.mark.asyncio
async def test_history_page(make_client):
    async with make_client() as c:
        resp = await c.get("/history")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_settings_page(make_client):
    async with make_client() as c:
        resp = await c.get("/settings")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_upload_page_ja(make_client):
    async with make_client() as c:
        resp = await c.get("/", cookies={"lang": "ja"})
    assert resp.status_code == 200
    assert "アップロード" in resp.text


@pytest.mark.asyncio
async def test_history_page_ja(make_client):
    async with make_client() as c:
        resp = await c.get("/history", cookies={"lang": "ja"})
    assert resp.status_code == 200
    assert "アップロード履歴" in resp.text


@pytest.mark.asyncio
async def test_nonexistent_job_redirects(make_client):
    async with make_client() as c:
        resp = await c.get("/srt/nonexistent-id", follow_redirects=False)
    assert resp.status_code == 307


@pytest.mark.asyncio
async def test_nonexistent_meta_redirects(make_client):
    async with make_client() as c:
        resp = await c.get("/meta/nonexistent-id", follow_redirects=False)
    assert resp.status_code == 307
