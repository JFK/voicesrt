from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings as app_settings
from src.database import get_session
from src.models import Setting
from src.services.crypto import decrypt, encrypt

router = APIRouter(prefix="/settings", tags=["settings"])


class KeyInput(BaseModel):
    key: str


class ModelInput(BaseModel):
    model: str


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
    result = await session.execute(select(Setting).where(Setting.key == db_key))
    setting = result.scalar_one_or_none()

    encrypted_value = encrypt(body.key)

    if setting:
        setting.value = encrypted_value
        setting.updated_at = datetime.now(UTC)
    else:
        setting = Setting(key=db_key, value=encrypted_value, encrypted=True)
        session.add(setting)

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
    result = await session.execute(select(Setting).where(Setting.key == db_key))
    setting = result.scalar_one_or_none()

    if setting:
        setting.value = body.model
        setting.updated_at = datetime.now(UTC)
    else:
        setting = Setting(key=db_key, value=body.model, encrypted=False)
        session.add(setting)

    await session.commit()
    return {"provider": provider, "model": body.model}


@router.post("/logo")
async def upload_logo(file: UploadFile, session: AsyncSession = Depends(get_session)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    logo_path = app_settings.assets_dir / "logo.png"
    logo_path.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    logo_path.write_bytes(content)
    return {"uploaded": True, "path": str(logo_path)}


@router.delete("/logo")
async def delete_logo():
    logo_path = app_settings.assets_dir / "logo.png"
    if logo_path.exists():
        logo_path.unlink()
    return {"deleted": True}


def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "****"
    return key[:4] + "..." + key[-4:]
