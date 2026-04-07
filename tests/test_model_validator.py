"""Tests for the pre-flight LLM model validator (issue #53)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services import model_validator
from src.services.model_validator import ModelNotAvailableError, validate_model


@pytest.fixture(autouse=True)
def _clear_validator_cache():
    model_validator.clear_cache()
    yield
    model_validator.clear_cache()


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_model_exists(monkeypatch):
    fake_client = MagicMock()
    fake_client.models.retrieve = AsyncMock(return_value=MagicMock(id="gpt-4o"))

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kw: fake_client)

    await validate_model("openai", "gpt-4o", "sk-test")
    fake_client.models.retrieve.assert_awaited_once_with("gpt-4o")


@pytest.mark.asyncio
async def test_openai_model_not_found(monkeypatch):
    import openai

    fake_client = MagicMock()
    fake_client.models.retrieve = AsyncMock(
        side_effect=openai.NotFoundError("model not found", response=MagicMock(status_code=404), body={"error": "nope"})
    )
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kw: fake_client)

    with pytest.raises(ModelNotAvailableError) as exc:
        await validate_model("openai", "gpt-9000", "sk-test")
    assert exc.value.provider == "openai"
    assert exc.value.model == "gpt-9000"


@pytest.mark.asyncio
async def test_openai_transport_error_skipped(monkeypatch):
    """Network/auth failures must NOT be raised — only catalog 404s are blocking."""
    fake_client = MagicMock()
    fake_client.models.retrieve = AsyncMock(side_effect=RuntimeError("connection refused"))

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kw: fake_client)

    # Should NOT raise.
    await validate_model("openai", "gpt-4o", "sk-test")


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


def _mock_httpx_tags(monkeypatch, models: list[str], status_code: int = 200):
    import httpx

    class MockResponse:
        def __init__(self):
            self.status_code = status_code

        def json(self):
            return {"models": [{"name": m} for m in models]}

    async def mock_get(self, url, **kwargs):
        return MockResponse()

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)


@pytest.mark.asyncio
async def test_ollama_model_exact_match(monkeypatch):
    _mock_httpx_tags(monkeypatch, ["qwen3:30b", "llama3:8b"])
    await validate_model("ollama", "qwen3:30b", "http://localhost:11434")


@pytest.mark.asyncio
async def test_ollama_model_prefix_match(monkeypatch):
    """`qwen3` should resolve when only `qwen3:30b` is installed."""
    _mock_httpx_tags(monkeypatch, ["qwen3:30b"])
    await validate_model("ollama", "qwen3", "http://localhost:11434")


@pytest.mark.asyncio
async def test_ollama_model_missing(monkeypatch):
    _mock_httpx_tags(monkeypatch, ["qwen3:30b"])
    with pytest.raises(ModelNotAvailableError):
        await validate_model("ollama", "phi4", "http://localhost:11434")


@pytest.mark.asyncio
async def test_ollama_unreachable_skipped(monkeypatch):
    import httpx

    async def mock_get(self, url, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    # Should NOT raise — transport failure is non-blocking.
    await validate_model("ollama", "qwen3", "http://localhost:11434")


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_avoids_second_call(monkeypatch):
    fake_client = MagicMock()
    fake_client.models.retrieve = AsyncMock(return_value=MagicMock(id="gpt-4o"))

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kw: fake_client)

    await validate_model("openai", "gpt-4o", "sk-test")
    await validate_model("openai", "gpt-4o", "sk-test")
    assert fake_client.models.retrieve.await_count == 1


@pytest.mark.asyncio
async def test_cache_negative_result(monkeypatch):
    import openai

    call_count = {"n": 0}

    async def retrieve(model):
        call_count["n"] += 1
        raise openai.NotFoundError("missing", response=MagicMock(status_code=404), body={"error": "nope"})

    fake_client = MagicMock()
    fake_client.models.retrieve = retrieve
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kw: fake_client)

    with pytest.raises(ModelNotAvailableError):
        await validate_model("openai", "gpt-9000", "sk-test")
    with pytest.raises(ModelNotAvailableError):
        await validate_model("openai", "gpt-9000", "sk-test")
    assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# Integration with /api/jobs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_job_rejects_bad_model(make_client, monkeypatch):
    """Job submission with refine enabled + bad model returns 400 before upload."""
    from src.services import model_validator as mv
    from src.services import transcribe

    async def fake_get_credential(session, provider):
        return "sk-test-fake"

    async def fake_validate(api_provider, model, credential):
        raise ModelNotAvailableError(api_provider, model, "fixture")

    monkeypatch.setattr(transcribe, "_get_credential", fake_get_credential)
    monkeypatch.setattr(mv, "validate_model", fake_validate)

    async with make_client() as c:
        resp = await c.post(
            "/api/jobs?provider=whisper&enable_refine=true",
            files={"file": ("test.mp3", b"fake", "audio/mpeg")},
        )

    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "MODEL_NOT_AVAILABLE"
    assert body["error"]["provider"] == "openai"
    assert "model" in body["error"]


@pytest.mark.asyncio
async def test_create_job_no_flags_skips_validation(make_client, monkeypatch):
    """Plain whisper job without refine/metadata/verify shouldn't trigger validation."""
    from src.services import model_validator as mv

    called = {"n": 0}

    async def fake_validate(*args, **kwargs):
        called["n"] += 1

    monkeypatch.setattr(mv, "validate_model", fake_validate)

    async with make_client() as c:
        resp = await c.post(
            "/api/jobs?provider=whisper",
            files={"file": ("test.mp3", b"fake", "audio/mpeg")},
        )
    assert resp.status_code == 200
    assert called["n"] == 0

    # Cleanup
    from tests.helpers import cleanup_job

    await cleanup_job(make_client, resp.json()["id"])
