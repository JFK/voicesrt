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
    assert _parse_silence_ranges(SAMPLE_STDERR) == [(4.123, 4.876), (12.5, 13.0)]


def test_parse_silence_ranges_drops_unmatched_start():
    text = "silence_start: 1.0\nsilence_start: 2.0\nsilence_end: 2.5"
    assert _parse_silence_ranges(text) == [(2.0, 2.5)]


def test_parse_silence_ranges_empty():
    assert _parse_silence_ranges("no matches here\n") == []


# -- _compute_chunk_boundaries --


def test_boundaries_silence_found_snaps_to_anchor():
    """When silence midpoints fall within ±window of each target, snap to them."""
    silences = [(597.5, 599.5), (1202.7, 1203.7)]  # midpoints 598.5, 1203.2
    boundaries = _compute_chunk_boundaries(1500.0, 600.0, silences)
    assert boundaries == [0.0, 598.5, 1203.2, 1500.0]


def test_boundaries_no_silence_falls_back_to_fixed():
    boundaries = _compute_chunk_boundaries(1500.0, 600.0, silences=[])
    assert boundaries == [0.0, 600.0, 1200.0, 1500.0]


def test_boundaries_silence_outside_window_falls_back():
    """A silence far from any target is ignored."""
    silences = [(50.0, 51.0)]
    boundaries = _compute_chunk_boundaries(1500.0, 600.0, silences)
    assert boundaries == [0.0, 600.0, 1200.0, 1500.0]


def test_boundaries_mixed_anchor_and_fallback():
    """Targets without nearby silence fall back; targets with nearby silence snap."""
    silences = [(1198.2, 1199.2)]  # midpoint 1198.7, only near target=1200
    boundaries = _compute_chunk_boundaries(1500.0, 600.0, silences)
    assert boundaries == [0.0, 600.0, 1198.7, 1500.0]


def test_boundaries_skips_anchor_near_end():
    """An anchor within _MIN_CHUNK_SEC of total_duration is rejected and the loop stops."""
    silences = [(1204.0, 1205.0)]  # midpoint 1204.5, would create a 0.5s tail chunk
    boundaries = _compute_chunk_boundaries(1205.0, 600.0, silences)
    assert boundaries == [0.0, 600.0, 1205.0]


# -- split_audio integration (mocked ffmpeg) --


@pytest.mark.asyncio
async def test_split_audio_short_circuits_when_under_chunk_size():
    audio = Path("/tmp/short.wav")
    with patch("src.services.audio.get_audio_duration", new=AsyncMock(return_value=120.0)):
        result = await split_audio(audio, chunk_duration_sec=600)
    assert result == [audio]


@pytest.mark.asyncio
async def test_split_audio_short_circuits_when_only_tail_remains():
    """Audio just slightly longer than chunk_duration → boundary computation
    rejects the only target as too-close-to-end. split_audio must return the
    original path instead of creating a single redundant chunk file.
    """
    audio = Path("/tmp/borderline.wav")
    # 600.5s with chunk_duration=600 → boundaries collapse to [0.0, 600.5]
    with (
        patch("src.services.audio.get_audio_duration", new=AsyncMock(return_value=600.5)),
        patch("src.services.audio.find_all_silences", new=AsyncMock(return_value=[])),
        patch("src.services.audio._run_ffmpeg", new=AsyncMock(return_value=b"")) as mock_ffmpeg,
    ):
        result = await split_audio(audio, chunk_duration_sec=600)
    assert result == [audio]
    assert mock_ffmpeg.call_count == 0


@pytest.mark.asyncio
async def test_split_audio_creates_chunks_at_boundaries(tmp_path):
    """split_audio invokes ffmpeg once per chunk with -ss / -t / -c copy."""
    audio = tmp_path / "long.wav"
    audio.touch()

    silences = [(597.5, 599.5), (1202.7, 1203.7)]  # midpoints 598.5, 1203.2
    with (
        patch("src.services.audio.get_audio_duration", new=AsyncMock(return_value=1500.0)),
        patch("src.services.audio.find_all_silences", new=AsyncMock(return_value=silences)),
        patch("src.services.audio._run_ffmpeg", new=AsyncMock(return_value=b"")) as mock_ffmpeg,
    ):
        result = await split_audio(audio, chunk_duration_sec=600)

    assert [p.name for p in result] == [
        "long_chunk000.wav",
        "long_chunk001.wav",
        "long_chunk002.wav",
    ]
    assert mock_ffmpeg.call_count == 3

    # Verify each call: -ss <start> -i <file> -t <len> -c copy
    expected_starts = [0.0, 598.5, 1203.2]
    expected_lens = [598.5, 604.7, 296.8]
    for call, exp_start, exp_len in zip(mock_ffmpeg.call_args_list, expected_starts, expected_lens, strict=True):
        args = call.args
        assert float(args[args.index("-ss") + 1]) == pytest.approx(exp_start)
        assert float(args[args.index("-t") + 1]) == pytest.approx(exp_len)
        assert "-c" in args and args[args.index("-c") + 1] == "copy"
