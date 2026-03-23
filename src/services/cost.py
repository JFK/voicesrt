import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import CostLog, Setting

logger = logging.getLogger(__name__)

# Default pricing (updated March 2026)
DEFAULT_WHISPER_COST_PER_MINUTE = 0.006

DEFAULT_PRICING = {
    "whisper-1": {"input_per_1m": 0.0, "output_per_1m": 0.0, "per_minute": 0.006},
    "gemini-2.5-flash-lite": {"input_per_1m": 0.10, "output_per_1m": 0.40},
    "gemini-2.5-flash": {"input_per_1m": 0.15, "output_per_1m": 0.60},
    "gemini-2.5-pro": {"input_per_1m": 1.25, "output_per_1m": 10.00},
    "gpt-5.4": {"input_per_1m": 2.50, "output_per_1m": 15.00},
    "gpt-5.4-mini": {"input_per_1m": 0.40, "output_per_1m": 1.60},
    "gpt-5.4-nano": {"input_per_1m": 0.10, "output_per_1m": 0.40},
    "gpt-4.1": {"input_per_1m": 2.00, "output_per_1m": 8.00},
    "gpt-4.1-mini": {"input_per_1m": 0.40, "output_per_1m": 1.60},
    "gpt-4o": {"input_per_1m": 2.50, "output_per_1m": 10.00},
    "gpt-4o-mini": {"input_per_1m": 0.15, "output_per_1m": 0.60},
}

GEMINI_AUDIO_TOKENS_PER_SECOND = 32

# In-memory cache (loaded from DB on first use)
_pricing_cache: dict | None = None


def _get_pricing() -> dict:
    """Get pricing dict (defaults, may be overridden by DB)."""
    global _pricing_cache
    if _pricing_cache is not None:
        return _pricing_cache
    return DEFAULT_PRICING


def set_pricing_cache(pricing: dict) -> None:
    """Set pricing cache from DB values."""
    global _pricing_cache
    _pricing_cache = pricing


def get_model_pricing(model: str) -> dict:
    """Get pricing for a specific model."""
    pricing = _get_pricing()
    return pricing.get(model, {"input_per_1m": 0.0, "output_per_1m": 0.0})


def estimate_whisper_cost(duration_sec: float) -> float:
    pricing = get_model_pricing("whisper-1")
    per_min = pricing.get("per_minute", DEFAULT_WHISPER_COST_PER_MINUTE)
    return (duration_sec / 60.0) * per_min


def estimate_gemini_cost(duration_sec: float, output_tokens: int, model: str = "gemini-2.5-flash") -> float:
    pricing = get_model_pricing(model)
    input_tokens = duration_sec * GEMINI_AUDIO_TOKENS_PER_SECOND
    input_cost = (input_tokens / 1_000_000) * pricing.get("input_per_1m", 0)
    output_cost = (output_tokens / 1_000_000) * pricing.get("output_per_1m", 0)
    return input_cost + output_cost


def estimate_llm_cost(input_tokens: int, output_tokens: int, model: str, provider: str) -> float:
    pricing = get_model_pricing(model)
    input_cost = (input_tokens / 1_000_000) * pricing.get("input_per_1m", 0)
    output_cost = (output_tokens / 1_000_000) * pricing.get("output_per_1m", 0)
    return input_cost + output_cost


async def load_pricing_from_db(session: AsyncSession) -> None:
    """Load custom pricing from DB and merge with defaults."""
    result = await session.execute(select(Setting).where(Setting.key == "pricing"))
    setting = result.scalar_one_or_none()
    if setting:
        try:
            custom = json.loads(setting.value)
            merged = {**DEFAULT_PRICING, **custom}
            set_pricing_cache(merged)
        except json.JSONDecodeError:
            logger.warning("Invalid pricing JSON in DB, using defaults")


async def log_cost(
    session: AsyncSession,
    job_id: str,
    provider: str,
    model: str,
    operation: str,
    estimated_cost: float,
    audio_duration: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    log = CostLog(
        job_id=job_id,
        provider=provider,
        model=model,
        operation=operation,
        audio_duration=audio_duration,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost=estimated_cost,
    )
    session.add(log)
    await session.commit()
