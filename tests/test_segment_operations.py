"""Tests for SRT Editor segment operations (merge, delete, add, time validation)."""

import pytest

from tests.helpers import cleanup_job, create_test_job

# ---------------------------------------------------------------------------
# Segment time validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_segments_valid(make_client):
    job_id = await create_test_job(make_client)
    try:
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Hello"},
            {"start": 2.0, "end": 4.0, "text": "World"},
        ]
        async with make_client() as c:
            resp = await c.put(
                f"/api/jobs/{job_id}/segments",
                json={"segments": segments},
            )
        assert resp.status_code == 200
        assert resp.json()["segment_count"] == 2
    finally:
        await cleanup_job(make_client, job_id)


@pytest.mark.asyncio
async def test_update_segments_start_after_end(make_client):
    job_id = await create_test_job(make_client)
    try:
        segments = [
            {"start": 3.0, "end": 2.0, "text": "Invalid"},
        ]
        async with make_client() as c:
            resp = await c.put(
                f"/api/jobs/{job_id}/segments",
                json={"segments": segments},
            )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "SEGMENT_TIME_ORDER"
        assert "start must be before end" in resp.json()["error"]["message"]
    finally:
        await cleanup_job(make_client, job_id)


@pytest.mark.asyncio
async def test_update_segments_overlap(make_client):
    job_id = await create_test_job(make_client)
    try:
        segments = [
            {"start": 0.0, "end": 3.0, "text": "First"},
            {"start": 2.0, "end": 4.0, "text": "Overlapping"},
        ]
        async with make_client() as c:
            resp = await c.put(
                f"/api/jobs/{job_id}/segments",
                json={"segments": segments},
            )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "SEGMENT_OVERLAP"
        assert "overlaps" in resp.json()["error"]["message"]
    finally:
        await cleanup_job(make_client, job_id)


@pytest.mark.asyncio
async def test_update_segments_equal_start_end(make_client):
    """start == end should be rejected."""
    job_id = await create_test_job(make_client)
    try:
        segments = [
            {"start": 1.0, "end": 1.0, "text": "Zero duration"},
        ]
        async with make_client() as c:
            resp = await c.put(
                f"/api/jobs/{job_id}/segments",
                json={"segments": segments},
            )
        assert resp.status_code == 400
    finally:
        await cleanup_job(make_client, job_id)


@pytest.mark.asyncio
async def test_update_segments_adjacent_ok(make_client):
    """Segments that touch (end == next start) should be valid."""
    job_id = await create_test_job(make_client)
    try:
        segments = [
            {"start": 0.0, "end": 2.0, "text": "First"},
            {"start": 2.0, "end": 4.0, "text": "Second"},
            {"start": 4.0, "end": 6.0, "text": "Third"},
        ]
        async with make_client() as c:
            resp = await c.put(
                f"/api/jobs/{job_id}/segments",
                json={"segments": segments},
            )
        assert resp.status_code == 200
    finally:
        await cleanup_job(make_client, job_id)


# ---------------------------------------------------------------------------
# Get segments returns glossary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_segments_includes_glossary(make_client):
    job_id = await create_test_job(make_client)
    try:
        async with make_client() as c:
            resp = await c.get(f"/api/jobs/{job_id}/segments")
        assert resp.status_code == 200
        data = resp.json()
        assert "glossary" in data
        assert "segments" in data
        assert len(data["segments"]) == 3
    finally:
        await cleanup_job(make_client, job_id)


# ---------------------------------------------------------------------------
# Media endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_media_endpoint_returns_file(make_client):
    """Media endpoint should return the uploaded file."""
    job_id = await create_test_job(make_client)
    try:
        async with make_client() as c:
            resp = await c.get(f"/api/jobs/{job_id}/media")
        # test.mp3 upload file exists (4 bytes), should serve it
        assert resp.status_code == 200
        assert "audio" in resp.headers.get("content-type", "")
    finally:
        await cleanup_job(make_client, job_id)


# ---------------------------------------------------------------------------
# Speaker download
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_srt_by_speaker(make_client):
    """Download SRT filtered by speaker should return only matching segments."""
    job_id = await create_test_job(make_client)
    try:
        # Assign speaker to segments 0 and 2
        async with make_client() as c:
            resp = await c.put(
                f"/api/jobs/{job_id}/speakers",
                json={
                    "speakers": ["Alice", "Bob"],
                    "speaker_map": {"0": "Alice", "1": "Bob", "2": "Alice"},
                },
            )
            assert resp.status_code == 200

            # Download Alice's segments
            resp = await c.get(f"/api/jobs/{job_id}/download?speaker=Alice")
            assert resp.status_code == 200
            content = resp.text
            assert "Segment 1" in content
            assert "Segment 3" in content
            assert "Segment 2" not in content

            # Download non-existent speaker
            resp = await c.get(f"/api/jobs/{job_id}/download?speaker=Nobody")
            assert resp.status_code == 404
    finally:
        await cleanup_job(make_client, job_id)


@pytest.mark.asyncio
async def test_download_srt_by_speaker_unicode_filename(make_client):
    """Speaker download with non-ASCII names should not crash."""
    job_id = await create_test_job(make_client)
    try:
        async with make_client() as c:
            await c.put(
                f"/api/jobs/{job_id}/speakers",
                json={"speakers": ["幸山"], "speaker_map": {"0": "幸山"}},
            )
            resp = await c.get(
                f"/api/jobs/{job_id}/download",
                params={"speaker": "幸山"},
            )
            assert resp.status_code == 200
            assert "content-disposition" in resp.headers
    finally:
        await cleanup_job(make_client, job_id)
