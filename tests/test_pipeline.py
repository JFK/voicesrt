"""Tests for transcription/refinement pipeline with mocked external APIs."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.services.refine import refine_with_llm


# -- Helpers --

MOCK_SEGMENTS = [
    {"start": 0.0, "end": 2.5, "text": "Hello world"},
    {"start": 3.0, "end": 5.0, "text": "This is a test"},
]


def _mock_openai_response(content: str, prompt_tokens: int = 50, completion_tokens: int = 20):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=content))]
    mock_response.usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return mock_response


def _patch_openai():
    """Patch openai.AsyncOpenAI for refine tests."""
    return patch("openai.AsyncOpenAI")


# -- refine_with_llm tests --


@pytest.mark.asyncio
async def test_refine_openai_standard():
    """Standard mode should call OpenAI and return refined segments."""
    resp = _mock_openai_response(
        '{"segments": [{"start": 0.0, "end": 2.5, "text": "Hello, world."}]}',
        prompt_tokens=100,
        completion_tokens=50,
    )

    with _patch_openai() as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        segments, inp, out = await refine_with_llm(
            MOCK_SEGMENTS, "fake-key", "openai", "gpt-test", refine_mode="standard"
        )

    assert len(segments) == 1
    assert segments[0]["text"] == "Hello, world."
    assert inp == 100
    assert out == 50

    prompt_content = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "Remove filler words" in prompt_content


@pytest.mark.asyncio
async def test_refine_verbatim_keeps_fillers():
    """Verbatim mode prompt should instruct keeping fillers."""
    resp = _mock_openai_response('{"segments": [{"start": 0.0, "end": 1.0, "text": "test"}]}')

    with _patch_openai() as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        await refine_with_llm(MOCK_SEGMENTS, "fake-key", "openai", "gpt-test", refine_mode="verbatim")

    prompt = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "keep" in prompt.lower()
    assert "filler" in prompt.lower()


@pytest.mark.asyncio
async def test_refine_caption_allows_splitting():
    """Caption mode prompt should allow segment splitting."""
    resp = _mock_openai_response('{"segments": [{"start": 0.0, "end": 1.0, "text": "test"}]}')

    with _patch_openai() as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        await refine_with_llm(MOCK_SEGMENTS, "fake-key", "openai", "gpt-test", refine_mode="caption")

    prompt = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "split" in prompt.lower()


@pytest.mark.asyncio
async def test_refine_custom_prompt_overrides_default():
    """Custom prompts should override default templates."""
    custom = "Custom: fix everything. {glossary_section}\n{segments_json}"
    resp = _mock_openai_response('{"segments": [{"start": 0.0, "end": 1.0, "text": "fixed"}]}')

    with _patch_openai() as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        await refine_with_llm(
            MOCK_SEGMENTS, "fake-key", "openai", "gpt-test",
            refine_mode="standard",
            custom_prompts={"standard": custom},
        )

    prompt = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "Custom: fix everything" in prompt


@pytest.mark.asyncio
async def test_refine_custom_prompt_fallback():
    """Custom prompt for different mode should not affect current mode."""
    resp = _mock_openai_response('{"segments": [{"start": 0.0, "end": 1.0, "text": "test"}]}')

    with _patch_openai() as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        await refine_with_llm(
            MOCK_SEGMENTS, "fake-key", "openai", "gpt-test",
            refine_mode="standard",
            custom_prompts={"caption": "custom caption {glossary_section}\n{segments_json}"},
        )

    prompt = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "custom caption" not in prompt
    assert "Remove filler words" in prompt


@pytest.mark.asyncio
async def test_refine_glossary_in_prompt():
    """Glossary should be injected into the refinement prompt."""
    resp = _mock_openai_response('{"segments": [{"start": 0.0, "end": 1.0, "text": "test"}]}')

    with _patch_openai() as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        await refine_with_llm(
            MOCK_SEGMENTS, "fake-key", "openai", "gpt-test",
            glossary="VoiceSRT:ボイスSRT\nKubernetes:クバネティス",
        )

    prompt = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "VoiceSRT" in prompt
    assert "Kubernetes" in prompt


@pytest.mark.asyncio
async def test_refine_temperature():
    """Refine should use low temperature (0.3) for accuracy."""
    resp = _mock_openai_response('{"segments": []}')

    with _patch_openai() as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        await refine_with_llm(MOCK_SEGMENTS, "fake-key", "openai", "gpt-test")

    assert mock_client.chat.completions.create.call_args.kwargs["temperature"] == 0.3


# -- Whisper prompt tests --


@pytest.mark.asyncio
async def test_whisper_receives_glossary_prompt():
    """Whisper API should receive glossary as prompt parameter."""
    from src.services.whisper import transcribe_with_whisper

    mock_response = MagicMock()
    mock_response.segments = [MagicMock(start=0.0, end=1.0, text="hello")]

    with patch("openai.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)

        await transcribe_with_whisper(
            audio_path=MagicMock(), api_key="fake-key", language="ja", prompt="漢字、かんじ",
        )

    assert mock_client.audio.transcriptions.create.call_args.kwargs["prompt"] == "漢字、かんじ"


@pytest.mark.asyncio
async def test_whisper_no_prompt_when_empty():
    """Whisper should not include prompt param if not provided."""
    from src.services.whisper import transcribe_with_whisper

    mock_response = MagicMock()
    mock_response.segments = []

    with patch("openai.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)

        await transcribe_with_whisper(audio_path=MagicMock(), api_key="fake-key")

    assert "prompt" not in mock_client.audio.transcriptions.create.call_args.kwargs


# -- Settings API integration tests --


@pytest.fixture
def make_client():
    def _make():
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    return _make


@pytest.mark.asyncio
async def test_refine_prompt_crud(make_client):
    """Save, get, and reset custom refine prompt."""
    custom = "My custom prompt {segments_json} {glossary_section}"

    # Save
    async with make_client() as c:
        resp = await c.put("/api/settings/refine-prompts/verbatim", json={"value": custom})
        assert resp.status_code == 200

    # Get
    async with make_client() as c:
        resp = await c.get("/api/settings/refine-prompts")
        assert resp.status_code == 200
        assert resp.json()["verbatim"]["custom"] == custom

    # Reset
    async with make_client() as c:
        resp = await c.delete("/api/settings/refine-prompts/verbatim")
        assert resp.status_code == 200

    # Verify reset
    async with make_client() as c:
        resp = await c.get("/api/settings/refine-prompts")
        assert resp.json()["verbatim"]["custom"] == ""
        assert len(resp.json()["verbatim"]["default"]) > 100
