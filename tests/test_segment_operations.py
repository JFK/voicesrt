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
# Media / audio endpoints
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


async def _set_audio_path(job_id: str, audio_path) -> None:
    from sqlalchemy import select

    from src.database import async_session
    from src.models import Job

    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one()
        job.audio_path = str(audio_path)
        await session.commit()


@pytest.mark.asyncio
async def test_audio_endpoint_uses_audio_path_when_present(make_client):
    """When job.audio_path points to an extracted file, /audio serves that file.

    This is the fix for #73: the editor must play the same audio whose timeline
    the SRT segments are anchored to, not the original upload that may drift
    due to MP4 edit lists or codec delay.
    """
    from src.config import settings

    job_id = await create_test_job(make_client)
    audio_path = settings.audio_dir / f"{job_id}.wav"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    extracted_payload = b"EXTRACTED_AUDIO_BYTES"
    audio_path.write_bytes(extracted_payload)
    try:
        await _set_audio_path(job_id, audio_path)
        async with make_client() as c:
            resp = await c.get(f"/api/jobs/{job_id}/audio")
        assert resp.status_code == 200
        assert resp.content == extracted_payload
        assert resp.headers.get("content-type") == "audio/wav"
    finally:
        await cleanup_job(make_client, job_id)


@pytest.mark.asyncio
async def test_audio_endpoint_falls_back_to_upload_for_legacy_jobs(make_client):
    """Jobs created before the audio_path column was added still play back.

    audio_path is NULL → endpoint falls back to the original upload, preserving
    backward compatibility for any job in the DB before this migration ran.
    """
    job_id = await create_test_job(make_client)
    try:
        async with make_client() as c:
            resp = await c.get(f"/api/jobs/{job_id}/audio")
        assert resp.status_code == 200
        assert "audio" in resp.headers.get("content-type", "")
    finally:
        await cleanup_job(make_client, job_id)


@pytest.mark.asyncio
async def test_audio_endpoint_404_when_both_sources_missing(make_client):
    """Neither audio_path file nor uploads file → 404, not crash."""
    from src.config import settings

    job_id = await create_test_job(make_client)
    try:
        await _set_audio_path(job_id, "/nonexistent/path.wav")
        for f in settings.uploads_dir.glob(f"{job_id}.*"):
            f.unlink(missing_ok=True)
        async with make_client() as c:
            resp = await c.get(f"/api/jobs/{job_id}/audio")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "MEDIA_NOT_FOUND"
    finally:
        await cleanup_job(make_client, job_id)


@pytest.mark.asyncio
async def test_media_endpoint_serves_original_when_audio_path_set(make_client):
    """`/media` keeps serving the upload even when audio_path is populated.

    The two endpoints have separate responsibilities: /media is for the
    original media file (download, future video preview), /audio is for the
    timestamp-aligned playback. Conflating them was the bug that gate1 caught.
    """
    from src.config import settings

    job_id = await create_test_job(make_client)
    audio_path = settings.audio_dir / f"{job_id}.wav"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"EXTRACTED")
    try:
        await _set_audio_path(job_id, audio_path)
        async with make_client() as c:
            resp = await c.get(f"/api/jobs/{job_id}/media")
        assert resp.status_code == 200
        # Upload file is `test.mp3` (4 bytes "fake") — not the extracted bytes.
        assert resp.content != b"EXTRACTED"
        assert resp.content == b"fake"
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
