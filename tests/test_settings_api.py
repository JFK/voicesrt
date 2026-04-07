"""Tests for Settings API endpoints."""

import pytest

from src.database import async_session
from src.models import Setting


@pytest.mark.asyncio
async def test_list_keys_tolerates_undecryptable_row(make_client):
    """A row encrypted with a different ENCRYPTION_KEY must not crash the endpoint.

    Reproduces the failure mode where rotating ENCRYPTION_KEY (or restoring a
    DB from another environment) leaves stale rows that decrypt() rejects.
    The endpoint should surface them with `decryption_error: True` instead of
    returning HTTP 500.
    """
    # Generate a syntactically valid Fernet token using a *different* key,
    # so the row decodes structurally but fails signature verification under
    # the active ENCRYPTION_KEY — exactly the post-rotation scenario.
    from cryptography.fernet import Fernet
    from sqlalchemy import delete

    from src.services.crypto import encrypt

    foreign_key = Fernet.generate_key()
    foreign_token = Fernet(foreign_key).encrypt(b"sk-foreign").decode()

    # Re-seed openai with a fresh, valid token under the active key — the
    # shared dev DB may carry a stale row left by a different ENCRYPTION_KEY.
    async with async_session() as s:
        await s.execute(delete(Setting).where(Setting.key == "api_key.openai"))
        await s.execute(delete(Setting).where(Setting.key == "api_key.google"))
        s.add(Setting(key="api_key.openai", value=encrypt("sk-test"), encrypted=True))
        s.add(Setting(key="api_key.google", value=foreign_token, encrypted=True))
        await s.commit()

    try:
        async with make_client() as c:
            resp = await c.get("/api/settings/keys")
        assert resp.status_code == 200
        data = resp.json()
        google_entry = next((e for e in data if e["provider"] == "google"), None)
        assert google_entry is not None
        assert google_entry.get("decryption_error") is True
        assert google_entry["masked"] == "****"
        # The valid openai row from the conftest fixture must still be present
        openai_entry = next((e for e in data if e["provider"] == "openai"), None)
        assert openai_entry is not None
        assert openai_entry.get("decryption_error") is not True
    finally:
        # Cleanup so other tests aren't affected. Leave openai re-seeded with
        # the valid test token (the autouse fixture relies on its presence).
        async with async_session() as s:
            await s.execute(delete(Setting).where(Setting.key == "api_key.google"))
            await s.commit()


@pytest.mark.asyncio
async def test_get_models(make_client):
    async with make_client() as c:
        resp = await c.get("/api/settings/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "openai" in data
    assert "gemini" in data


@pytest.mark.asyncio
async def test_set_model(make_client):
    async with make_client() as c:
        resp = await c.put("/api/settings/models/openai", json={"model": "gpt-5.4-mini"})
    assert resp.status_code == 200
    assert resp.json()["model"] == "gpt-5.4-mini"


@pytest.mark.asyncio
async def test_set_model_invalid_provider(make_client):
    async with make_client() as c:
        resp = await c.put("/api/settings/models/invalid", json={"model": "test"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_glossary(make_client):
    async with make_client() as c:
        resp = await c.get("/api/settings/glossary")
    assert resp.status_code == 200
    assert "glossary" in resp.json()


@pytest.mark.asyncio
async def test_set_glossary(make_client):
    async with make_client() as c:
        resp = await c.put("/api/settings/glossary", json={"value": "term1\nterm2"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_tone_references(make_client):
    async with make_client() as c:
        resp = await c.get("/api/settings/tone-references")
    assert resp.status_code == 200
    assert "tone_references" in resp.json()


@pytest.mark.asyncio
async def test_set_tone_references(make_client):
    async with make_client() as c:
        resp = await c.put(
            "/api/settings/tone-references",
            json={"value": "---\nTitle: Test\nDescription: Test desc\n---"},
        )
    assert resp.status_code == 200
    assert resp.json()["saved"] is True


@pytest.mark.asyncio
async def test_get_pricing(make_client):
    async with make_client() as c:
        resp = await c.get("/api/settings/pricing")
    assert resp.status_code == 200
    data = resp.json()
    assert "pricing" in data
    assert "whisper-1" in data["pricing"]


@pytest.mark.asyncio
async def test_set_pricing(make_client):
    async with make_client() as c:
        resp = await c.put(
            "/api/settings/pricing",
            json={"pricing": {"whisper-1": {"input_per_1m": 0.0, "output_per_1m": 0.0, "per_minute": 0.006}}},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_general_settings(make_client):
    async with make_client() as c:
        resp = await c.get("/api/settings/general")
    assert resp.status_code == 200
    data = resp.json()
    assert "max_upload_size_gb" in data


@pytest.mark.asyncio
async def test_set_general_setting(make_client):
    async with make_client() as c:
        resp = await c.put("/api/settings/general/max_upload_size_gb", json={"value": "5"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_set_general_setting_invalid_key(make_client):
    async with make_client() as c:
        resp = await c.put("/api/settings/general/nonexistent", json={"value": "test"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_meta_context(make_client):
    async with make_client() as c:
        resp = await c.get("/api/settings/meta-context")
    assert resp.status_code == 200
    data = resp.json()
    assert "context" in data
    assert "prompt" in data


@pytest.mark.asyncio
async def test_set_meta_context(make_client):
    async with make_client() as c:
        resp = await c.put(
            "/api/settings/meta-context",
            json={"context": '{"channelName": "Test"}', "prompt": "Generate metadata"},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_save_key_invalid_provider(make_client):
    async with make_client() as c:
        resp = await c.put("/api/settings/keys/invalid", json={"key": "test-key"})
    assert resp.status_code == 400
