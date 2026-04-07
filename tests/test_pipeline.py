"""Tests for transcription/refinement pipeline with mocked external APIs."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.errors import build_error_detail, classify_error, parse_error_detail, serialize_error_detail
from src.services.refine import refine_with_llm
from tests.helpers import mock_openai_response

# -- Helpers --

MOCK_SEGMENTS = [
    {"start": 0.0, "end": 2.5, "text": "Hello world"},
    {"start": 3.0, "end": 5.0, "text": "This is a test"},
]


def _patch_openai():
    """Patch openai.AsyncOpenAI for refine tests."""
    return patch("openai.AsyncOpenAI")


# -- refine_with_llm tests --


@pytest.mark.asyncio
async def test_refine_openai_standard():
    """Standard mode should call OpenAI and return refined segments."""
    resp = mock_openai_response(
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
    resp = mock_openai_response('{"segments": [{"start": 0.0, "end": 1.0, "text": "test"}]}')

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
    resp = mock_openai_response('{"segments": [{"start": 0.0, "end": 1.0, "text": "test"}]}')

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
    resp = mock_openai_response('{"segments": [{"start": 0.0, "end": 1.0, "text": "fixed"}]}')

    with _patch_openai() as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        await refine_with_llm(
            MOCK_SEGMENTS,
            "fake-key",
            "openai",
            "gpt-test",
            refine_mode="standard",
            custom_prompts={"standard": custom},
        )

    prompt = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "Custom: fix everything" in prompt


@pytest.mark.asyncio
async def test_refine_custom_prompt_fallback():
    """Custom prompt for different mode should not affect current mode."""
    resp = mock_openai_response('{"segments": [{"start": 0.0, "end": 1.0, "text": "test"}]}')

    with _patch_openai() as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        await refine_with_llm(
            MOCK_SEGMENTS,
            "fake-key",
            "openai",
            "gpt-test",
            refine_mode="standard",
            custom_prompts={"caption": "custom caption {glossary_section}\n{segments_json}"},
        )

    prompt = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "custom caption" not in prompt
    assert "Remove filler words" in prompt


@pytest.mark.asyncio
async def test_refine_glossary_in_prompt():
    """Glossary should be injected into the refinement prompt."""
    resp = mock_openai_response('{"segments": [{"start": 0.0, "end": 1.0, "text": "test"}]}')

    with _patch_openai() as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        await refine_with_llm(
            MOCK_SEGMENTS,
            "fake-key",
            "openai",
            "gpt-test",
            glossary="VoiceSRT:ボイスSRT\nKubernetes:クバネティス",
        )

    prompt = mock_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "VoiceSRT" in prompt
    assert "Kubernetes" in prompt


@pytest.mark.asyncio
async def test_refine_temperature():
    """Refine should use low temperature (0.3) for accuracy."""
    resp = mock_openai_response('{"segments": []}')

    with _patch_openai() as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        await refine_with_llm(MOCK_SEGMENTS, "fake-key", "openai", "gpt-test")

    assert mock_client.chat.completions.create.call_args.kwargs["temperature"] == 0.3


# -- error_detail tests --


def test_build_error_detail_preserves_exception_info():
    """Raw exception class and message must survive translation."""

    class CustomError(ValueError):
        pass

    exc = CustomError("model `gpt-5.4` does not exist")
    detail = build_error_detail(exc, stage="refine", provider="openai", model="gpt-5.4")

    assert detail["exception_class"].endswith("CustomError")
    assert detail["raw_message"] == "model `gpt-5.4` does not exist"
    assert detail["stage"] == "refine"
    assert detail["provider"] == "openai"
    assert detail["model"] == "gpt-5.4"
    # ISO-8601 with Z suffix and second precision (no microseconds, no offset)
    assert detail["occurred_at"].endswith("Z")
    assert "." not in detail["occurred_at"]
    assert "+" not in detail["occurred_at"]


def test_build_error_detail_distinguishes_invalid_token():
    """The InvalidToken decrypt failure (#52 scenario) must NOT be hidden as 'Model not found'."""
    from cryptography.fernet import InvalidToken

    exc = InvalidToken()
    detail = build_error_detail(exc, stage="pipeline")

    # The translated user-facing message is allowed to be the generic
    # fallback, but the structured detail keeps the real exception class so
    # the user can debug from the UI.
    assert "InvalidToken" in detail["exception_class"]
    assert "Model not found" not in str(detail)
    assert "Model not found" not in classify_error(exc)


def test_serialize_and_parse_error_detail_round_trip():
    """serialize_error_detail → parse_error_detail must round-trip."""
    exc = RuntimeError("boom")
    raw = serialize_error_detail(exc, stage="refine", provider="openai", model="gpt-x")
    parsed = parse_error_detail(raw)
    assert parsed is not None
    assert parsed["stage"] == "refine"
    assert parsed["provider"] == "openai"
    assert parsed["model"] == "gpt-x"
    assert "RuntimeError" in parsed["exception_class"]
    assert parsed["raw_message"] == "boom"

    assert parse_error_detail(None) is None
    assert parse_error_detail("") is None
    assert parse_error_detail("not-json") is None
    assert parse_error_detail("[1, 2, 3]") is None  # not a dict


@pytest.mark.asyncio
async def test_refine_failure_populates_error_detail(monkeypatch):
    """When refinement raises, the pipeline must persist both error_message and error_detail."""
    from src.constants import STATUS_COMPLETED
    from src.models import Job
    from src.services import transcribe as transcribe_mod

    # Stub the heavy parts so we exercise just the refine catch path.
    job = Job(
        id="test-job-err",
        filename="x.wav",
        file_size=1,
        provider="whisper",
        enable_refine=True,
    )

    fake_segments = [{"start": 0.0, "end": 1.0, "text": "hi"}]

    async def fake_get_credential(_session, _provider):
        return "fake-key"

    async def fake_extract(_path, out_path):
        out_path.write_bytes(b"")
        return 1.0

    async def fake_run_transcription(*_args, **_kwargs):
        return list(fake_segments)

    async def fake_run_refinement(*_args, **_kwargs):
        raise RuntimeError("upstream refine failure: model `gpt-x` does not exist")

    async def fake_get_refine_model(_session, _provider_name):
        return "gpt-x"

    def fake_save_srt(_content, _path):
        pass

    monkeypatch.setattr(transcribe_mod, "_get_credential", fake_get_credential)
    monkeypatch.setattr(transcribe_mod, "extract_audio", fake_extract)
    monkeypatch.setattr(transcribe_mod, "_run_transcription", fake_run_transcription)
    monkeypatch.setattr(transcribe_mod, "_run_refinement", fake_run_refinement)
    monkeypatch.setattr(transcribe_mod, "_get_refine_model", fake_get_refine_model)
    monkeypatch.setattr(transcribe_mod, "save_srt", fake_save_srt)

    # Place the upload file where the pipeline looks for it.
    upload_dir = transcribe_mod.settings.uploads_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / f"{job.id}.wav").write_bytes(b"")

    session = MagicMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))

    try:
        await transcribe_mod.process_transcription(job, session)
    finally:
        (upload_dir / f"{job.id}.wav").unlink(missing_ok=True)

    assert job.status == STATUS_COMPLETED  # refine failure is non-fatal
    assert job.error_message and "Refinement failed" in job.error_message
    assert job.error_detail
    detail = json.loads(job.error_detail)
    assert detail["stage"] == "refine"
    assert "RuntimeError" in detail["exception_class"]
    assert "upstream refine failure" in detail["raw_message"]


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
            audio_path=MagicMock(),
            api_key="fake-key",
            language="ja",
            prompt="漢字、かんじ",
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
