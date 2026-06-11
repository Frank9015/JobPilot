"""
JobPilot Dashboard — Control Router
Endpoints para controlar la ejecución del sistema (scrape, score, generate CVs).
"""
from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter

from jobpilot.core.config import get_config, get_settings
from jobpilot.database.engine import verify_connection

router = APIRouter()

# Estado global de tareas en background
_running_tasks: dict[str, bool] = {}


@router.get("/status")
async def get_system_status() -> dict[str, Any]:
    """Estado actual del sistema."""
    settings = get_settings()
    config = get_config()

    return {
        "db_connected": verify_connection(),
        "gemini_mode": "mock" if settings.gemini_mock_mode else "real",
        "enabled_portals": config.enabled_portals,
        "min_score": config.min_score_to_apply,
        "headful": config.headful,
        "running_tasks": {k: v for k, v in _running_tasks.items() if v},
    }


@router.post("/scrape")
async def trigger_scrape() -> dict[str, Any]:
    """Lanza scraping en background."""
    if _running_tasks.get("scrape"):
        return {"success": False, "message": "Scraping ya en ejecucion"}

    def run():
        _running_tasks["scrape"] = True
        try:
            from jobpilot.scraper.manager import ScraperManager
            manager = ScraperManager()
            manager.run_scrape_cycle()
        finally:
            _running_tasks["scrape"] = False

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    return {"success": True, "message": "Scraping iniciado en background"}


@router.post("/score")
async def trigger_score() -> dict[str, Any]:
    """Lanza scoring en background."""
    if _running_tasks.get("score"):
        return {"success": False, "message": "Scoring ya en ejecucion"}

    def run():
        _running_tasks["score"] = True
        try:
            from jobpilot.database.engine import get_session
            from jobpilot.profile.repository import ProfileRepository
            from jobpilot.scoring.engine import ScoringEngine

            with get_session() as session:
                repo = ProfileRepository(session)
                profile = repo.get_as_profile_data()
                if profile:
                    engine = ScoringEngine(session)
                    engine.score_pending_offers(profile)
        finally:
            _running_tasks["score"] = False

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    return {"success": True, "message": "Scoring iniciado en background"}


@router.post("/generate-cvs")
async def trigger_generate_cvs() -> dict[str, Any]:
    """Genera CVs para ofertas elegibles en background."""
    if _running_tasks.get("generate_cvs"):
        return {"success": False, "message": "Generacion de CVs ya en ejecucion"}

    def run():
        _running_tasks["generate_cvs"] = True
        try:
            from jobpilot.database.engine import get_session
            from jobpilot.profile.repository import ProfileRepository
            from jobpilot.cv.generator import CVGenerator
            from jobpilot.cv.renderer import CVRenderer
            from jobpilot.cv.repository import CVRepository
            from jobpilot.database.models import JobOffer, JobScore, CandidateProfile
            from jobpilot.scoring.models import ScoreResult
            from sqlalchemy import select
            from pathlib import Path

            config = get_config()

            with get_session() as session:
                repo = ProfileRepository(session)
                profile_data = repo.get_as_profile_data()
                if not profile_data:
                    return

                offers_with_scores = session.execute(
                    select(JobOffer, JobScore)
                    .outerjoin(JobScore, JobOffer.id == JobScore.job_offer_id)
                    .where(
                        JobOffer.status == "scored",
                        JobScore.total_score >= config.min_score_to_apply,
                    )
                ).all()

                generator = CVGenerator(session)
                renderer = CVRenderer()
                cv_repo = CVRepository(session)
                profile_orm = session.scalar(
                    select(CandidateProfile).order_by(CandidateProfile.created_at.desc()).limit(1)
                )

                for offer, score in offers_with_scores:
                    existing = cv_repo.get_for_offer(offer.id)
                    if existing and Path(existing.file_path).exists():
                        continue

                    score_result = ScoreResult(
                        total_score=float(score.total_score or 0),
                        skill_match=float(score.skill_match or 0),
                    ) if score else None

                    adapted = generator.adapt_cv(profile_data, offer, score_result)

                    safe_company = (offer.company or "unknown").replace(" ", "_")[:20]
                    filename = f"cv_{safe_company}_{offer.id.hex[:8]}.pdf"
                    filename = "".join(c for c in filename if c.isalnum() or c in "_-.").lower()
                    output_path = config.cv_generated_dir / filename

                    renderer.render(profile_data, adapted, output_path)
                    if profile_orm:
                        cv_repo.save(offer, profile_orm, adapted, output_path)
                    offer.status = "cv_ready"
                    session.flush()
        finally:
            _running_tasks["generate_cvs"] = False

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    return {"success": True, "message": "Generacion de CVs iniciada en background"}
