from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "VideoSRT"
    data_dir: Path = Path("data")
    encryption_key: str = ""

    # Default LLM models
    default_openai_model: str = "gpt-5.4"
    default_gemini_model: str = "gemini-3.1-flash-lite"

    # Upload settings
    max_upload_size_gb: int = 10

    # Whisper settings
    whisper_chunk_duration_sec: int = 600  # 10 minutes

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.data_dir / 'db' / 'videosrt.db'}"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def srt_dir(self) -> Path:
        return self.data_dir / "srt"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"

    @property
    def assets_dir(self) -> Path:
        return self.data_dir / "assets"


settings = Settings()
