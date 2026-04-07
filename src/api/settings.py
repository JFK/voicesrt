import logging
from datetime import UTC, datetime

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings as app_settings
from src.database import get_session
from src.errors import (
    invalid_key_provider,
    invalid_model_provider,
    invalid_ollama_url,
    invalid_refine_mode,
    key_not_configured,
    key_not_found,
    unknown_setting,
)
from src.models import Setting
from src.services.crypto import decrypt, encrypt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


async def _upsert_setting(session: AsyncSession, key: str, value: str, encrypted: bool = False):
    """Check if setting exists, update or create it."""
    result = await session.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
        setting.updated_at = datetime.now(UTC)
    else:
        setting = Setting(key=key, value=value, encrypted=encrypted)
        session.add(setting)


class KeyInput(BaseModel):
    key: str


class ModelInput(BaseModel):
    model: str


class GeneralSettingInput(BaseModel):
    value: str


@router.get("/keys")
async def list_keys(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Setting).where(Setting.encrypted == True))  # noqa: E712
    keys = result.scalars().all()
    out = []
    for k in keys:
        entry: dict = {
            "provider": k.key.replace("api_key.", ""),
            "configured": True,
            "updated_at": k.updated_at.isoformat() if k.updated_at else None,
        }
        try:
            entry["masked"] = _mask_key(decrypt(k.value))
        except InvalidToken as e:
            # Row was encrypted with a different ENCRYPTION_KEY (rotation, DB
            # restore from another env). Surface in an error state so the UI
            # can prompt re-entry instead of crashing the whole endpoint.
            # NOTE: only InvalidToken is swallowed — config errors like a
            # missing ENCRYPTION_KEY raise RuntimeError from crypto.py and
            # must propagate so they aren't silently masked.
            logger.warning("Failed to decrypt %s: %s", k.key, e)
            entry["masked"] = "****"
            entry["decryption_error"] = True
        out.append(entry)
    return out


@router.put("/keys/{provider}")
async def save_key(provider: str, body: KeyInput, session: AsyncSession = Depends(get_session)):
    if provider not in ("openai", "google"):
        raise invalid_key_provider()

    db_key = f"api_key.{provider}"
    encrypted_value = encrypt(body.key)
    await _upsert_setting(session, db_key, encrypted_value, encrypted=True)
    await session.commit()
    return {"provider": provider, "configured": True}


@router.delete("/keys/{provider}")
async def delete_key(provider: str, session: AsyncSession = Depends(get_session)):
    db_key = f"api_key.{provider}"
    result = await session.execute(select(Setting).where(Setting.key == db_key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise key_not_found()

    await session.delete(setting)
    await session.commit()
    return {"deleted": True}


@router.post("/keys/{provider}/test")
async def test_key(provider: str, session: AsyncSession = Depends(get_session)):
    if provider == "ollama":
        # Ollama doesn't use API keys; test connectivity instead
        return await _test_ollama(session)

    db_key = f"api_key.{provider}"
    result = await session.execute(select(Setting).where(Setting.key == db_key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise key_not_configured()

    api_key = decrypt(setting.value)

    try:
        if provider == "openai":
            import openai

            client = openai.AsyncOpenAI(api_key=api_key)
            await client.models.list()
        elif provider == "google":
            from google import genai

            client = genai.Client(api_key=api_key)
            client.models.list()
        return {"valid": True}
    except Exception as e:
        return {"valid": False, "error": str(e)}


async def _test_ollama(session: AsyncSession) -> dict:
    """Test Ollama connectivity by hitting the /api/tags endpoint."""
    import httpx

    from src.constants import KEY_OLLAMA_BASE_URL
    from src.services.utils import _resolve_ollama_url

    result = await session.execute(select(Setting).where(Setting.key == KEY_OLLAMA_BASE_URL))
    setting = result.scalar_one_or_none()
    base_url = _resolve_ollama_url(setting.value if setting else app_settings.default_ollama_base_url)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                return {"valid": True, "models": models}
            return {"valid": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"valid": False, "error": f"Cannot connect to Ollama at {base_url}: {e}"}


@router.get("/available-models")
async def get_available_models(session: AsyncSession = Depends(get_session)):
    """Return available models per provider for selection dropdowns."""
    import httpx

    from src.constants import KEY_OLLAMA_BASE_URL
    from src.services.utils import _resolve_ollama_url

    available: dict[str, list[str]] = {
        "openai": ["gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano"],
        "gemini": [
            "gemini-3.1-pro-preview",
            "gemini-3-flash-preview",
            "gemini-2.5-flash-lite",
        ],
        "ollama": [],
    }

    # Fetch Ollama models dynamically
    result = await session.execute(select(Setting).where(Setting.key == KEY_OLLAMA_BASE_URL))
    setting = result.scalar_one_or_none()
    base_url = _resolve_ollama_url(setting.value if setting else app_settings.default_ollama_base_url)
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
            if resp.status_code == 200:
                available["ollama"] = [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        pass

    # Current configured models
    configured = {}
    for provider in ("openai", "gemini", "ollama"):
        db_key = f"model.{provider}"
        r = await session.execute(select(Setting).where(Setting.key == db_key))
        s = r.scalar_one_or_none()
        configured[provider] = s.value if s else getattr(app_settings, f"default_{provider}_model")

    # Check which providers have API keys configured
    has_key = {}
    for provider, key in [("openai", "api_key.openai"), ("gemini", "api_key.google")]:
        r = await session.execute(select(Setting).where(Setting.key == key))
        has_key[provider] = r.scalar_one_or_none() is not None
    has_key["ollama"] = len(available["ollama"]) > 0

    return {"available": available, "configured": configured, "has_key": has_key}


@router.get("/models")
async def get_models(session: AsyncSession = Depends(get_session)):
    defaults = {
        "openai": app_settings.default_openai_model,
        "gemini": app_settings.default_gemini_model,
        "ollama": app_settings.default_ollama_model,
    }
    models = {}
    for provider, default in defaults.items():
        db_key = f"model.{provider}"
        result = await session.execute(select(Setting).where(Setting.key == db_key))
        setting = result.scalar_one_or_none()
        models[provider] = setting.value if setting else default
    return models


@router.put("/models/{provider}")
async def set_model(provider: str, body: ModelInput, session: AsyncSession = Depends(get_session)):
    if provider not in ("openai", "gemini", "ollama"):
        raise invalid_model_provider()

    db_key = f"model.{provider}"
    await _upsert_setting(session, db_key, body.model)
    await session.commit()
    return {"provider": provider, "model": body.model}


GENERAL_SETTINGS = {
    "max_upload_size_gb": {"default": str(app_settings.max_upload_size_gb), "label": "Max Upload Size (GB)"},
    "refine_model_openai": {"default": "gpt-5.4-nano", "label": "OpenAI"},
    "refine_model_gemini": {"default": "gemini-2.5-flash-lite", "label": "Gemini"},
    "refine_model_ollama": {"default": app_settings.default_ollama_model, "label": "Ollama"},
}


@router.get("/ollama-url")
async def get_ollama_url(session: AsyncSession = Depends(get_session)):
    from src.constants import KEY_OLLAMA_BASE_URL

    result = await session.execute(select(Setting).where(Setting.key == KEY_OLLAMA_BASE_URL))
    setting = result.scalar_one_or_none()
    return {"url": setting.value if setting else app_settings.default_ollama_base_url}


@router.put("/ollama-url")
async def set_ollama_url(body: GeneralSettingInput, session: AsyncSession = Depends(get_session)):
    from urllib.parse import urlparse

    from src.constants import KEY_OLLAMA_BASE_URL

    url = body.value.rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise invalid_ollama_url()

    await _upsert_setting(session, KEY_OLLAMA_BASE_URL, url)
    await session.commit()
    return {"url": url}


@router.get("/glossary")
async def get_glossary(session: AsyncSession = Depends(get_session)):
    db_key = "glossary"
    result = await session.execute(select(Setting).where(Setting.key == db_key))
    setting = result.scalar_one_or_none()
    return {"glossary": setting.value if setting else ""}


@router.put("/glossary")
async def set_glossary(body: GeneralSettingInput, session: AsyncSession = Depends(get_session)):
    await _upsert_setting(session, "glossary", body.value)
    await session.commit()
    return {"glossary": body.value}


class MetaContextInput(BaseModel):
    context: str = ""
    prompt: str = ""


@router.get("/meta-context")
async def get_meta_context(session: AsyncSession = Depends(get_session)):
    result_ctx = await session.execute(select(Setting).where(Setting.key == "meta_context"))
    result_prompt = await session.execute(select(Setting).where(Setting.key == "meta_prompt"))
    ctx = result_ctx.scalar_one_or_none()
    prompt = result_prompt.scalar_one_or_none()
    return {
        "context": ctx.value if ctx else "",
        "prompt": prompt.value if prompt else "",
    }


@router.put("/meta-context")
async def set_meta_context(body: MetaContextInput, session: AsyncSession = Depends(get_session)):
    for db_key, value in [("meta_context", body.context), ("meta_prompt", body.prompt)]:
        await _upsert_setting(session, db_key, value)
    await session.commit()
    return {"saved": True}


@router.get("/general")
async def get_general_settings(session: AsyncSession = Depends(get_session)):
    result = {}
    for key, meta in GENERAL_SETTINGS.items():
        db_key = f"general.{key}"
        r = await session.execute(select(Setting).where(Setting.key == db_key))
        setting = r.scalar_one_or_none()
        result[key] = {
            "value": setting.value if setting else meta["default"],
            "label": meta["label"],
        }
    return result


@router.put("/general/{key}")
async def set_general_setting(key: str, body: GeneralSettingInput, session: AsyncSession = Depends(get_session)):
    if key not in GENERAL_SETTINGS:
        raise unknown_setting(key)

    db_key = f"general.{key}"
    await _upsert_setting(session, db_key, body.value)
    await session.commit()
    return {"key": key, "value": body.value}


@router.get("/pricing")
async def get_pricing(session: AsyncSession = Depends(get_session)):
    """Get all model pricing (defaults merged with custom)."""
    import json as json_mod

    from src.services.cost import DEFAULT_PRICING

    result = await session.execute(select(Setting).where(Setting.key == "pricing"))
    setting = result.scalar_one_or_none()
    custom = {}
    if setting:
        try:
            custom = json_mod.loads(setting.value)
        except Exception:
            pass
    merged = {**DEFAULT_PRICING, **custom}
    return {"pricing": merged, "has_custom": bool(custom)}


@router.put("/pricing")
async def set_pricing(request: Request, session: AsyncSession = Depends(get_session)):
    """Save custom model pricing."""
    import json as json_mod

    from src.services.cost import load_pricing_from_db

    body = await request.json()
    pricing = body.get("pricing", {})
    await _upsert_setting(session, "pricing", json_mod.dumps(pricing))
    await session.commit()
    await load_pricing_from_db(session)
    return {"saved": True}


@router.get("/refine-prompts")
async def get_refine_prompts(session: AsyncSession = Depends(get_session)):
    """Get custom refine prompts (empty string means use default)."""
    from src.api.jobs import VALID_REFINE_MODES
    from src.services.refine import _PROMPT_MAP

    result = {}
    for mode in VALID_REFINE_MODES:
        db_key = f"general.refine_prompt_{mode}"
        r = await session.execute(select(Setting).where(Setting.key == db_key))
        setting = r.scalar_one_or_none()
        result[mode] = {
            "custom": setting.value if setting else "",
            "default": _PROMPT_MAP[mode],
        }
    return result


@router.put("/refine-prompts/{mode}")
async def set_refine_prompt(mode: str, body: GeneralSettingInput, session: AsyncSession = Depends(get_session)):
    from src.api.jobs import VALID_REFINE_MODES

    if mode not in VALID_REFINE_MODES:
        raise invalid_refine_mode(", ".join(VALID_REFINE_MODES))
    db_key = f"general.refine_prompt_{mode}"
    await _upsert_setting(session, db_key, body.value)
    await session.commit()
    return {"mode": mode, "saved": True}


@router.delete("/refine-prompts/{mode}")
async def reset_refine_prompt(mode: str, session: AsyncSession = Depends(get_session)):
    """Reset a refine prompt to default by deleting the custom override."""
    from src.api.jobs import VALID_REFINE_MODES

    if mode not in VALID_REFINE_MODES:
        raise invalid_refine_mode(", ".join(VALID_REFINE_MODES))
    db_key = f"general.refine_prompt_{mode}"
    result = await session.execute(select(Setting).where(Setting.key == db_key))
    setting = result.scalar_one_or_none()
    if setting:
        await session.delete(setting)
        await session.commit()
    return {"mode": mode, "reset": True}


@router.get("/tone-references")
async def get_tone_references(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Setting).where(Setting.key == "tone_references"))
    setting = result.scalar_one_or_none()
    return {"tone_references": setting.value if setting else ""}


@router.put("/tone-references")
async def set_tone_references(body: GeneralSettingInput, session: AsyncSession = Depends(get_session)):
    await _upsert_setting(session, "tone_references", body.value)
    await session.commit()
    return {"saved": True}


def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "****"
    return key[:4] + "..." + key[-4:]
