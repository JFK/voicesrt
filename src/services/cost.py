from sqlalchemy.ext.asyncio import AsyncSession

from src.models import CostLog

# Pricing constants
WHISPER_COST_PER_MINUTE = 0.006  # USD

GEMINI_PRICING = {
    "gemini-2.5-flash": {"input_per_1m": 0.15, "output_per_1m": 0.60},
    "gemini-2.0-flash": {"input_per_1m": 0.10, "output_per_1m": 0.40},
}
GEMINI_AUDIO_TOKENS_PER_SECOND = 32

OPENAI_PRICING = {
    "gpt-4.1": {"input_per_1m": 2.00, "output_per_1m": 8.00},
    "gpt-4.1-mini": {"input_per_1m": 0.40, "output_per_1m": 1.60},
    "gpt-4.1-nano": {"input_per_1m": 0.10, "output_per_1m": 0.40},
    "gpt-4o": {"input_per_1m": 2.50, "output_per_1m": 10.00},
    "gpt-4o-mini": {"input_per_1m": 0.15, "output_per_1m": 0.60},
}


def estimate_whisper_cost(duration_sec: float) -> float:
    return (duration_sec / 60.0) * WHISPER_COST_PER_MINUTE


def estimate_gemini_cost(duration_sec: float, output_tokens: int, model: str = "gemini-2.5-flash") -> float:
    pricing = GEMINI_PRICING.get(model, GEMINI_PRICING["gemini-2.5-flash"])
    input_tokens = duration_sec * GEMINI_AUDIO_TOKENS_PER_SECOND
    input_cost = (input_tokens / 1_000_000) * pricing["input_per_1m"]
    output_cost = (output_tokens / 1_000_000) * pricing["output_per_1m"]
    return input_cost + output_cost


def estimate_llm_cost(input_tokens: int, output_tokens: int, model: str, provider: str) -> float:
    if provider == "openai":
        pricing = OPENAI_PRICING.get(model, OPENAI_PRICING["gpt-4.1"])
    else:
        pricing = GEMINI_PRICING.get(model, GEMINI_PRICING["gemini-2.5-flash"])
    input_cost = (input_tokens / 1_000_000) * pricing["input_per_1m"]
    output_cost = (output_tokens / 1_000_000) * pricing["output_per_1m"]
    return input_cost + output_cost


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
