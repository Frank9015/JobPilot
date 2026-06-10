"""
JobPilot — Token Guardian
Guardián de cuota diaria de Gemini API.
Verifica límites ANTES de cada llamada y registra uso DESPUÉS.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jobpilot.core.config import get_config
from jobpilot.core.logger import get_logger

logger = get_logger("token_guardian")


class GeminiOperation(StrEnum):
    PARSE_CV = "parse_cv"
    SCORE_JOB = "score_job"
    ADAPT_CV = "adapt_cv"
    ANSWER_QUESTION = "answer_question"


class GeminiModel(StrEnum):
    FLASH = "flash"
    PRO = "pro"


class QuotaExceededError(Exception):
    """Se lanza cuando se supera la cuota diaria de Gemini."""
    pass


class TokenGuardian:
    """
    Gestiona cuota diaria de Gemini API.
    
    Uso:
        guardian = TokenGuardian(db_session)
        guardian.check_quota(GeminiModel.FLASH, GeminiOperation.SCORE_JOB)
        # ... llamada a Gemini ...
        guardian.record_usage(model, operation, tokens_in, tokens_out)
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._config = get_config()

    # ── Verificación de cuota ─────────────────────────────────────────────────
    def check_quota(
        self,
        model: GeminiModel,
        operation: GeminiOperation,
    ) -> None:
        """
        Verifica si hay cuota disponible antes de llamar a Gemini.
        Lanza QuotaExceededError si no hay margen.
        """
        from jobpilot.database.models import GeminiUsageLog  # import tardío

        today = date.today()
        today_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)

        # Contar requests de hoy para este modelo
        stmt = (
            select(func.count())
            .select_from(GeminiUsageLog)
            .where(
                GeminiUsageLog.model == model,
                GeminiUsageLog.cache_hit.is_(False),
                GeminiUsageLog.created_at >= today_start,
            )
        )
        requests_today: int = self._session.scalar(stmt) or 0

        # Verificar límites
        if model == GeminiModel.FLASH:
            limit = self._config.daily_flash_request_limit
        else:
            limit = self._config.daily_pro_request_limit

        if requests_today >= limit:
            logger.warning(
                f"[red]Cuota diaria agotada[/red] para {model}: "
                f"{requests_today}/{limit} requests hoy. "
                f"Activando modo fallback."
            )
            raise QuotaExceededError(
                f"Cuota {model} agotada: {requests_today}/{limit} requests hoy."
            )

        # Verificar tokens totales
        token_stmt = (
            select(func.sum(GeminiUsageLog.total_tokens))
            .select_from(GeminiUsageLog)
            .where(
                GeminiUsageLog.cache_hit.is_(False),
                GeminiUsageLog.created_at >= today_start,
            )
        )
        tokens_today: int = self._session.scalar(token_stmt) or 0

        if tokens_today >= self._config.daily_token_limit:
            logger.warning(
                f"[red]Límite de tokens diarios alcanzado[/red]: "
                f"{tokens_today:,}/{self._config.daily_token_limit:,}"
            )
            raise QuotaExceededError(
                f"Límite de tokens diarios alcanzado: {tokens_today:,}"
            )

        logger.debug(
            f"Cuota OK — {model} [{operation}]: "
            f"{requests_today}/{limit} requests, "
            f"{tokens_today:,}/{self._config.daily_token_limit:,} tokens hoy"
        )

    # ── Registro de uso ───────────────────────────────────────────────────────
    def record_usage(
        self,
        model: GeminiModel,
        operation: GeminiOperation,
        tokens_in: int,
        tokens_out: int,
        cache_hit: bool = False,
    ) -> None:
        """Registra el uso de tokens en gemini_usage_log."""
        from jobpilot.database.models import GeminiUsageLog

        entry = GeminiUsageLog(
            model=model,
            operation=operation,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            total_tokens=tokens_in + tokens_out,
            cache_hit=cache_hit,
        )
        self._session.add(entry)
        self._session.flush()

        if cache_hit:
            logger.debug(f"Cache hit — {operation} (ahorro: {tokens_in + tokens_out} tokens)")
        else:
            logger.info(
                f"Gemini [{model}] {operation}: "
                f"{tokens_in} in + {tokens_out} out = {tokens_in + tokens_out} tokens"
            )

    # ── Estadísticas del día ──────────────────────────────────────────────────
    def get_daily_stats(self) -> dict[str, Any]:
        """Retorna estadísticas de uso del día actual para el dashboard."""
        from jobpilot.database.models import GeminiUsageLog

        today = date.today()
        today_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)

        def count_requests(model: str, cache_hit: bool = False):
            stmt = (
                select(func.count())
                .select_from(GeminiUsageLog)
                .where(
                    GeminiUsageLog.model == model,
                    GeminiUsageLog.cache_hit.is_(cache_hit),
                    GeminiUsageLog.created_at >= today_start,
                )
            )
            return self._session.scalar(stmt) or 0

        def sum_tokens(cache_hit: bool = False):
            stmt = (
                select(func.sum(GeminiUsageLog.total_tokens))
                .select_from(GeminiUsageLog)
                .where(
                    GeminiUsageLog.cache_hit.is_(cache_hit),
                    GeminiUsageLog.created_at >= today_start,
                )
            )
            return self._session.scalar(stmt) or 0

        flash_requests = count_requests(GeminiModel.FLASH)
        pro_requests = count_requests(GeminiModel.PRO)
        tokens_used = sum_tokens(cache_hit=False)
        cache_hits = count_requests(GeminiModel.FLASH, cache_hit=True) + \
                     count_requests(GeminiModel.PRO, cache_hit=True)
        tokens_saved = sum_tokens(cache_hit=True)

        # Proyección de scorings restantes
        avg_score_tokens = 1800  # estimado por scoring
        remaining_flash = self._config.daily_flash_request_limit - flash_requests
        remaining_tokens = self._config.daily_token_limit - tokens_used
        estimated_scorings_left = min(
            remaining_flash,
            remaining_tokens // avg_score_tokens if avg_score_tokens else 0,
        )

        return {
            "flash_requests": flash_requests,
            "flash_limit": self._config.daily_flash_request_limit,
            "flash_pct": round(flash_requests / self._config.daily_flash_request_limit * 100, 1),
            "pro_requests": pro_requests,
            "pro_limit": self._config.daily_pro_request_limit,
            "pro_pct": round(pro_requests / self._config.daily_pro_request_limit * 100, 1),
            "tokens_used": tokens_used,
            "token_limit": self._config.daily_token_limit,
            "tokens_pct": round(tokens_used / self._config.daily_token_limit * 100, 1),
            "cache_hits": cache_hits,
            "tokens_saved": tokens_saved,
            "fallback_active": flash_requests >= self._config.daily_flash_request_limit,
            "estimated_scorings_left": estimated_scorings_left,
        }

    # ── Caché de resultados ───────────────────────────────────────────────────
    @staticmethod
    def make_cache_key(operation: GeminiOperation, input_data: str) -> str:
        """Genera una clave de caché SHA256 para una operación + input."""
        raw = f"{operation}:{input_data}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_cached(
        self,
        operation: GeminiOperation,
        input_data: str,
    ) -> dict | None:
        """Retorna resultado cacheado si existe, None si no."""
        from jobpilot.database.models import GeminiCache

        cache_key = self.make_cache_key(operation, input_data)
        stmt = select(GeminiCache).where(
            GeminiCache.cache_key == cache_key,
        )
        cached = self._session.scalar(stmt)
        if cached is None:
            return None
        # Verificar expiración
        if cached.expires_at and cached.expires_at < datetime.now(timezone.utc):
            self._session.delete(cached)
            return None
        return cached.output

    def save_cache(
        self,
        operation: GeminiOperation,
        model: GeminiModel,
        input_data: str,
        output: dict,
        tokens_used: int,
        expires_at: datetime | None = None,
    ) -> None:
        """Guarda un resultado en caché."""
        from jobpilot.database.models import GeminiCache

        cache_key = self.make_cache_key(operation, input_data)
        input_hash = hashlib.sha256(input_data.encode()).hexdigest()

        # Upsert manual
        existing = self._session.scalar(
            select(GeminiCache).where(GeminiCache.cache_key == cache_key)
        )
        if existing:
            existing.output = output
            existing.tokens_used = tokens_used
            existing.expires_at = expires_at
        else:
            entry = GeminiCache(
                cache_key=cache_key,
                model=model,
                operation=operation,
                input_hash=input_hash,
                output=output,
                tokens_used=tokens_used,
                expires_at=expires_at,
            )
            self._session.add(entry)
        self._session.flush()
