"""Tests for LLM service functions with mocked API calls."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.helpers import mock_openai_response


def _patch_openai(module_path):
    """Patch openai.AsyncOpenAI within a function that imports openai locally."""
    mock_client = AsyncMock()

    def _make_patcher(response):
        mock_client.chat.completions.create = AsyncMock(return_value=response)
        mock_module = MagicMock()
        mock_module.AsyncOpenAI.return_value = mock_client
        return patch.dict("sys.modules", {"openai": mock_module}), mock_client

    return _make_patcher


@pytest.mark.asyncio
async def test_generate_metadata_openai():
    from src.services.metadata import generate_youtube_metadata

    response = mock_openai_response(
        '{"title": "Test Title", "description": "Test desc", "tags": ["tag1"], "chapters": []}'
    )
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)
    mock_openai = MagicMock()
    mock_openai.AsyncOpenAI.return_value = mock_client

    with patch.dict("sys.modules", {"openai": mock_openai}):
        result, input_tokens, output_tokens = await generate_youtube_metadata(
            "Hello world", "fake-key", "openai", "gpt-5.4"
        )

    assert result["title"] == "Test Title"
    assert input_tokens == 100
    assert output_tokens == 50


@pytest.mark.asyncio
async def test_generate_metadata_with_tone_ref():
    from src.services.metadata import generate_youtube_metadata

    response = mock_openai_response('{"title": "Toned Title", "description": "desc", "tags": [], "chapters": []}')
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)
    mock_openai = MagicMock()
    mock_openai.AsyncOpenAI.return_value = mock_client

    with patch.dict("sys.modules", {"openai": mock_openai}):
        result, _, _ = await generate_youtube_metadata(
            "Hello world",
            "fake-key",
            "openai",
            "gpt-5.4",
            tone_references="---\nTitle: Prev Video\nDescription: prev desc\n---",
        )

    assert result["title"] == "Toned Title"
    call_args = mock_client.chat.completions.create.call_args
    prompt = call_args.kwargs["messages"][1]["content"]
    assert "Tone Reference" in prompt
    assert "Prev Video" in prompt


@pytest.mark.asyncio
async def test_generate_catchphrases_openai():
    from src.services.catchphrase import generate_catchphrases

    response = mock_openai_response(
        '{"catchphrases": [{"text": "Catch!", "style": "exclamation"}, {"text": "Why?", "style": "question"}]}'
    )
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)
    mock_openai = MagicMock()
    mock_openai.AsyncOpenAI.return_value = mock_client

    with patch.dict("sys.modules", {"openai": mock_openai}):
        phrases, input_tokens, _ = await generate_catchphrases("test srt content", "fake-key", "openai", "gpt-5.4")

    assert len(phrases) == 2
    assert phrases[0]["text"] == "Catch!"
    assert input_tokens == 100


@pytest.mark.asyncio
async def test_generate_quiz_openai():
    import json

    from src.services.quiz import generate_quiz

    quiz_data = {"quiz": [{"question": "What is AI?", "options": ["A", "B", "C", "D"], "answer_index": 0}]}
    response = mock_openai_response(json.dumps(quiz_data))
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)
    mock_openai = MagicMock()
    mock_openai.AsyncOpenAI.return_value = mock_client

    with patch.dict("sys.modules", {"openai": mock_openai}):
        quiz, _, _ = await generate_quiz("test srt content", "fake-key", "openai", "gpt-5.4")

    assert len(quiz) == 1
    assert quiz[0]["question"] == "What is AI?"


@pytest.mark.asyncio
async def test_optimize_meta_prompt_openai():
    from src.services.metadata import optimize_meta_prompt

    response = mock_openai_response("Improved prompt text")
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)
    mock_openai = MagicMock()
    mock_openai.AsyncOpenAI.return_value = mock_client

    with patch.dict("sys.modules", {"openai": mock_openai}):
        result = await optimize_meta_prompt(
            "current prompt",
            {"channelName": "Test", "genre": "Tech", "speakers": "", "audience": "", "notes": ""},
            "fake-key",
            "openai",
            "gpt-5.4",
        )

    assert result == "Improved prompt text"
