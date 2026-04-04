# Provider mapping: transcription provider -> API provider name
PROVIDER_API_MAP = {"whisper": "openai", "gemini": "gemini", "ollama": "ollama"}

# Settings keys
KEY_API_OPENAI = "api_key.openai"
KEY_API_GOOGLE = "api_key.google"
KEY_MODEL_OPENAI = "model.openai"
KEY_MODEL_GEMINI = "model.gemini"
KEY_MODEL_OLLAMA = "model.ollama"
KEY_OLLAMA_BASE_URL = "ollama.base_url"

# Job statuses
STATUS_PENDING = "pending"
STATUS_EXTRACTING = "extracting"
STATUS_TRANSCRIBING = "transcribing"
STATUS_REFINING = "refining"
STATUS_GENERATING_METADATA = "generating_metadata"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


def get_provider_name(job_provider: str) -> str:
    """Map transcription provider to API provider name."""
    return PROVIDER_API_MAP.get(job_provider, job_provider)
