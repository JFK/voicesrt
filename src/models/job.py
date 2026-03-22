import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.database import utcnow


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename: Mapped[str] = mapped_column(String, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    audio_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    srt_path: Mapped[str | None] = mapped_column(String, nullable=True)
    youtube_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    youtube_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    youtube_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    catchphrases: Mapped[str | None] = mapped_column(Text, nullable=True)
    quiz: Mapped[str | None] = mapped_column(Text, nullable=True)
    enable_metadata: Mapped[bool] = mapped_column(Boolean, default=False)
    enable_refine: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
