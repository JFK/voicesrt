"""Tests for waveform peak extraction (services.peaks)."""

import asyncio
import json
import shutil
import struct
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.peaks import (
    PEAKS_TARGET_BUCKETS,
    generate_peaks,
    get_or_generate_peaks,
)

FIXTURE = Path(__file__).parent / "fixtures" / "test.mp3"

# Skip the ffmpeg-driven cases when the binary is absent (e.g. fresh dev
# environment without the system dependency installed). CI installs ffmpeg
# explicitly; the cache-only test below still exercises the pure-Python path.
_needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)


@_needs_ffmpeg
@pytest.mark.asyncio
async def test_generate_peaks_returns_normalized_envelope():
    result = await generate_peaks(FIXTURE, target_buckets=300)

    assert "peaks" in result
    assert "duration" in result
    assert result["duration"] > 0
    # ±1 because the trailing partial-bucket may emit one extra peak.
    assert abs(len(result["peaks"]) - 300) <= 1
    assert all(0.0 <= p <= 1.0 for p in result["peaks"])
    # A real audio file should produce non-trivial amplitude somewhere.
    assert max(result["peaks"]) > 0.0


@_needs_ffmpeg
@pytest.mark.asyncio
async def test_generate_peaks_default_bucket_count():
    result = await generate_peaks(FIXTURE)
    assert abs(len(result["peaks"]) - PEAKS_TARGET_BUCKETS) <= 1


@_needs_ffmpeg
@pytest.mark.asyncio
async def test_get_or_generate_peaks_caches_to_disk(tmp_path):
    cache_dir = tmp_path / "peaks"
    job_id = "test-job-cache"

    first = await get_or_generate_peaks(job_id, FIXTURE, cache_dir)
    cache_file = cache_dir / f"{job_id}.json"
    assert cache_file.exists()

    # Second call with the same source must hit the cache. We can't probe a
    # bogus path here anymore — the source-stamp would invalidate the entry
    # (see test_get_or_generate_peaks_regenerates_when_source_changes) — so
    # the cache-hit assertion is on a same-source repeat instead.
    second = await get_or_generate_peaks(job_id, FIXTURE, cache_dir)
    assert second == first


@pytest.mark.asyncio
async def test_get_or_generate_peaks_returns_cached_value(tmp_path):
    cache_dir = tmp_path / "peaks"
    cache_dir.mkdir()
    job_id = "preseeded"
    source = "/nonexistent.mp3"
    expected = {"peaks": [0.1, 0.2, 0.3], "duration": 12.5, "source": source}
    (cache_dir / f"{job_id}.json").write_text(json.dumps(expected))

    result = await get_or_generate_peaks(job_id, Path(source), cache_dir)
    assert result == expected


@pytest.mark.asyncio
async def test_get_or_generate_peaks_regenerates_when_source_changes(tmp_path):
    """A cache stamped with a different source must be invalidated.

    This is the contract that keeps issue #73's waveform aligned with the
    SRT timeline: switching the playback source from the original upload
    to the extracted audio must force a regeneration instead of returning
    the previously cached envelope.
    """
    cache_dir = tmp_path / "peaks"
    cache_dir.mkdir()
    job_id = "stale"
    stale = {"peaks": [0.0], "duration": 1.0, "source": "/old/source.mp3"}
    (cache_dir / f"{job_id}.json").write_text(json.dumps(stale))

    fake_result = {"peaks": [0.9], "duration": 9.0}
    with patch("src.services.peaks.generate_peaks", new=AsyncMock(return_value=fake_result)) as mock_gen:
        result = await get_or_generate_peaks(job_id, Path("/new/source.mp3"), cache_dir)

    mock_gen.assert_awaited_once()
    assert result["peaks"] == [0.9]
    assert result["source"] == "/new/source.mp3"


@pytest.mark.asyncio
async def test_get_or_generate_peaks_treats_corrupt_cache_as_miss(tmp_path):
    """A partial / corrupt cache write (concurrent writer) regenerates cleanly.

    Treating ``json.JSONDecodeError`` as a cache miss keeps a transient mid-
    flush window from surfacing as a 500 to the client.
    """
    cache_dir = tmp_path / "peaks"
    cache_dir.mkdir()
    job_id = "corrupt"
    (cache_dir / f"{job_id}.json").write_text("{not valid json")

    fake_result = {"peaks": [0.5], "duration": 5.0}
    with patch("src.services.peaks.generate_peaks", new=AsyncMock(return_value=fake_result)) as mock_gen:
        result = await get_or_generate_peaks(job_id, Path("/some/source.mp3"), cache_dir)

    mock_gen.assert_awaited_once()
    assert result["peaks"] == [0.5]


# ---- ffmpeg-mocked tests: exercise the bucketing/cache/locking logic on CI
# runners that don't have the binary installed. These complement the real
# ffmpeg integration tests above.


def _fake_proc(pcm_bytes: bytes, *, returncode: int = 0, stderr: bytes = b""):
    """Build a mock asyncio subprocess that streams ``pcm_bytes`` from stdout."""
    proc = MagicMock()
    proc.returncode = returncode

    chunks = [pcm_bytes[i : i + 1024] for i in range(0, len(pcm_bytes), 1024)] + [b""]
    proc.stdout = MagicMock()
    proc.stdout.read = AsyncMock(side_effect=chunks)
    proc.stderr = MagicMock()
    proc.stderr.read = AsyncMock(return_value=stderr)
    proc.wait = AsyncMock()
    proc.kill = MagicMock()
    return proc


@pytest.mark.asyncio
async def test_generate_peaks_buckets_pcm_amplitude_correctly():
    """Each bucket's emitted peak == max |sample| / 32768 over its samples."""
    target = 10
    samples_per_bucket = 400  # matches duration=1s × PEAKS_SAMPLE_RATE=4000 / 10
    samples: list[int] = []
    for b in range(target):
        bucket = [(b + 1) * 100] * (samples_per_bucket - 1) + [-(b + 1) * 100]
        samples.extend(bucket)
    pcm = struct.pack(f"<{len(samples)}h", *samples)

    proc = _fake_proc(pcm)
    with (
        patch("src.services.peaks.get_audio_duration", new=AsyncMock(return_value=1.0)),
        patch("src.services.peaks.asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)),
    ):
        result = await generate_peaks(Path("/fake.mp3"), target_buckets=target)

    assert result["duration"] == 1.0
    assert len(result["peaks"]) == target
    for b, peak in enumerate(result["peaks"]):
        assert peak == pytest.approx((b + 1) * 100 / 32768.0)


@pytest.mark.asyncio
async def test_generate_peaks_zero_duration_raises():
    with patch("src.services.peaks.get_audio_duration", new=AsyncMock(return_value=0)):
        with pytest.raises(RuntimeError, match="zero duration"):
            await generate_peaks(Path("/fake.mp3"))


@pytest.mark.asyncio
async def test_generate_peaks_propagates_ffmpeg_failure():
    proc = _fake_proc(b"", returncode=1, stderr=b"ffmpeg: invalid input")
    with (
        patch("src.services.peaks.get_audio_duration", new=AsyncMock(return_value=10.0)),
        patch("src.services.peaks.asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)),
    ):
        with pytest.raises(RuntimeError, match="ffmpeg peak extraction failed"):
            await generate_peaks(Path("/fake.mp3"))


@pytest.mark.asyncio
async def test_get_or_generate_peaks_writes_compact_cache(tmp_path):
    cache_dir = tmp_path / "peaks"
    fake_result = {"peaks": [0.1, 0.2], "duration": 5.0}

    with patch("src.services.peaks.generate_peaks", new=AsyncMock(return_value=fake_result)) as mock_gen:
        result = await get_or_generate_peaks("job-compact", Path("/fake.mp3"), cache_dir)

    assert result == fake_result
    mock_gen.assert_awaited_once()

    cache_file = cache_dir / "job-compact.json"
    text = cache_file.read_text()
    # Compact separators keep the JSON small for transfer.
    assert ", " not in text
    assert ": " not in text
    assert json.loads(text) == fake_result


@pytest.mark.asyncio
async def test_get_or_generate_peaks_concurrent_calls_share_one_generation(tmp_path):
    """Per-job lock must collapse concurrent requests into a single ffmpeg run."""
    cache_dir = tmp_path / "peaks"
    fake_result = {"peaks": [0.5], "duration": 1.0}
    call_count = 0

    async def slow_generate(media_path):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return fake_result

    with patch("src.services.peaks.generate_peaks", new=slow_generate):
        results = await asyncio.gather(
            get_or_generate_peaks("shared-job", Path("/fake.mp3"), cache_dir),
            get_or_generate_peaks("shared-job", Path("/fake.mp3"), cache_dir),
            get_or_generate_peaks("shared-job", Path("/fake.mp3"), cache_dir),
        )

    assert all(r == fake_result for r in results)
    assert call_count == 1, f"expected 1 generate_peaks call, got {call_count}"
