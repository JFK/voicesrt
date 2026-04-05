"""Structured error responses with error codes.

All API errors return a consistent JSON format:
{
    "error": {
        "code": "ERROR_CODE",
        "message": "Human-readable message"
    }
}
"""

from fastapi import HTTPException


class AppError(HTTPException):
    """Application error with a machine-readable error code."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(status_code=status_code, detail={"code": code, "message": message})
        self.code = code
        self.message = message


def job_not_found() -> AppError:
    return AppError(404, "JOB_NOT_FOUND", "Job not found")


def invalid_provider(provider: str) -> AppError:
    return AppError(400, "INVALID_PROVIDER", f"Invalid provider: {provider}")


def no_file_provided() -> AppError:
    return AppError(400, "NO_FILE_PROVIDED", "No file provided")


def unsupported_format(supported: str) -> AppError:
    return AppError(400, "UNSUPPORTED_FORMAT", f"Unsupported format. Supported: {supported}")


def file_too_large(max_gb: int) -> AppError:
    return AppError(413, "FILE_TOO_LARGE", f"File too large. Max: {max_gb}GB")


def upload_failed() -> AppError:
    return AppError(500, "UPLOAD_FAILED", "Upload failed")


def glossary_too_long() -> AppError:
    return AppError(400, "GLOSSARY_TOO_LONG", "Glossary too long. Max 5000 characters.")


def invalid_refine_mode(valid_modes: str) -> AppError:
    return AppError(400, "INVALID_REFINE_MODE", f"Invalid refine_mode. Must be one of: {valid_modes}")


def srt_not_found() -> AppError:
    return AppError(404, "SRT_NOT_FOUND", "SRT file not found")


def srt_file_missing() -> AppError:
    return AppError(404, "SRT_FILE_MISSING", "SRT file not found on disk")


def srt_not_available() -> AppError:
    return AppError(400, "SRT_NOT_AVAILABLE", "No SRT file available")


def no_speaker_segments(speaker: str) -> AppError:
    return AppError(404, "NO_SPEAKER_SEGMENTS", f"No segments for speaker: {speaker}")


def media_not_found() -> AppError:
    return AppError(404, "MEDIA_NOT_FOUND", "Media file not found")


def no_segments_provided() -> AppError:
    return AppError(400, "NO_SEGMENTS_PROVIDED", "No segments provided")


def invalid_segment(index: int) -> AppError:
    return AppError(400, "INVALID_SEGMENT", f"Invalid segment at index {index}")


def segment_timing_invalid(index: int) -> AppError:
    return AppError(400, "SEGMENT_TIMING_INVALID", f"Segment {index}: start and end must be numeric")


def segment_time_order(index: int) -> AppError:
    return AppError(400, "SEGMENT_TIME_ORDER", f"Segment {index}: start must be before end")


def segment_overlap(index: int) -> AppError:
    return AppError(400, "SEGMENT_OVERLAP", f"Segment {index}: overlaps with previous segment")


def invalid_segment_index(index: int) -> AppError:
    return AppError(400, "INVALID_SEGMENT_INDEX", f"Invalid segment index: {index}")


def invalid_key_provider() -> AppError:
    return AppError(400, "INVALID_KEY_PROVIDER", "Provider must be 'openai' or 'google'")


def key_not_found() -> AppError:
    return AppError(404, "KEY_NOT_FOUND", "Key not found")


def key_not_configured() -> AppError:
    return AppError(404, "KEY_NOT_CONFIGURED", "Key not configured")


def invalid_model_provider() -> AppError:
    return AppError(400, "INVALID_MODEL_PROVIDER", "Provider must be 'openai', 'gemini', or 'ollama'")


def invalid_ollama_url() -> AppError:
    return AppError(400, "INVALID_OLLAMA_URL", "URL must be http:// or https:// with a valid host")


def unknown_setting(key: str) -> AppError:
    return AppError(400, "UNKNOWN_SETTING", f"Unknown setting: {key}")


def classify_error(exc: Exception) -> str:
    """Classify an exception into a user-friendly message with actionable hint."""
    msg = str(exc)
    if isinstance(exc, TimeoutError) or "timeout" in msg.lower():
        return "Processing timed out. Try a smaller file or a faster model."
    if "401" in msg or "unauthorized" in msg.lower() or "invalid api key" in msg.lower():
        return "API key is invalid or expired. Check Settings → API Keys."
    if "429" in msg or "rate limit" in msg.lower() or "quota" in msg.lower():
        return "API rate limit reached. Wait a moment and retry."
    if "404" in msg and "model" in msg.lower():
        return "Model not found. Check Settings → LLM Models."
    if "connection" in msg.lower() and ("refused" in msg.lower() or "error" in msg.lower()):
        return "Cannot connect to the API server. Check that the service is running."
    return msg[:200] if len(msg) > 200 else msg


def actionable_error(step: str, exc: Exception, recovery: str) -> str:
    """Build a user-facing error message with context and recovery hint."""
    cause = classify_error(exc)
    return f"{step}: {cause}\n{recovery}"[:500]
