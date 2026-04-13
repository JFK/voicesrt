"""Tests for the streaming SRT editor feature (issue #50).

Covers: on_chunk callback, _resolve_segments, _load_custom_prompts,
streaming pipeline path, and graceful degradation on refine failure.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import segment_factory

# -- _resolve_segments tests --


@pytest.mark.asyncio
async def test_resolve_segments_prefers_srt_file(tmp_path):
    """When srt_path is set, _resolve_segments reads from the SRT file."""
    from src.api.jobs import _resolve_segments

    srt_content = "1\n00:00:00,000 --> 00:00:02,000\nHello\n\n2\n00:00:02,000 --> 00:00:04,000\nWorld\n\n"
    srt_file = tmp_path / "test.srt"
    srt_file.write_text(srt_content)

    job = MagicMock()
    job.srt_path = str(srt_file)
    job.segments_json = json.dumps([{"start": 0, "end": 1, "text": "stale"}])

    segments = await _resolve_segments(job)
    assert len(segments) == 2
    assert segments[0]["text"] == "Hello"


@pytest.mark.asyncio
async def test_resolve_segments_falls_back_to_segments_json():
    """When srt_path is None, _resolve_segments reads from segments_json."""
    from src.api.jobs import _resolve_segments

    segs = [{"start": 0.0, "end": 1.0, "text": "streaming"}]
    job = MagicMock()
    job.srt_path = None
    job.segments_json = json.dumps(segs)

    segments = await _resolve_segments(job)
    assert len(segments) == 1
    assert segments[0]["text"] == "streaming"


@pytest.mark.asyncio
async def test_resolve_segments_raises_when_neither():
    """When both srt_path and segments_json are None, raises srt_not_found."""
    from src.api.jobs import _resolve_segments
    from src.errors import AppError

    job = MagicMock()
    job.srt_path = None
    job.segments_json = None

    with pytest.raises(AppError):
        await _resolve_segments(job)


# -- _load_custom_prompts tests --


@pytest.mark.asyncio
async def test_load_custom_prompts_returns_stored_prompts():
    """_load_custom_prompts returns prompts from DB settings."""
    from src.services.transcribe import _load_custom_prompts

    mock_setting = MagicMock()
    mock_setting.value = "custom verbatim prompt"
    mock_result = MagicMock()
    # Only return a setting for "verbatim", None for others
    call_count = 0

    def scalar_one_or_none():
        nonlocal call_count
        call_count += 1
        return mock_setting if call_count == 1 else None

    mock_result.scalar_one_or_none = scalar_one_or_none

    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)

    prompts = await _load_custom_prompts(session)
    assert "verbatim" in prompts
    assert prompts["verbatim"] == "custom verbatim prompt"
    assert "standard" not in prompts
    assert "caption" not in prompts


@pytest.mark.asyncio
async def test_load_custom_prompts_returns_empty_when_none():
    """_load_custom_prompts returns empty dict when no custom prompts exist."""
    from src.services.transcribe import _load_custom_prompts

    mock_result = MagicMock()
    mock_result.scalar_one_or_none = lambda: None

    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)

    prompts = await _load_custom_prompts(session)
    assert prompts == {}


# -- on_chunk callback tests --


@pytest.mark.asyncio
async def test_on_chunk_called_per_chunk_whisper(monkeypatch):
    """Whisper multi-chunk transcription calls on_chunk for each chunk."""
    from src.services.transcribe import _transcribe_whisper

    chunk1_segs = [{"start": 0.0, "end": 1.0, "text": "chunk1"}]
    chunk2_segs = [{"start": 0.0, "end": 1.0, "text": "chunk2"}]
    call_count = 0

    async def fake_transcribe(_path, _key, _lang, _prompt):
        nonlocal call_count
        call_count += 1
        return chunk1_segs if call_count == 1 else chunk2_segs

    async def fake_split(_path, **kwargs):
        from pathlib import Path

        return [Path("/fake/chunk0.wav"), Path("/fake/chunk1.wav")]

    async def fake_duration(_path):
        return 5.0

    monkeypatch.setattr("src.services.transcribe.split_audio", fake_split)
    monkeypatch.setattr("src.services.transcribe.get_audio_duration", fake_duration)
    monkeypatch.setattr("src.services.whisper.transcribe_with_whisper", fake_transcribe)

    chunks_received = []

    async def on_chunk(segs):
        chunks_received.append(list(segs))

    from pathlib import Path

    result = await _transcribe_whisper(Path("/fake/audio.wav"), "key", "en", on_chunk=on_chunk)

    assert len(chunks_received) == 2
    # First chunk: offset 0
    assert chunks_received[0][0]["text"] == "chunk1"
    assert chunks_received[0][0]["start"] == 0.0
    # Second chunk: offset 5.0
    assert chunks_received[1][0]["text"] == "chunk2"
    assert chunks_received[1][0]["start"] == 5.0
    # Full result should have both
    assert len(result) == 2


@pytest.mark.asyncio
async def test_on_chunk_called_once_for_single_chunk(monkeypatch):
    """Single-chunk file calls on_chunk exactly once."""
    from src.services.transcribe import _transcribe_whisper

    segs = [{"start": 0.0, "end": 1.0, "text": "single"}]

    async def fake_transcribe(_path, _key, _lang, _prompt):
        return list(segs)

    async def fake_split(_path, **kwargs):
        from pathlib import Path

        return [Path("/fake/audio.wav")]

    monkeypatch.setattr("src.services.transcribe.split_audio", fake_split)
    monkeypatch.setattr("src.services.whisper.transcribe_with_whisper", fake_transcribe)

    chunks_received = []

    async def on_chunk(s):
        chunks_received.append(list(s))

    from pathlib import Path

    result = await _transcribe_whisper(Path("/fake/audio.wav"), "key", "en", on_chunk=on_chunk)

    assert len(chunks_received) == 1
    assert chunks_received[0][0]["text"] == "single"
    assert len(result) == 1


# -- Streaming pipeline integration test --


@pytest.mark.asyncio
async def test_streaming_pipeline_writes_segments_json(monkeypatch):
    """Streaming pipeline persists segments_json and publishes SSE events."""
    from src.models import Job
    from src.services import transcribe as transcribe_mod

    job = Job(
        id="test-streaming",
        filename="x.wav",
        file_size=1,
        provider="whisper",
        enable_refine=True,
        enable_verify=False,
    )

    fake_segments = segment_factory(3)

    async def fake_get_credential(_session, _provider):
        return "fake-key"

    async def fake_extract(_path, out_path):
        out_path.write_bytes(b"")
        return 1.0

    # on_chunk is called inside _run_transcription; we need to simulate it
    async def fake_run_transcription(*_args, **kwargs):
        on_chunk = kwargs.get("on_chunk")
        if on_chunk:
            await on_chunk(fake_segments)
        return list(fake_segments)

    async def fake_get_refine_model(_session, _provider_name):
        return "gpt-test"

    async def fake_load_custom_prompts(_session):
        return {}

    # Mock refine_with_llm to return uppercase text
    async def fake_refine(segments, *args, **kwargs):
        refined = [{"start": s["start"], "end": s["end"], "text": s["text"].upper()} for s in segments]
        return refined, 10, 10

    def fake_save_srt(_content, _path):
        pass

    monkeypatch.setattr(transcribe_mod, "_get_credential", fake_get_credential)
    monkeypatch.setattr(transcribe_mod, "extract_audio", fake_extract)
    monkeypatch.setattr(transcribe_mod, "_run_transcription", fake_run_transcription)
    monkeypatch.setattr(transcribe_mod, "_get_refine_model", fake_get_refine_model)
    monkeypatch.setattr(transcribe_mod, "_load_custom_prompts", fake_load_custom_prompts)
    monkeypatch.setattr(transcribe_mod, "save_srt", fake_save_srt)
    monkeypatch.setattr("src.services.refine.refine_with_llm", fake_refine)

    # Track SSE publishes
    published_events = []
    original_publish = transcribe_mod.status_manager.publish

    async def tracking_publish(job_id, status, detail=None, extra=None):
        if extra and extra.get("event") == "segments.appended":
            published_events.append(extra)
        await original_publish(job_id, status, detail=detail, extra=extra)

    monkeypatch.setattr(transcribe_mod.status_manager, "publish", tracking_publish)

    # Mock cost logging
    monkeypatch.setattr(transcribe_mod, "log_cost", AsyncMock())
    monkeypatch.setattr(transcribe_mod, "estimate_llm_cost", lambda *a: 0.001)

    # Place upload file
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

    # Verify segments_json was written
    assert job.segments_json is not None
    stored = json.loads(job.segments_json)
    assert len(stored) == 3
    # Refine should have uppercased the text
    assert stored[0]["text"] == "SEGMENT 1"

    # Verify SSE event was published
    assert len(published_events) == 1
    assert published_events[0]["event"] == "segments.appended"
    assert len(published_events[0]["segments"]) == 3

    # Verify SRT was generated (job completed)
    assert job.status == "completed"


# -- Graceful degradation test --


@pytest.mark.asyncio
async def test_streaming_refine_failure_uses_raw_segments(monkeypatch):
    """When per-chunk refine fails, raw segments are used (graceful degradation)."""
    from src.models import Job
    from src.services import transcribe as transcribe_mod

    job = Job(
        id="test-degrade",
        filename="x.wav",
        file_size=1,
        provider="whisper",
        enable_refine=True,
        enable_verify=False,
    )

    fake_segments = segment_factory(2)

    async def fake_get_credential(_session, _provider):
        return "fake-key"

    async def fake_extract(_path, out_path):
        out_path.write_bytes(b"")
        return 1.0

    async def fake_run_transcription(*_args, **kwargs):
        on_chunk = kwargs.get("on_chunk")
        if on_chunk:
            await on_chunk(fake_segments)
        return list(fake_segments)

    async def fake_get_refine_model(_session, _provider_name):
        return "gpt-test"

    async def fake_load_custom_prompts(_session):
        return {}

    async def fake_refine_fails(*args, **kwargs):
        raise RuntimeError("LLM unavailable")

    def fake_save_srt(_content, _path):
        pass

    monkeypatch.setattr(transcribe_mod, "_get_credential", fake_get_credential)
    monkeypatch.setattr(transcribe_mod, "extract_audio", fake_extract)
    monkeypatch.setattr(transcribe_mod, "_run_transcription", fake_run_transcription)
    monkeypatch.setattr(transcribe_mod, "_get_refine_model", fake_get_refine_model)
    monkeypatch.setattr(transcribe_mod, "_load_custom_prompts", fake_load_custom_prompts)
    monkeypatch.setattr(transcribe_mod, "save_srt", fake_save_srt)
    monkeypatch.setattr("src.services.refine.refine_with_llm", fake_refine_fails)
    monkeypatch.setattr(transcribe_mod, "log_cost", AsyncMock())
    monkeypatch.setattr(transcribe_mod, "estimate_llm_cost", lambda *a: 0.0)

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

    # Raw segments should be used (not uppercased)
    assert job.segments_json is not None
    stored = json.loads(job.segments_json)
    assert stored[0]["text"] == "Segment 1"  # original, not refined
    assert job.status == "completed"


# -- refine_with_llm context_before test --


@pytest.mark.asyncio
async def test_refine_context_before_included_in_prompt(monkeypatch):
    """When context_before is provided, it appears in the LLM prompt."""
    from unittest.mock import patch

    from src.services.refine import refine_with_llm

    captured_prompt = []

    async def fake_refine_openai(prompt, *args, **kwargs):
        captured_prompt.append(prompt)
        return [{"start": 0, "end": 1, "text": "refined"}], 10, 10

    with patch("src.services.refine._refine_openai_compat", fake_refine_openai):
        context = [{"start": 0, "end": 1, "text": "previous"}]
        await refine_with_llm(
            [{"start": 1, "end": 2, "text": "current"}],
            "key",
            "openai",
            "gpt-test",
            context_before=context,
        )

    assert len(captured_prompt) == 1
    assert "Prior context" in captured_prompt[0]
    assert "previous" in captured_prompt[0]


@pytest.mark.asyncio
async def test_refine_no_context_before_omits_section(monkeypatch):
    """When context_before is None/empty, no context section in prompt."""
    from unittest.mock import patch

    from src.services.refine import refine_with_llm

    captured_prompt = []

    async def fake_refine_openai(prompt, *args, **kwargs):
        captured_prompt.append(prompt)
        return [{"start": 0, "end": 1, "text": "refined"}], 10, 10

    with patch("src.services.refine._refine_openai_compat", fake_refine_openai):
        await refine_with_llm(
            [{"start": 0, "end": 1, "text": "current"}],
            "key",
            "openai",
            "gpt-test",
        )

    assert len(captured_prompt) == 1
    assert "Prior context" not in captured_prompt[0]


# -- status_manager.publish extra test --


@pytest.mark.asyncio
async def test_status_manager_publish_extra_merged():
    """publish() with extra dict merges into the SSE data payload."""
    import asyncio

    from src.services.status import JobStatusManager

    mgr = JobStatusManager()
    queue: asyncio.Queue = asyncio.Queue(maxsize=10)
    mgr._subscribers["test-job"] = [queue]

    await mgr.publish(
        "test-job",
        "transcribing",
        extra={"event": "segments.appended", "segments": [{"text": "hi"}]},
    )

    data = queue.get_nowait()
    assert data["status"] == "transcribing"
    assert data["event"] == "segments.appended"
    assert data["segments"] == [{"text": "hi"}]


@pytest.mark.asyncio
async def test_status_manager_publish_without_extra():
    """publish() without extra produces standard {status} payload."""
    import asyncio

    from src.services.status import JobStatusManager

    mgr = JobStatusManager()
    queue: asyncio.Queue = asyncio.Queue(maxsize=10)
    mgr._subscribers["test-job"] = [queue]

    await mgr.publish("test-job", "transcribing")

    data = queue.get_nowait()
    assert data == {"status": "transcribing"}
    assert "event" not in data
