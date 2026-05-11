"""Tests for HTML page routes."""

import pytest

from src.database import async_session
from src.models import Setting


@pytest.mark.asyncio
async def test_landing_page(make_client):
    async with make_client() as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert "VoiceSRT" in resp.text
    # Persona cards should be present
    assert "persona=youtuber" in resp.text
    assert "persona=meeting" in resp.text
    assert "persona=editor" in resp.text


@pytest.mark.asyncio
async def test_upload_page(make_client):
    async with make_client() as c:
        resp = await c.get("/upload")
    assert resp.status_code == 200
    assert "VoiceSRT" in resp.text


@pytest.mark.asyncio
async def test_landing_redirects_job_to_upload(make_client):
    async with make_client() as c:
        resp = await c.get("/?job=abc123", follow_redirects=False)
    assert resp.status_code == 307
    assert "/upload" in resp.headers["location"]
    assert "job=abc123" in resp.headers["location"]


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
        resp = await c.get("/upload", cookies={"lang": "ja"})
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


@pytest.mark.asyncio
async def test_landing_redirects_when_only_undecryptable_keys(make_client):
    """If every stored api_key row fails to decrypt under the active ENCRYPTION_KEY,
    the landing page must redirect to /setup so the user can recover. Without this,
    _get_credential() would later crash deep in the transcription pipeline.
    """
    from cryptography.fernet import Fernet
    from sqlalchemy import delete

    # Replace the autouse fixture row with a token written under a foreign key
    # so it is structurally valid but fails signature verification.
    foreign_token = Fernet(Fernet.generate_key()).encrypt(b"sk-foreign").decode()

    async with async_session() as s:
        await s.execute(delete(Setting).where(Setting.key.like("api_key.%")))
        s.add(Setting(key="api_key.openai", value=foreign_token, encrypted=True))
        await s.commit()

    try:
        async with make_client() as c:
            resp = await c.get("/", follow_redirects=False)
        assert resp.status_code == 307
        assert resp.headers["location"] == "/setup"
    finally:
        # Restore the autouse fixture row so other tests aren't affected.
        from src.services.crypto import encrypt

        async with async_session() as s:
            await s.execute(delete(Setting).where(Setting.key.like("api_key.%")))
            s.add(Setting(key="api_key.openai", value=encrypt("sk-test"), encrypted=True))
            await s.commit()


@pytest.mark.asyncio
async def test_setup_page_omits_banner_in_clean_state(make_client):
    """When all stored api_key rows decrypt correctly, /setup must NOT render
    the rotation banner — otherwise users navigating directly to /setup would
    see a misleading warning even though nothing has rotated.
    """
    async with make_client() as c:
        resp = await c.get("/setup")
    assert resp.status_code == 200
    assert "Encryption key has changed" not in resp.text


@pytest.mark.asyncio
async def test_setup_page_flags_key_mismatch_when_rows_undecryptable(make_client):
    """The /setup page must expose key_mismatch=True when api_key.% rows exist
    but cannot be decrypted under the active ENCRYPTION_KEY, so the template
    can render a warning explaining why the user landed here.
    """
    from cryptography.fernet import Fernet
    from sqlalchemy import delete

    foreign_token = Fernet(Fernet.generate_key()).encrypt(b"sk-foreign").decode()

    async with async_session() as s:
        await s.execute(delete(Setting).where(Setting.key.like("api_key.%")))
        s.add(Setting(key="api_key.openai", value=foreign_token, encrypted=True))
        await s.commit()

    try:
        async with make_client() as c:
            resp = await c.get("/setup")
        assert resp.status_code == 200
        # English banner copy must render so the user understands why the
        # /setup redirect happened — the localized text key is intentionally
        # asserted by substring to stay tolerant of i18n wording tweaks.
        assert "Encryption key has changed" in resp.text

        async with make_client() as c:
            resp_ja = await c.get("/setup", cookies={"lang": "ja"})
        assert resp_ja.status_code == 200
        assert "暗号化キーが変更されました" in resp_ja.text
    finally:
        from src.services.crypto import encrypt

        async with async_session() as s:
            await s.execute(delete(Setting).where(Setting.key.like("api_key.%")))
            s.add(Setting(key="api_key.openai", value=encrypt("sk-test"), encrypted=True))
            await s.commit()
