"""Pre-flight validation of LLM model availability per provider.

The job submission path calls `validate_job_models()` before audio is uploaded
so a stale/typo'd model name fails fast (HTTP 400) instead of burning extraction
time and surfacing as a vague late error.

Transport-level failures (provider unreachable, auth errors) are NOT raised
here — they should be caught by the actual API call later. This validator only
flags the case where the provider is reachable AND tells us the model does not
exist.

A small in-memory cache (5 min TTL) avoids hitting the provider's catalog
endpoint on every upload.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import get_provider_name
from src.errors import model_not_available
from src.services.utils import create_openai_compatible_client, fetch_ollama_models

logger = logging.getLogger(__name__)

_CACHE_TTL_SEC = 300
# Key: (api_provider, model, credential_fingerprint) -> (is_valid, expires_at_monotonic)
_cache: dict[tuple[str, str, str], tuple[bool, float]] = {}
_cache_lock = asyncio.Lock()


class ModelNotAvailableError(Exception):
    """Raised when a provider's catalog confirms the model does not exist."""

    def __init__(self, provider: str, model: str, detail: str = ""):
        self.provider = provider
        self.model = model
        self.detail = detail
        super().__init__(f"Model '{model}' not available for provider '{provider}'")


def _fingerprint(credential: str) -> str:
    """Stable per-process cache key component that never reveals the credential."""
    return f"{len(credential)}:{hash(credential) & 0xFFFFFFFF:08x}"


async def validate_model(api_provider: str, model: str, credential: str) -> None:
    """Verify that `model` is in `api_provider`'s catalog.

    `api_provider` is the API-level name: "openai", "gemini", or "ollama".
    For ollama, `credential` is the base URL.

    Raises:
        ModelNotAvailableError: provider is reachable and rejected the model.
    """
    if not model:
        return

    cache_key = (api_provider, model, _fingerprint(credential))
    now = time.monotonic()

    async with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and cached[1] > now:
            if cached[0]:
                return
            raise ModelNotAvailableError(api_provider, model, "(cached)")

    try:
        await _check(api_provider, model, credential)
    except ModelNotAvailableError:
        async with _cache_lock:
            _cache[cache_key] = (False, time.monotonic() + _CACHE_TTL_SEC)
        raise

    async with _cache_lock:
        _cache[cache_key] = (True, time.monotonic() + _CACHE_TTL_SEC)


def clear_cache() -> None:
    """Test helper — drop the validation cache."""
    _cache.clear()


async def _check(api_provider: str, model: str, credential: str) -> None:
    if api_provider == "openai":
        await _check_openai(model, credential)
    elif api_provider == "gemini":
        await _check_gemini(model, credential)
    elif api_provider == "ollama":
        await _check_ollama(model, credential)
    else:
        logger.debug("validate_model: unknown provider '%s' — skipping", api_provider)


async def _check_openai(model: str, credential: str) -> None:
    import openai

    client = create_openai_compatible_client("openai", credential)
    try:
        await client.models.retrieve(model)
    except openai.NotFoundError as e:
        raise ModelNotAvailableError("openai", model, str(e)) from e
    except Exception as e:
        # Auth/network issues are not our concern — let the real call surface them.
        logger.warning("OpenAI model validation skipped (transport): %s", e)


async def _check_gemini(model: str, credential: str) -> None:
    try:
        from google import genai  # type: ignore[import-not-found]
    except ImportError:
        logger.debug("google-genai not installed — skipping Gemini validation")
        return

    full_name = model if model.startswith("models/") else f"models/{model}"

    def _retrieve():
        client = genai.Client(api_key=credential)
        return client.models.get(model=full_name)

    try:
        await asyncio.to_thread(_retrieve)
    except Exception as e:
        # google-genai does not expose structured 404 — fall back to string match.
        msg = str(e)
        if "404" in msg or "NOT_FOUND" in msg or "not found" in msg.lower():
            raise ModelNotAvailableError("gemini", model, msg) from e
        logger.warning("Gemini model validation skipped (transport): %s", e)


async def _check_ollama(model: str, base_url: str) -> None:
    available = await fetch_ollama_models(base_url)
    if not available:
        # Unreachable / empty catalog — non-blocking.
        logger.warning("Ollama validation skipped (no catalog returned)")
        return
    # Allow exact match, or "qwen3" matching "qwen3:30b" (tag-less prefix).
    if model in available or any(name.startswith(f"{model}:") for name in available):
        return
    raise ModelNotAvailableError(
        "ollama",
        model,
        f"Available: {', '.join(sorted(available))}",
    )


# ---------------------------------------------------------------------------
# Job-level orchestration (called from src/api/jobs.py before upload)
# ---------------------------------------------------------------------------


async def _collect_targets(
    session: AsyncSession,
    provider: str,
    model_override: str | None,
    enable_refine: bool,
    enable_verify: bool,
    enable_metadata: bool,
) -> list[tuple[str, str]]:
    """De-duplicated (api_provider, model) pairs for a job submission.

    Whisper transcription uses a hardcoded `whisper-1` and needs no check.
    Ollama jobs delegate transcription to whisper, so only their post-processing
    (refine/metadata) model is checked.
    """
    from src.services.transcribe import _get_model, _get_refine_model

    api_provider = get_provider_name(provider)

    # Each entry: (target_api_provider, awaitable_for_model_name)
    plan: list[tuple[str, Awaitable[str]]] = []
    if provider == "gemini":
        plan.append(("gemini", _get_model(session, "gemini", model_override)))
    if enable_metadata:
        plan.append((api_provider, _get_model(session, provider)))
    if enable_refine or enable_verify:
        plan.append((api_provider, _get_refine_model(session, api_provider)))

    if not plan:
        return []

    coros: list[Awaitable[str]] = [coro for _, coro in plan]
    resolved_models = await asyncio.gather(*coros)

    seen: set[tuple[str, str]] = set()
    deduped: list[tuple[str, str]] = []
    for (target, _), model in zip(plan, resolved_models, strict=True):
        if not model:
            continue
        key = (target, model)
        if key not in seen:
            seen.add(key)
            deduped.append(key)
    return deduped


async def validate_job_models(
    session: AsyncSession,
    provider: str,
    model_override: str | None,
    enable_refine: bool,
    enable_verify: bool,
    enable_metadata: bool,
) -> None:
    """Pre-flight: confirm every LLM model the job will touch exists.

    Raises AppError(MODEL_NOT_AVAILABLE) on first catalog rejection. Missing or
    undecryptable credentials are silently skipped — the actual API call will
    surface those as their own error later.
    """
    from src.services.transcribe import _get_credential

    targets = await _collect_targets(session, provider, model_override, enable_refine, enable_verify, enable_metadata)
    if not targets:
        return

    async def _one(api_provider: str, model: str) -> None:
        cred_provider = "whisper" if api_provider == "openai" else api_provider
        try:
            credential = await _get_credential(session, cred_provider)
        except Exception as e:
            logger.debug("model validation skipped (no credential for %s): %s", cred_provider, e)
            return
        try:
            await validate_model(api_provider, model, credential)
        except ModelNotAvailableError as e:
            raise model_not_available(api_provider, model, e.detail) from e

    await asyncio.gather(*(_one(p, m) for p, m in targets))
