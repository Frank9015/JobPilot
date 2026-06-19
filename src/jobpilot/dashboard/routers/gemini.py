"""
JobPilot Dashboard — Gemini Router
Endpoints para uso de tokens Gemini y estadísticas de IA.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from jobpilot.database.engine import get_session
from jobpilot.database.models import GeminiCache, GeminiUsageLog
from jobpilot.core.config import get_config

router = APIRouter()


@router.get("/usage")
async def get_usage_today() -> dict[str, Any]:
    """Uso de tokens Gemini del día actual."""
    config = get_config()
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    with get_session() as s:
        # Totales del día — queries simples para evitar errores de tipo
        total_requests = (
            s.scalar(
                select(func.count())
                .select_from(GeminiUsageLog)
                .where(GeminiUsageLog.created_at >= today_start)
            )
            or 0
        )

        tokens_in = (
            s.scalar(
                select(func.coalesce(func.sum(GeminiUsageLog.tokens_in), 0)).where(
                    GeminiUsageLog.created_at >= today_start
                )
            )
            or 0
        )

        tokens_out = (
            s.scalar(
                select(func.coalesce(func.sum(GeminiUsageLog.tokens_out), 0)).where(
                    GeminiUsageLog.created_at >= today_start
                )
            )
            or 0
        )

        cache_hits = (
            s.scalar(
                select(func.count())
                .select_from(GeminiUsageLog)
                .where(
                    GeminiUsageLog.created_at >= today_start,
                    GeminiUsageLog.cache_hit == True,
                )
            )
            or 0
        )

        cache_entries = s.scalar(select(func.count()).select_from(GeminiCache)) or 0

        # Por operación
        by_op = s.execute(
            select(
                GeminiUsageLog.operation,
                func.count().label("count"),
                func.coalesce(
                    func.sum(GeminiUsageLog.tokens_in + GeminiUsageLog.tokens_out), 0
                ).label("tokens"),
            )
            .where(GeminiUsageLog.created_at >= today_start)
            .group_by(GeminiUsageLog.operation)
        ).all()

    total_tokens = int(tokens_in) + int(tokens_out)
    token_limit = config.daily_token_limit
    request_limit = config.daily_flash_request_limit

    return {
        "today": {
            "requests": total_requests,
            "tokens_in": int(tokens_in),
            "tokens_out": int(tokens_out),
            "tokens_total": total_tokens,
            "cache_hits": cache_hits,
            "cache_entries": cache_entries,
        },
        "limits": {
            "token_limit": token_limit,
            "request_limit": request_limit,
            "token_pct": (
                round(total_tokens / token_limit * 100, 2) if token_limit else 0
            ),
            "request_pct": (
                round(total_requests / request_limit * 100, 2) if request_limit else 0
            ),
        },
        "by_operation": [
            {"operation": op, "count": count, "tokens": int(tokens)}
            for op, count, tokens in by_op
        ],
    }


@router.get("/history")
async def get_usage_history(days: int = 7) -> list[dict[str, Any]]:
    """Historial de uso por día."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    with get_session() as s:
        rows = s.execute(
            select(
                func.date_trunc("day", GeminiUsageLog.created_at).label("day"),
                func.count().label("requests"),
                func.coalesce(
                    func.sum(GeminiUsageLog.tokens_in + GeminiUsageLog.tokens_out), 0
                ).label("tokens"),
            )
            .where(GeminiUsageLog.created_at >= cutoff)
            .group_by(func.date_trunc("day", GeminiUsageLog.created_at))
            .order_by(func.date_trunc("day", GeminiUsageLog.created_at))
        ).all()

    return [
        {
            "date": day.isoformat() if day else None,
            "requests": count,
            "tokens": int(tokens),
        }
        for day, count, tokens in rows
    ]
