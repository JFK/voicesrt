"""Shared test helpers. Import from here, not from conftest.py."""

from unittest.mock import MagicMock


def mock_openai_response(content: str, prompt_tokens: int = 100, completion_tokens: int = 50):
    """Create a mock OpenAI chat completion response."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=content))]
    mock_response.usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return mock_response


async def create_test_job(make_client, num_segments: int = 3) -> str:
    """Create a completed job with a real SRT file for testing."""
    async with make_client() as c:
        resp = await c.post(
            "/api/jobs?provider=whisper",
            files={"file": ("test.mp3", b"fake", "audio/mpeg")},
        )
    assert resp.status_code == 200, f"POST /api/jobs failed: {resp.status_code} {resp.text}"
    job_id = resp.json()["id"]

    from src.config import settings

    srt_dir = settings.srt_dir
    srt_dir.mkdir(parents=True, exist_ok=True)
    srt_path = srt_dir / f"{job_id}.srt"

    lines = []
    for i in range(num_segments):
        start = i * 2.0
        end = start + 2.0
        sh, sm, ss = int(start // 3600), int(start % 3600 // 60), start % 60
        eh, em, es = int(end // 3600), int(end % 3600 // 60), end % 60
        lines.append(f"{i + 1}\n{sh:02d}:{sm:02d}:{ss:06.3f}".replace(".", ","))
        lines[-1] += f" --> {eh:02d}:{em:02d}:{es:06.3f}\n".replace(".", ",")
        lines[-1] += f"Segment {i + 1}\n"
    srt_path.write_text("\n".join(lines) + "\n")

    from sqlalchemy import select

    from src.database import async_session
    from src.models import Job

    async with async_session() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one()
        job.srt_path = str(srt_path)
        job.status = "completed"
        await session.commit()

    return job_id


async def cleanup_job(make_client, job_id: str) -> None:
    """Delete a test job."""
    async with make_client() as c:
        resp = await c.delete(f"/api/jobs/{job_id}")
        assert resp.status_code in (200, 204, 404), f"Failed to clean up job {job_id}: {resp.status_code} {resp.text}"


def segment_factory(n: int = 3, duration: float = 2.0) -> list[dict]:
    """Generate N test segments with sequential timestamps."""
    return [{"start": i * duration, "end": (i + 1) * duration, "text": f"Segment {i + 1}"} for i in range(n)]
