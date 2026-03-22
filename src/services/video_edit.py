import asyncio
from pathlib import Path

from src.config import settings


async def embed_video(job, embed_srt: bool = True, embed_logo: bool = False) -> Path:
    """Embed subtitles and/or logo into video using ffmpeg.

    Returns path to the output video file.
    """
    mp4_path = settings.uploads_dir / f"{job.id}.mp4"

    # If original was deleted, check for it
    if not mp4_path.exists():
        raise FileNotFoundError(
            f"Original MP4 not found at {mp4_path}. "
            "Re-upload the video to embed subtitles."
        )

    output_path = settings.output_dir / f"{job.id}_edited.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    srt_path = Path(job.srt_path) if job.srt_path else None
    logo_path = settings.assets_dir / "logo.png"

    filters = []

    # Build filter chain
    if embed_srt and srt_path and srt_path.exists():
        # Escape path for ffmpeg subtitles filter (colons and backslashes)
        escaped_srt = str(srt_path).replace("\\", "\\\\").replace(":", "\\:")
        subtitle_style = (
            "FontName=Noto Sans CJK JP,"
            "FontSize=22,"
            "PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,"
            "BackColour=&H80000000,"
            "BorderStyle=4,"
            "Outline=2,"
            "Shadow=0,"
            "MarginV=30"
        )
        filters.append(f"subtitles='{escaped_srt}':force_style='{subtitle_style}'")

    cmd = ["ffmpeg", "-y", "-i", str(mp4_path)]

    if embed_logo and logo_path.exists():
        cmd.extend(["-i", str(logo_path)])

        if filters:
            # Combine logo overlay + subtitle filter
            filter_complex = (
                f"[1:v]scale=80:80[logo];"
                f"[0:v][logo]overlay=10:10[v1];"
                f"[v1]{filters[0]}"
            )
        else:
            filter_complex = "[1:v]scale=80:80[logo];[0:v][logo]overlay=10:10"

        cmd.extend(["-filter_complex", filter_complex])
    elif filters:
        cmd.extend(["-vf", filters[0]])
    else:
        # No editing needed, just copy
        cmd.extend(["-c", "copy"])

    cmd.extend(["-c:a", "copy", str(output_path)])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg video editing failed: {stderr.decode()}")

    return output_path
