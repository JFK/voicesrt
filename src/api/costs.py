from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import CostLog

router = APIRouter(prefix="/costs", tags=["costs"])


@router.get("")
async def get_costs(session: AsyncSession = Depends(get_session)):
    # Total cost
    total_result = await session.execute(select(func.sum(CostLog.estimated_cost)))
    total = total_result.scalar() or 0.0

    # By provider
    provider_result = await session.execute(
        select(CostLog.provider, func.sum(CostLog.estimated_cost)).group_by(CostLog.provider)
    )
    by_provider = {row[0]: row[1] for row in provider_result.all()}

    # By operation
    op_result = await session.execute(
        select(CostLog.operation, func.sum(CostLog.estimated_cost)).group_by(CostLog.operation)
    )
    by_operation = {row[0]: row[1] for row in op_result.all()}

    # By month
    month_result = await session.execute(
        select(
            func.strftime("%Y-%m", CostLog.created_at).label("month"),
            func.sum(CostLog.estimated_cost),
        ).group_by("month").order_by("month")
    )
    by_month = [{"month": row[0], "cost": row[1]} for row in month_result.all()]

    # Recent logs
    recent_result = await session.execute(select(CostLog).order_by(CostLog.created_at.desc()).limit(50))
    recent = [
        {
            "job_id": log.job_id,
            "provider": log.provider,
            "model": log.model,
            "operation": log.operation,
            "audio_duration": log.audio_duration,
            "estimated_cost": log.estimated_cost,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in recent_result.scalars().all()
    ]

    return {
        "total": round(total, 6),
        "by_provider": by_provider,
        "by_operation": by_operation,
        "by_month": by_month,
        "recent": recent,
    }
