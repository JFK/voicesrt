"""Regression: metadata generation must route to the override provider, not job.provider.

Previously ``_run_metadata_generation`` always used ``job.provider`` to decide
which LLM SDK to call, so picking OpenAI in the UI for a Gemini-transcribed
job sent the OpenAI key to the Gemini SDK and Google rejected it with
``API_KEY_INVALID``.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.services.transcribe import _run_metadata_generation


def _make_job():
    return SimpleNamespace(
        id="test-job",
        provider="gemini",  # transcription provider
        youtube_title=None,
        youtube_description=None,
        youtube_tags=None,
    )


@pytest.mark.asyncio
async def test_run_metadata_generation_routes_to_override_provider():
    job = _make_job()
    fake_metadata = {"titles": ["T"], "description": "d", "tags": ["x"], "chapters": []}

    with (
        patch(
            "src.services.metadata.generate_youtube_metadata",
            new=AsyncMock(return_value=(fake_metadata, 100, 50)),
        ) as mock_gen,
        patch("src.services.transcribe.log_cost", new=AsyncMock()),
        patch("src.services.transcribe.estimate_llm_cost", return_value=0.001),
    ):
        await _run_metadata_generation(
            job,
            session=AsyncMock(),
            srt_content="srt",
            api_key="OPENAI_KEY",
            model="gpt-5.4",
            provider="openai",  # explicit override
        )

    # Critical: provider passed to generate_youtube_metadata must be the override,
    # otherwise the OpenAI key gets routed to the Gemini SDK.
    args, _ = mock_gen.call_args
    assert args[2] == "openai", f"expected provider='openai', got {args[2]!r}"
    assert args[1] == "OPENAI_KEY"


@pytest.mark.asyncio
async def test_run_metadata_generation_defaults_to_job_provider():
    """When no override is passed, fall back to the job's transcription provider."""
    job = _make_job()  # provider='gemini'
    fake_metadata = {"titles": ["T"], "description": "d", "tags": ["x"], "chapters": []}

    with (
        patch(
            "src.services.metadata.generate_youtube_metadata",
            new=AsyncMock(return_value=(fake_metadata, 100, 50)),
        ) as mock_gen,
        patch("src.services.transcribe.log_cost", new=AsyncMock()),
        patch("src.services.transcribe.estimate_llm_cost", return_value=0.001),
    ):
        await _run_metadata_generation(
            job,
            session=AsyncMock(),
            srt_content="srt",
            api_key="GEMINI_KEY",
            model="gemini-2.5-flash",
        )

    args, _ = mock_gen.call_args
    assert args[2] == "gemini"
