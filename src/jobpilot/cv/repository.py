"""
JobPilot — CV Repository
CRUD para CVs generados en PostgreSQL.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobpilot.core.logger import get_logger
from jobpilot.cv.generator import AdaptedCV
from jobpilot.database.models import CandidateProfile, GeneratedCV, JobOffer

logger = get_logger("cv.repository")


class CVRepository:
    """CRUD para la tabla generated_cv."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_offer(self, job_offer_id: uuid.UUID) -> GeneratedCV | None:
        """Retorna el CV generado para una oferta, o None."""
        return self._session.scalar(
            select(GeneratedCV).where(GeneratedCV.job_offer_id == job_offer_id)
        )

    def save(
        self,
        job_offer: JobOffer,
        profile: CandidateProfile,
        adapted_cv: AdaptedCV,
        pdf_path: Path | str,
    ) -> GeneratedCV:
        """Persiste un CV generado en la tabla generated_cv."""
        # Verificar si ya existe
        existing = self.get_for_offer(job_offer.id)
        if existing:
            existing.file_path = str(pdf_path)
            existing.emphasis_notes = adapted_cv.emphasis_notes
            existing.adaptation_method = adapted_cv.adaptation_method
            self._session.flush()
            logger.info(f"CV actualizado para '{job_offer.title[:40]}'")
            return existing

        cv = GeneratedCV(
            job_offer_id=job_offer.id,
            profile_id=profile.id,
            file_path=str(pdf_path),
            emphasis_notes=adapted_cv.emphasis_notes,
            adaptation_method=adapted_cv.adaptation_method,
        )
        self._session.add(cv)
        self._session.flush()
        logger.info(f"CV guardado para '{job_offer.title[:40]}': {pdf_path}")
        return cv

    def cleanup_old(self, days: int = 7) -> int:
        """Elimina CVs generados mas antiguos que N dias del disco y BD."""
        cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
        from datetime import timedelta

        cutoff = cutoff - timedelta(days=days)

        old_cvs = self._session.scalars(
            select(GeneratedCV).where(GeneratedCV.generated_at < cutoff)
        ).all()

        deleted = 0
        for cv in old_cvs:
            # Eliminar archivo del disco
            pdf = Path(cv.file_path)
            if pdf.exists():
                pdf.unlink()
                logger.debug(f"PDF eliminado: {pdf}")

            self._session.delete(cv)
            deleted += 1

        if deleted:
            self._session.flush()
            logger.info(f"Limpieza: {deleted} CVs antiguos eliminados (>{days} dias)")

        return deleted
