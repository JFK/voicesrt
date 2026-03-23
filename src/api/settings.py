from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings as app_settings
from src.database import get_session
from src.models import Setting
from src.services.crypto import decrypt, encrypt

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
    return [
        {
            "provider": k.key.replace("api_key.", ""),
            "configured": True,
            "masked": _mask_key(decrypt(k.value)),
            "updated_at": k.updated_at.isoformat() if k.updated_at else None,
        }
        for k in keys
    ]


@router.put("/keys/{provider}")
async def save_key(provider: str, body: KeyInput, session: AsyncSession = Depends(get_session)):
    if provider not in ("openai", "google"):
        raise HTTPException(status_code=400, detail="Provider must be 'openai' or 'google'")

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
        raise HTTPException(status_code=404, detail="Key not found")

    await session.delete(setting)
    await session.commit()
    return {"deleted": True}


@router.post("/keys/{provider}/test")
async def test_key(provider: str, session: AsyncSession = Depends(get_session)):
    db_key = f"api_key.{provider}"
    result = await session.execute(select(Setting).where(Setting.key == db_key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="Key not configured")

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


@router.get("/models")
async def get_models(session: AsyncSession = Depends(get_session)):
    models = {}
    for provider in ("openai", "gemini"):
        db_key = f"model.{provider}"
        result = await session.execute(select(Setting).where(Setting.key == db_key))
        setting = result.scalar_one_or_none()
        if setting:
            models[provider] = setting.value
        else:
            models[provider] = (
                app_settings.default_openai_model if provider == "openai" else app_settings.default_gemini_model
            )
    return models


@router.put("/models/{provider}")
async def set_model(provider: str, body: ModelInput, session: AsyncSession = Depends(get_session)):
    if provider not in ("openai", "gemini"):
        raise HTTPException(status_code=400, detail="Provider must be 'openai' or 'gemini'")

    db_key = f"model.{provider}"
    await _upsert_setting(session, db_key, body.model)
    await session.commit()
    return {"provider": provider, "model": body.model}


GENERAL_SETTINGS = {
    "max_upload_size_gb": {"default": str(app_settings.max_upload_size_gb), "label": "Max Upload Size (GB)"},
    "refine_model_openai": {"default": "gpt-5.4-nano", "label": "Refine Model (OpenAI)"},
    "refine_model_gemini": {"default": "gemini-2.5-flash-lite", "label": "Refine Model (Gemini)"},
}


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
        raise HTTPException(status_code=400, detail=f"Unknown setting: {key}")

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
        raise HTTPException(status_code=400, detail=f"Mode must be one of: {', '.join(VALID_REFINE_MODES)}")
    db_key = f"general.refine_prompt_{mode}"
    await _upsert_setting(session, db_key, body.value)
    await session.commit()
    return {"mode": mode, "saved": True}


@router.delete("/refine-prompts/{mode}")
async def reset_refine_prompt(mode: str, session: AsyncSession = Depends(get_session)):
    """Reset a refine prompt to default by deleting the custom override."""
    from src.api.jobs import VALID_REFINE_MODES

    if mode not in VALID_REFINE_MODES:
        raise HTTPException(status_code=400, detail=f"Mode must be one of: {', '.join(VALID_REFINE_MODES)}")
    db_key = f"general.refine_prompt_{mode}"
    result = await session.execute(select(Setting).where(Setting.key == db_key))
    setting = result.scalar_one_or_none()
    if setting:
        await session.delete(setting)
        await session.commit()
    return {"mode": mode, "reset": True}


def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "****"
    return key[:4] + "..." + key[-4:]
