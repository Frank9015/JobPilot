"""
JobPilot — Automation Manager
Orquesta el ciclo completo de postulación automática:
CV generation → LinkedIn Easy Apply → registro en BD.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobpilot.automation.base import BaseAutomator
from jobpilot.automation.linkedin import ApplyResult, LinkedInAutomator
from jobpilot.core.config import get_config, get_settings
from jobpilot.core.logger import get_logger
from jobpilot.cv.generator import CVGenerator
from jobpilot.cv.renderer import CVRenderer
from jobpilot.cv.repository import CVRepository
from jobpilot.database.models import (
    Application,
    AuditLog,
    CandidateProfile,
    GeneratedCV,
    JobOffer,
    JobScore,
)
from jobpilot.profile.models import ProfileData

logger = get_logger("automation.manager")


# ── Registry de automators ────────────────────────────────────────────────────
def _build_automator_registry() -> dict[str, type[BaseAutomator]]:
    """Construye el mapa de nombre_portal -> clase_automator."""
    from jobpilot.automation.linkedin import LinkedInAutomator
    from jobpilot.automation.bumeran import BumeranAutomator
    from jobpilot.automation.laborum import LaborumAutomator
    from jobpilot.automation.indeed import IndeedAutomator
    from jobpilot.automation.sence import SenceAutomator

    return {
        "linkedin": LinkedInAutomator,
        "bumeran": BumeranAutomator,
        "laborum": LaborumAutomator,
        "indeed": IndeedAutomator,
        "sence": SenceAutomator,
    }


class AutomationManager:
    """
    Gestiona el flujo completo de postulación automática.

    Pipeline por oferta elegible:
    1. Verificar score >= umbral
    2. Generar CV adaptado (si no existe)
    3. Ejecutar Easy Apply (o dry-run)
    4. Registrar resultado en tabla application + audit_log

    Uso:
        manager = AutomationManager(session)
        results = manager.run_apply_cycle(profile, dry_run=True)
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._config = get_config()
        self._settings = get_settings()
        self._registry = _build_automator_registry()
        self._cv_generator = CVGenerator(session)
        self._cv_renderer = CVRenderer()
        self._cv_repo = CVRepository(session)

    def run_apply_cycle(
        self,
        profile: ProfileData,
        dry_run: bool = True,
        portal: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Ejecuta un ciclo de postulación en todas las ofertas elegibles.

        Args:
            profile: Datos del candidato.
            dry_run: Si True, simula todo sin enviar.
            portal: Si se especifica, solo postula en ese portal.

        Returns:
            Lista de resultados por oferta.
        """
        # Obtener ofertas elegibles
        eligible = self._get_eligible_offers(portal)

        if not eligible:
            logger.info("No hay ofertas elegibles para postular")
            return []

        logger.info(
            f"{'[DRY-RUN] ' if dry_run else ''}Ciclo de postulacion: "
            f"{len(eligible)} ofertas elegibles"
        )

        results: list[dict[str, Any]] = []
        automators: dict[str, BaseAutomator] = {}

        try:
            for i, (offer, score) in enumerate(eligible, 1):
                portal_name = offer.portal

                # Verificar límite diario
                if self._check_daily_limit(portal_name):
                    logger.warning(f"Limite diario alcanzado para [{portal_name}]")
                    continue

                # Obtener o crear automator
                if portal_name not in automators:
                    automator = self._get_automator(portal_name)
                    if not automator:
                        logger.warning(f"Sin automator para [{portal_name}]")
                        continue
                    automators[portal_name] = automator

                automator = automators[portal_name]

                # Pipeline
                logger.info(f"[{i}/{len(eligible)}] {offer.title[:45]} ({offer.company or '?'})")

                result = self._apply_single(
                    offer=offer,
                    score=score,
                    profile=profile,
                    automator=automator,
                    dry_run=dry_run,
                )
                results.append(result)

        finally:
            # Cerrar todos los automators
            for automator in automators.values():
                automator.close()

        # Resumen
        applied = sum(1 for r in results if r["status"] in ("applied", "dry_run"))
        failed = sum(1 for r in results if r["status"] == "failed")
        logger.info(
            f"Ciclo completado: {applied} exitosas, {failed} fallidas "
            f"(de {len(results)} intentos)"
        )

        return results

    def _apply_single(
        self,
        offer: JobOffer,
        score: JobScore | None,
        profile: ProfileData,
        automator: BaseAutomator,
        dry_run: bool,
    ) -> dict[str, Any]:
        """Ejecuta el pipeline completo para una oferta individual."""

        result: dict[str, Any] = {
            "offer_id": str(offer.id),
            "title": offer.title,
            "company": offer.company,
            "portal": offer.portal,
            "score": float(score.total_score) if score else 0,
            "status": "pending",
            "message": "",
        }

        try:
            # 1. Generar CV adaptado (si no existe)
            cv_path = self._ensure_cv(offer, profile, score)
            result["cv_path"] = str(cv_path) if cv_path else None

            # 2. Ejecutar postulación
            apply_result = automator.apply_to_job(
                job_offer=offer,
                profile=profile,
                cv_path=cv_path,
                dry_run=dry_run,
            )

            result["status"] = apply_result.status
            result["message"] = apply_result.message
            result["fields_filled"] = apply_result.fields_filled
            result["fields_total"] = apply_result.fields_total

            # 3. Registrar en BD
            self._record_application(offer, apply_result, cv_path)

            # 4. Actualizar status de la oferta
            if apply_result.status == "applied":
                offer.status = "applied"
            elif apply_result.status == "dry_run":
                offer.status = "cv_ready"
            elif apply_result.status == "needs_human":
                offer.status = "needs_human"
            self._session.flush()

        except Exception as e:
            logger.error(f"Error en pipeline para '{offer.title[:40]}': {e}")
            result["status"] = "failed"
            result["message"] = str(e)

        return result

    def _ensure_cv(
        self,
        offer: JobOffer,
        profile: ProfileData,
        score: JobScore | None,
    ) -> Path | None:
        """Genera un CV adaptado si no existe. Retorna ruta al PDF."""

        # Verificar si ya existe
        existing = self._cv_repo.get_for_offer(offer.id)
        if existing and Path(existing.file_path).exists():
            logger.debug(f"CV existente: {existing.file_path}")
            return Path(existing.file_path)

        # Generar adaptación
        from jobpilot.scoring.models import ScoreResult
        score_result = None
        if score:
            score_result = ScoreResult(
                total_score=float(score.total_score or 0),
                skill_match=float(score.skill_match or 0),
                experience_match=float(score.experience_match or 0),
            )

        adapted = self._cv_generator.adapt_cv(profile, offer, score_result)

        # Generar nombre de archivo
        safe_company = (offer.company or "unknown").replace(" ", "_")[:20]
        safe_title = offer.title.replace(" ", "_")[:30]
        filename = f"cv_{safe_company}_{safe_title}_{offer.id.hex[:8]}.pdf"
        filename = "".join(c for c in filename if c.isalnum() or c in "_-.").lower()

        output_path = self._config.cv_generated_dir / filename

        # Renderizar PDF
        pdf_path = self._cv_renderer.render(profile, adapted, output_path)

        # Guardar en BD
        profile_orm = self._session.scalar(
            select(CandidateProfile).order_by(CandidateProfile.created_at.desc()).limit(1)
        )
        if profile_orm:
            self._cv_repo.save(offer, profile_orm, adapted, pdf_path)

        return pdf_path

    # ── Queries ───────────────────────────────────────────────────────────────
    def _get_eligible_offers(
        self,
        portal: str | None = None,
    ) -> list[tuple[JobOffer, JobScore | None]]:
        """Obtiene ofertas con score >= umbral que aún no se han postulado."""
        min_score = self._config.min_score_to_apply

        query = (
            select(JobOffer, JobScore)
            .outerjoin(JobScore, JobOffer.id == JobScore.job_offer_id)
            .where(
                JobOffer.status.in_(["scored", "cv_ready"]),
                JobScore.total_score >= min_score,
            )
            .order_by(JobScore.total_score.desc())
        )

        if portal:
            query = query.where(JobOffer.portal == portal)

        rows = self._session.execute(query).all()
        return [(offer, score) for offer, score in rows]

    def _check_daily_limit(self, portal: str) -> bool:
        """Verifica si se alcanzó el límite diario de postulaciones."""
        from sqlalchemy import func

        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )

        count = self._session.scalar(
            select(func.count()).select_from(Application).where(
                Application.applied_at >= today_start,
            )
        ) or 0

        try:
            limit = self._config.portal_daily_limit(portal)
        except (KeyError, TypeError):
            limit = 10

        return count >= limit

    def _get_automator(self, portal: str) -> BaseAutomator | None:
        """Instancia el automator correspondiente al portal."""
        cls = self._registry.get(portal)
        if not cls:
            return None
        return cls()

    # ── Registro en BD ────────────────────────────────────────────────────────
    def _record_application(
        self,
        offer: JobOffer,
        result: ApplyResult,
        cv_path: Path | None,
    ) -> None:
        """Registra el resultado de la postulación en BD."""

        # Buscar generated_cv si existe
        cv_orm = None
        if cv_path:
            cv_orm = self._cv_repo.get_for_offer(offer.id)

        # Solo registrar application si se envió realmente o dry-run
        if result.status in ("applied", "dry_run"):
            app = Application(
                job_offer_id=offer.id,
                generated_cv_id=cv_orm.id if cv_orm else None,
                status="completed" if result.status == "applied" else "pending",
                applied_at=datetime.now(timezone.utc) if result.status == "applied" else None,
            )
            self._session.add(app)

        # Audit log
        self._session.add(AuditLog(
            entity_type="application",
            entity_id=offer.id,
            action="apply",
            status=result.status,
            detail={
                "portal": offer.portal,
                "title": offer.title[:60],
                "company": offer.company,
                "dry_run": result.status == "dry_run",
                "fields_filled": result.fields_filled,
                "fields_total": result.fields_total,
                "message": result.message[:200],
            },
        ))

        self._session.flush()

    # ── Setup de sesiones ─────────────────────────────────────────────────────
    def setup_portal_session(self, portal: str) -> bool:
        """Ejecuta el setup de sesión manual para un portal."""
        automator = self._get_automator(portal)
        if not automator:
            logger.error(f"Sin automator disponible para [{portal}]")
            return False
        return automator.setup_session()

    def setup_all_sessions(self) -> dict[str, bool]:
        """Ejecuta setup de sesión para todos los portales habilitados."""
        results: dict[str, bool] = {}
        for portal in self._config.enabled_portals:
            if portal in self._registry:
                print(f"\n--- Setup de {portal.upper()} ---")
                results[portal] = self.setup_portal_session(portal)
        return results
