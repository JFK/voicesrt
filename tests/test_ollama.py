"""Tests for Ollama provider integration."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.services.utils import create_openai_compatible_client


@pytest.fixture
def make_client():
    def _make():
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    return _make


def _mock_openai_response(content, prompt_tokens=100, completion_tokens=50):
    """Create a mock OpenAI-compatible response (used by Ollama via OpenAI SDK)."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=content))]
    mock_response.usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return mock_response


# ---------------------------------------------------------------------------
# create_openai_compatible_client
# ---------------------------------------------------------------------------


def test_create_openai_compatible_client_ollama():
    client = create_openai_compatible_client("ollama", "http://localhost:11434")
    assert client.base_url.host == "localhost"
    assert "/v1" in str(client.base_url)
    assert client.api_key == "ollama"


def test_create_openai_compatible_client_openai():
    client = create_openai_compatible_client("openai", "sk-test-key")
    assert client.api_key == "sk-test-key"


def test_create_openai_compatible_client_custom_url():
    client = create_openai_compatible_client("ollama", "http://192.168.1.100:11434")
    assert "192.168.1.100" in str(client.base_url)


# ---------------------------------------------------------------------------
# Settings API - Ollama
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_models_includes_ollama(make_client):
    async with make_client() as c:
        resp = await c.get("/api/settings/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "ollama" in data


@pytest.mark.asyncio
async def test_set_ollama_model(make_client):
    async with make_client() as c:
        resp = await c.put("/api/settings/models/ollama", json={"model": "qwen3:8b"})
    assert resp.status_code == 200
    assert resp.json()["model"] == "qwen3:8b"


@pytest.mark.asyncio
async def test_save_key_rejects_ollama(make_client):
    """Ollama doesn't use API keys; save_key should reject it."""
    async with make_client() as c:
        resp = await c.put("/api/settings/keys/ollama", json={"key": "not-needed"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_ollama_url(make_client):
    async with make_client() as c:
        resp = await c.get("/api/settings/ollama-url")
    assert resp.status_code == 200
    assert "url" in resp.json()


@pytest.mark.asyncio
async def test_set_ollama_url(make_client):
    async with make_client() as c:
        resp = await c.put("/api/settings/ollama-url", json={"value": "http://192.168.1.50:11434"})
    assert resp.status_code == 200
    assert resp.json()["url"] == "http://192.168.1.50:11434"


@pytest.mark.asyncio
async def test_set_ollama_url_strips_trailing_slash(make_client):
    async with make_client() as c:
        resp = await c.put("/api/settings/ollama-url", json={"value": "http://localhost:11434/"})
    assert resp.status_code == 200
    assert resp.json()["url"] == "http://localhost:11434"


@pytest.mark.asyncio
async def test_test_ollama_connection_failure(make_client):
    """Test Ollama connectivity endpoint when Ollama is not running."""
    import httpx

    async def _raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("Connection refused")

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.get = _raise_connect_error
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_http

        async with make_client() as c:
            resp = await c.post("/api/settings/keys/ollama/test")
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    assert "Cannot connect" in data["error"]


# ---------------------------------------------------------------------------
# LLM services - Ollama provider routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refine_with_ollama():
    from src.services.refine import refine_with_llm

    segments = [{"start": 0.0, "end": 2.5, "text": "Hello world"}]
    response_content = json.dumps({"segments": [{"start": 0.0, "end": 2.5, "text": "Hello, world!"}]})
    response = _mock_openai_response(response_content)

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)

    with patch("src.services.refine.create_openai_compatible_client", return_value=mock_client):
        result, in_tok, out_tok = await refine_with_llm(segments, "http://localhost:11434", "ollama", "qwen3:latest")

    assert len(result) == 1
    assert result[0]["text"] == "Hello, world!"
    assert in_tok == 100
    assert out_tok == 50


@pytest.mark.asyncio
async def test_verify_with_ollama():
    from src.services.refine import verify_segments

    segments = [
        {"start": 0.0, "end": 2.5, "text": "Jonh said hello"},
        {"start": 3.0, "end": 5.0, "text": "John replied"},
    ]
    response_content = json.dumps({"corrections": [{"index": 0, "text": "John said hello", "reason": "Name typo"}]})
    response = _mock_openai_response(response_content)

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)

    with patch("src.services.refine.create_openai_compatible_client", return_value=mock_client):
        verified, changed, reasons, in_tok, out_tok = await verify_segments(
            segments, "http://localhost:11434", "ollama", "qwen3:latest"
        )

    assert verified[0]["text"] == "John said hello"
    assert 0 in changed
    assert in_tok == 100


@pytest.mark.asyncio
async def test_suggest_with_ollama():
    from src.services.refine import suggest_segment

    segment = {"start": 0.0, "end": 2.5, "text": "orginal text"}
    response_content = json.dumps({"text": "original text", "reason": "Fixed typo"})
    response = _mock_openai_response(response_content)

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)

    with patch("src.services.refine.create_openai_compatible_client", return_value=mock_client):
        text, reason, in_tok, out_tok = await suggest_segment(
            segment, [], [], "http://localhost:11434", "ollama", "qwen3:latest"
        )

    assert text == "original text"
    assert "typo" in reason.lower()


@pytest.mark.asyncio
async def test_generate_metadata_ollama():
    from src.services.metadata import generate_youtube_metadata

    response_content = json.dumps({"title": "Test Title", "description": "Test desc", "tags": ["tag1"], "chapters": []})
    response = _mock_openai_response(response_content)

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)

    with patch("src.services.metadata.create_openai_compatible_client", return_value=mock_client):
        result, in_tok, out_tok = await generate_youtube_metadata(
            "Hello world", "http://localhost:11434", "ollama", "qwen3:latest"
        )

    assert result["title"] == "Test Title"
    assert in_tok == 100


@pytest.mark.asyncio
async def test_generate_quiz_ollama():
    from src.services.quiz import generate_quiz

    quiz_data = {"quiz": [{"question": "What is AI?", "options": ["A", "B", "C", "D"], "answer_index": 0}]}
    response = _mock_openai_response(json.dumps(quiz_data))

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)

    with patch("src.services.quiz.create_openai_compatible_client", return_value=mock_client):
        quiz, in_tok, _ = await generate_quiz("test srt", "http://localhost:11434", "ollama", "qwen3:latest")

    assert len(quiz) == 1
    assert quiz[0]["question"] == "What is AI?"


@pytest.mark.asyncio
async def test_generate_catchphrases_ollama():
    from src.services.catchphrase import generate_catchphrases

    response_content = json.dumps({"catchphrases": [{"text": "Wow!", "style": "exclamation"}]})
    response = _mock_openai_response(response_content)

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)

    with patch("src.services.catchphrase.create_openai_compatible_client", return_value=mock_client):
        phrases, in_tok, _ = await generate_catchphrases("test srt", "http://localhost:11434", "ollama", "qwen3:latest")

    assert len(phrases) == 1
    assert phrases[0]["text"] == "Wow!"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_provider_api_map_ollama():
    from src.constants import PROVIDER_API_MAP, get_provider_name

    assert PROVIDER_API_MAP["ollama"] == "ollama"
    assert get_provider_name("ollama") == "ollama"


# ---------------------------------------------------------------------------
# Cost - Ollama models default to zero cost
# ---------------------------------------------------------------------------


def test_ollama_model_zero_cost():
    from src.services.cost import estimate_llm_cost

    cost = estimate_llm_cost(1000, 500, "qwen3:latest", "ollama")
    assert cost == 0.0
