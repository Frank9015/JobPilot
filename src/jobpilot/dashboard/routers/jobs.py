"""
JobPilot Dashboard — Jobs Router
Endpoints para ofertas laborales, scores y estadísticas.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from jobpilot.database.engine import get_session
from jobpilot.database.models import GeneratedCV, JobOffer, JobScore

router = APIRouter()


@router.get("/stats")
async def get_stats() -> dict[str, Any]:
    """Estadísticas generales de ofertas."""
    with get_session() as s:
        total = s.scalar(select(func.count()).select_from(JobOffer)) or 0
        scored = (
            s.scalar(
                select(func.count())
                .select_from(JobOffer)
                .where(JobOffer.status == "scored")
            )
            or 0
        )
        cv_ready = (
            s.scalar(
                select(func.count())
                .select_from(JobOffer)
                .where(JobOffer.status == "cv_ready")
            )
            or 0
        )
        applied = (
            s.scalar(
                select(func.count())
                .select_from(JobOffer)
                .where(JobOffer.status == "applied")
            )
            or 0
        )
        avg_score = s.scalar(select(func.avg(JobScore.total_score))) or 0

        portal_rows = s.execute(
            select(JobOffer.portal, func.count()).group_by(JobOffer.portal)
        ).all()
        by_portal = {row[0]: row[1] for row in portal_rows}

        status_rows = s.execute(
            select(JobOffer.status, func.count()).group_by(JobOffer.status)
        ).all()
        by_status = {row[0]: row[1] for row in status_rows}

    return {
        "total": total,
        "scored": scored,
        "cv_ready": cv_ready,
        "applied": applied,
        "avg_score": round(float(avg_score), 1),
        "by_portal": by_portal,
        "by_status": by_status,
    }


@router.get("")
async def list_jobs(
    status: str | None = None,
    portal: str | None = None,
    score_min: float | None = None,
    limit: int = Query(default=50, le=200),
) -> list[dict[str, Any]]:
    """Lista ofertas con filtros opcionales."""
    with get_session() as s:
        query = (
            select(JobOffer, JobScore)
            .outerjoin(JobScore, JobOffer.id == JobScore.job_offer_id)
            .order_by(JobOffer.scraped_at.desc())
            .limit(limit)
        )

        if status:
            query = query.where(JobOffer.status == status)
        if portal:
            query = query.where(JobOffer.portal == portal)
        if score_min is not None:
            query = query.where(JobScore.total_score >= score_min)

        rows = s.execute(query).all()

        results = []
        for offer, score in rows:
            results.append(
                {
                    "id": str(offer.id),
                    "title": offer.title,
                    "company": offer.company,
                    "location": offer.location,
                    "portal": offer.portal,
                    "url": offer.url,
                    "status": offer.status,
                    "modality": offer.modality,
                    "scraped_at": (
                        offer.scraped_at.isoformat() if offer.scraped_at else None
                    ),
                    "score": (
                        {
                            "total": (
                                float(score.total_score)
                                if score and score.total_score
                                else None
                            ),
                            "skill_match": (
                                float(score.skill_match)
                                if score and score.skill_match
                                else None
                            ),
                            "experience_match": (
                                float(score.experience_match)
                                if score and score.experience_match
                                else None
                            ),
                            "education_match": (
                                float(score.education_match)
                                if score and score.education_match
                                else None
                            ),
                            "location_match": (
                                float(score.location_match)
                                if score and score.location_match
                                else None
                            ),
                            "method": score.score_method if score else None,
                            "reasoning": score.gemini_reasoning if score else None,
                        }
                        if score
                        else None
                    ),
                }
            )

    return results


@router.get("/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    """Detalle de una oferta con score y CV."""
    import uuid

    with get_session() as s:
        try:
            offer = s.get(JobOffer, uuid.UUID(job_id))
            if not offer:
                return {"error": "Not found"}
        except ValueError:
            return {"error": "Invalid job ID format"}

        score = s.scalar(select(JobScore).where(JobScore.job_offer_id == offer.id))
        cv = s.scalar(select(GeneratedCV).where(GeneratedCV.job_offer_id == offer.id))

        return {
            "id": str(offer.id),
            "title": offer.title,
            "company": offer.company,
            "location": offer.location,
            "portal": offer.portal,
            "url": offer.url,
            "status": offer.status,
            "description": offer.description,
            "requirements": offer.requirements,
            "modality": offer.modality,
            "scraped_at": offer.scraped_at.isoformat() if offer.scraped_at else None,
            "score": (
                {
                    "total": float(score.total_score) if score else None,
                    "skill_match": float(score.skill_match) if score else None,
                    "experience_match": (
                        float(score.experience_match) if score else None
                    ),
                    "education_match": float(score.education_match) if score else None,
                    "method": score.score_method if score else None,
                    "reasoning": score.gemini_reasoning if score else None,
                }
                if score
                else None
            ),
            "cv": (
                {
                    "id": str(cv.id),
                    "file_path": cv.file_path,
                    "method": cv.adaptation_method,
                    "generated_at": (
                        cv.generated_at.isoformat() if cv.generated_at else None
                    ),
                }
                if cv
                else None
            ),
        }


@router.get("/{job_id}/cv/download.pdf")
async def download_cv(job_id: str) -> Any:
    """Descarga el PDF del CV generado para esta oferta."""
    import uuid
    from pathlib import Path
    from fastapi.responses import FileResponse
    from fastapi import HTTPException

    with get_session() as s:
        try:
            cv = s.scalar(
                select(GeneratedCV).where(GeneratedCV.job_offer_id == uuid.UUID(job_id))
            )
            if not cv or not cv.file_path:
                raise HTTPException(
                    status_code=404, detail="CV not found for this job offer"
                )

            file_path = Path(cv.file_path)
            if not file_path.exists():
                raise HTTPException(status_code=404, detail="PDF file missing on disk")

            return FileResponse(
                path=str(file_path),
                filename=file_path.name,
                media_type="application/pdf",
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid job ID format")
