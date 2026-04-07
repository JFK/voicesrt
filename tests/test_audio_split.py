"""Tests for silence-aware audio chunking (services.audio)."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.services.audio import (
    _compute_chunk_boundaries,
    _parse_silence_ranges,
    split_audio,
)

# -- _parse_silence_ranges --

SAMPLE_STDERR = """\
[silencedetect @ 0x55] silence_start: 4.123
[silencedetect @ 0x55] silence_end: 4.876 | silence_duration: 0.753
[silencedetect @ 0x55] silence_start: 12.5
[silencedetect @ 0x55] silence_end: 13.0 | silence_duration: 0.5
size=N/A time=00:00:30.00 bitrate=N/A speed=900x
"""


def test_parse_silence_ranges_basic():
    ranges = _parse_silence_ranges(SAMPLE_STDERR, offset_sec=0.0)
    assert ranges == [(4.123, 4.876), (12.5, 13.0)]


def test_parse_silence_ranges_applies_offset():
    ranges = _parse_silence_ranges(SAMPLE_STDERR, offset_sec=100.0)
    assert ranges == [(104.123, 104.876), (112.5, 113.0)]


def test_parse_silence_ranges_drops_unmatched_start():
    text = "silence_start: 1.0\nsilence_start: 2.0\nsilence_end: 2.5"
    # The first start has no end and should be dropped; second start matches.
    assert _parse_silence_ranges(text, 0.0) == [(2.0, 2.5)]


def test_parse_silence_ranges_empty():
    assert _parse_silence_ranges("no matches here\n", 0.0) == []


# -- _compute_chunk_boundaries --


@pytest.mark.asyncio
async def test_boundaries_silence_found_snaps_to_anchor():
    """When silence is found near each target, boundaries snap to it."""
    # 25-min audio, 10-min chunks → targets at 600 and 1200
    # Mock find_silence_near to return slightly offset anchors
    with patch("src.services.audio.find_silence_near", new=AsyncMock(side_effect=[598.5, 1203.2])):
        boundaries = await _compute_chunk_boundaries(
            audio_path=Path("/tmp/fake.wav"),
            total_duration=1500.0,
            chunk_duration_sec=600.0,
        )
    assert boundaries == [0.0, 598.5, 1203.2, 1500.0]


@pytest.mark.asyncio
async def test_boundaries_no_silence_falls_back_to_fixed():
    """When find_silence_near returns None, boundaries fall back to fixed targets."""
    with patch("src.services.audio.find_silence_near", new=AsyncMock(return_value=None)):
        boundaries = await _compute_chunk_boundaries(
            audio_path=Path("/tmp/fake.wav"),
            total_duration=1500.0,
            chunk_duration_sec=600.0,
        )
    assert boundaries == [0.0, 600.0, 1200.0, 1500.0]


@pytest.mark.asyncio
async def test_boundaries_mixed_anchor_and_fallback():
    """Some boundaries find silence, others fall back."""
    with patch(
        "src.services.audio.find_silence_near",
        new=AsyncMock(side_effect=[None, 1198.7]),
    ):
        boundaries = await _compute_chunk_boundaries(
            audio_path=Path("/tmp/fake.wav"),
            total_duration=1500.0,
            chunk_duration_sec=600.0,
        )
    # First boundary falls back to 600.0, second snaps to 1198.7
    assert boundaries == [0.0, 600.0, 1198.7, 1500.0]


@pytest.mark.asyncio
async def test_boundaries_rejects_anchor_too_close_to_previous():
    """An anchor that would create a sub-_MIN_CHUNK_SEC chunk is rejected."""
    # First call snaps to 600.0, second call returns 600.5 (only 0.5s after) → rejected
    with patch(
        "src.services.audio.find_silence_near",
        new=AsyncMock(side_effect=[600.0, 600.5]),
    ):
        boundaries = await _compute_chunk_boundaries(
            audio_path=Path("/tmp/fake.wav"),
            total_duration=1800.0,
            chunk_duration_sec=600.0,
        )
    # Second target was 1200.0; rejected anchor falls back to 1200.0
    assert boundaries == [0.0, 600.0, 1200.0, 1800.0]


@pytest.mark.asyncio
async def test_boundaries_skips_anchor_near_end():
    """If the anchor is within _MIN_CHUNK_SEC of the end, stop adding boundaries."""
    # Audio is 1205s, target is 1200, anchor at 1204.5 → too close to end
    with patch("src.services.audio.find_silence_near", new=AsyncMock(return_value=1204.5)):
        boundaries = await _compute_chunk_boundaries(
            audio_path=Path("/tmp/fake.wav"),
            total_duration=1205.0,
            chunk_duration_sec=600.0,
        )
    # Only the first target produces a real boundary (silence anchor=1204.5
    # for target=600 is rejected because 1204.5 is past target+window normally,
    # but the mock returns it regardless — we get [0, 1204.5, 1205] and the
    # second loop iteration sees target=1804.5 > duration so loop exits)
    # The end-of-audio guard rejects the 1204.5 anchor since it's within
    # _MIN_CHUNK_SEC of total_duration=1205.
    assert boundaries == [0.0, 1205.0]


# -- split_audio integration (mocked ffmpeg) --


@pytest.mark.asyncio
async def test_split_audio_short_circuits_when_under_chunk_size():
    """Audio shorter than chunk_duration returns the original path unchanged."""
    audio = Path("/tmp/short.wav")
    with patch("src.services.audio.get_audio_duration", new=AsyncMock(return_value=120.0)):
        result = await split_audio(audio, chunk_duration_sec=600)
    assert result == [audio]


@pytest.mark.asyncio
async def test_split_audio_creates_chunks_at_boundaries(tmp_path):
    """split_audio invokes ffmpeg once per chunk with the computed boundaries."""
    audio = tmp_path / "long.wav"
    audio.touch()

    # 1500s audio, 600s chunks → boundaries [0, 598.5, 1203.2, 1500]
    # → 3 chunks
    with (
        patch("src.services.audio.get_audio_duration", new=AsyncMock(return_value=1500.0)),
        patch("src.services.audio.find_silence_near", new=AsyncMock(side_effect=[598.5, 1203.2])),
        patch("src.services.audio._run_ffmpeg", new=AsyncMock(return_value=b"")) as mock_ffmpeg,
    ):
        result = await split_audio(audio, chunk_duration_sec=600)

    assert len(result) == 3
    assert result[0].name == "long_chunk000.wav"
    assert result[1].name == "long_chunk001.wav"
    assert result[2].name == "long_chunk002.wav"
    # ffmpeg called 3 times (one per chunk)
    assert mock_ffmpeg.call_count == 3
    # Verify the -ss / -t pairs match the computed boundaries
    calls = [call.args for call in mock_ffmpeg.call_args_list]
    assert "-ss" in calls[0] and str(0.0) in calls[0]
    assert "-ss" in calls[1] and str(598.5) in calls[1]
    assert "-ss" in calls[2] and str(1203.2) in calls[2]
