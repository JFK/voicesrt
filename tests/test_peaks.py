"""Tests for waveform peak extraction (services.peaks)."""

import json
from pathlib import Path

import pytest

from src.services.peaks import (
    PEAKS_TARGET_BUCKETS,
    generate_peaks,
    get_or_generate_peaks,
)

FIXTURE = Path(__file__).parent / "fixtures" / "test.mp3"


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


@pytest.mark.asyncio
async def test_generate_peaks_default_bucket_count():
    result = await generate_peaks(FIXTURE)
    assert abs(len(result["peaks"]) - PEAKS_TARGET_BUCKETS) <= 1


@pytest.mark.asyncio
async def test_get_or_generate_peaks_caches_to_disk(tmp_path):
    cache_dir = tmp_path / "peaks"
    job_id = "test-job-cache"

    first = await get_or_generate_peaks(job_id, FIXTURE, cache_dir)
    cache_file = cache_dir / f"{job_id}.json"
    assert cache_file.exists()

    # Second call must read from cache, not regenerate — corrupt the source
    # path and confirm we still get the original result.
    second = await get_or_generate_peaks(job_id, Path("/nonexistent.mp3"), cache_dir)
    assert second == first


@pytest.mark.asyncio
async def test_get_or_generate_peaks_returns_cached_value(tmp_path):
    cache_dir = tmp_path / "peaks"
    cache_dir.mkdir()
    job_id = "preseeded"
    expected = {"peaks": [0.1, 0.2, 0.3], "duration": 12.5}
    (cache_dir / f"{job_id}.json").write_text(json.dumps(expected))

    result = await get_or_generate_peaks(job_id, Path("/nonexistent.mp3"), cache_dir)
    assert result == expected
