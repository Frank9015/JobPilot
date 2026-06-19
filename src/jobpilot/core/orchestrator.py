"""
JobPilot — Orchestrator
Motor central que coordina el pipeline completo end-to-end:
  scrape → score → generate CV → apply → intervención humana

Reemplaza la cadena manual de cmd_scrape/score/generate/apply en main.py
con un flujo unificado que gestiona errores, reintentos, intervención humana,
y audit log de forma transversal.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jobpilot.automation.manager import AutomationManager
from jobpilot.core.config import get_config, get_settings
from jobpilot.core.logger import get_logger
from jobpilot.cv.generator import CVGenerator
from jobpilot.cv.renderer import CVRenderer
from jobpilot.cv.repository import CVRepository
from jobpilot.database.engine import get_session
from jobpilot.database.models import (
    Application,
    AuditLog,
    CandidateProfile,
    JobOffer,
    JobScore,
)
from jobpilot.intervention.console import ConsoleNotifier
from jobpilot.intervention.handler import InterventionHandler
from jobpilot.intervention.telegram import TelegramNotifier
from jobpilot.profile.repository import ProfileRepository
from jobpilot.scoring.engine import ScoringEngine
from jobpilot.scraper.manager import ScraperManager

logger = get_logger("core.orchestrator")


# ── Resultado del ciclo ───────────────────────────────────────────────────────
@dataclass
class CycleResult:
    """Resultado completo de un ciclo del orquestador."""

    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    elapsed_seconds: float = 0.0

    # Contadores por fase
    offers_scraped: int = 0
    offers_scored: int = 0
    cvs_generated: int = 0
    applications_sent: int = 0
    applications_dry_run: int = 0
    applications_failed: int = 0
    interventions_requested: int = 0
    interventions_resolved: int = 0
    interventions_timeout: int = 0

    # Errores por fase
    errors: list[dict[str, Any]] = field(default_factory=list)

    # Status general
    success: bool = True
    aborted: bool = False
    abort_reason: str = ""

    def summary(self) -> dict[str, Any]:
        """Resumen compacto para audit_log y dashboard."""
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "offers_scraped": self.offers_scraped,
            "offers_scored": self.offers_scored,
            "cvs_generated": self.cvs_generated,
            "applications_sent": self.applications_sent,
            "applications_dry_run": self.applications_dry_run,
            "applications_failed": self.applications_failed,
            "interventions_requested": self.interventions_requested,
            "interventions_resolved": self.interventions_resolved,
            "interventions_timeout": self.interventions_timeout,
            "errors_count": len(self.errors),
            "success": self.success,
            "aborted": self.aborted,
        }


class Orchestrator:
    """
    Orquestador central de JobPilot.

    Coordina la ejecución del pipeline completo con:
    - Verificación de pre-condiciones (BD, perfil, sesiones).
    - Ejecución secuencial: scrape → score → generate_cv → apply.
    - Intervención humana cuando se detectan problemas.
    - Audit log exhaustivo en cada fase.
    - Reintentos configurables.

    Uso:
        orchestrator = Orchestrator(dry_run=True, mock=False)
        result = orchestrator.run_full_cycle()

        # O fases individuales:
        orchestrator.run_phase_scrape()
        orchestrator.run_phase_score()
    """

    def __init__(
        self,
        dry_run: bool = True,
        mock: bool = False,
        portals: list[str] | None = None,
        enable_console: bool = True,
        enable_telegram: bool = True,
    ) -> None:
        self._dry_run = dry_run
        self._mock = mock
        self._portals = portals
        self._enable_console = enable_console
        self._enable_telegram = enable_telegram

        self._config = get_config()
        self._settings = get_settings()
        self._result = CycleResult()

    # ── Ciclo completo ────────────────────────────────────────────────────────
    def run_full_cycle(self) -> CycleResult:
        """
        Ejecuta el pipeline completo: scrape → score → generate_cv → apply.

        Returns:
            CycleResult con estadísticas completas del ciclo.
        """
        logger.info(
            f"{'=' * 60}\n"
            f"  CICLO JOBPILOT INICIADO\n"
            f"  Modo: {'DRY-RUN' if self._dry_run else 'REAL'} | "
            f"Gemini: {'MOCK' if self._mock or self._settings.gemini_mock_mode else 'REAL'}\n"
            f"{'=' * 60}"
        )

        start = time.time()

        try:
            # Pre-checks
            if not self._verify_preconditions():
                self._result.aborted = True
                self._result.success = False
                return self._result

            # Fase 1: Scrape
            self._run_phase("scrape", self.run_phase_scrape)

            # Fase 2: Score
            self._run_phase("score", self.run_phase_score)

            # Fase 3: Generate CVs
            self._run_phase("generate_cv", self.run_phase_generate_cvs)

            # Fase 4: Apply
            self._run_phase("apply", self.run_phase_apply)

        except KeyboardInterrupt:
            logger.warning("Ciclo interrumpido por el usuario")
            self._result.aborted = True
            self._result.abort_reason = "keyboard_interrupt"
        except Exception as e:
            logger.error(f"Error fatal en ciclo: {e}")
            self._result.success = False
            self._result.errors.append(
                {
                    "phase": "cycle",
                    "error": str(e),
                    "type": type(e).__name__,
                }
            )

        self._result.elapsed_seconds = time.time() - start
        self._result.finished_at = datetime.now(timezone.utc)

        # Audit log del ciclo completo
        self._log_cycle_audit()

        # Log resumen
        r = self._result
        logger.info(
            f"\n{'=' * 60}\n"
            f"  CICLO COMPLETADO en {r.elapsed_seconds:.1f}s\n"
            f"  Scrape: {r.offers_scraped} | Score: {r.offers_scored} | "
            f"CVs: {r.cvs_generated}\n"
            f"  Apply: {r.applications_sent} enviadas, "
            f"{r.applications_dry_run} dry-run, "
            f"{r.applications_failed} fallidas\n"
            f"  Intervenciones: {r.interventions_requested} solicitadas, "
            f"{r.interventions_resolved} resueltas, "
            f"{r.interventions_timeout} timeout\n"
            f"  Errores: {len(r.errors)}\n"
            f"{'=' * 60}"
        )

        # Enviar resumen por Telegram si está habilitado
        if self._enable_telegram:
            try:
                telegram = TelegramNotifier()
                if telegram._configured:
                    status_icon = "✅" if r.success else "❌"
                    mode_text = "DRY-RUN" if self._dry_run else "REAL"
                    msg = (
                        f"{status_icon} *Ciclo JobPilot Completado* [{mode_text}]\n\n"
                        f"⏱️ *Tiempo:* {r.elapsed_seconds:.1f}s\n"
                        f"🔎 *Ofertas scrapeadas:* {r.offers_scraped}\n"
                        f"🎯 *Ofertas evaluadas:* {r.offers_scored}\n"
                        f"📄 *CVs generados:* {r.cvs_generated}\n"
                        f"🚀 *Postulaciones enviadas:* {r.applications_sent}\n"
                        f"⚠️ *Postulaciones fallidas:* {r.applications_failed}\n"
                        f"👤 *Intervenciones:* {r.interventions_resolved}/{r.interventions_requested}\n"
                    )
                    telegram._send_message(msg, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Error enviando resumen a Telegram: {e}")

        return self._result

    # ── Fases individuales ────────────────────────────────────────────────────
    def run_phase_scrape(self) -> None:
        """Fase 1: Scraping de ofertas."""
        logger.info("─── FASE 1: SCRAPING ───")

        manager = ScraperManager()
        available = manager.get_enabled_portals()

        if self._portals:
            available = [p for p in available if p in self._portals]

        if not available:
            logger.info("No hay portales habilitados para scraping")
            return

        stats_list = manager.run_scrape_cycle()
        self._result.offers_scraped = sum(s.new_saved for s in stats_list)

        logger.info(
            f"Scraping completado: {self._result.offers_scraped} ofertas nuevas"
        )

    def run_phase_score(self) -> None:
        """Fase 2: Scoring de ofertas pendientes."""
        logger.info("─── FASE 2: SCORING ───")

        with get_session() as session:
            repo = ProfileRepository(session)
            profile_data = repo.get_as_profile_data()

            if not profile_data:
                logger.warning("No hay perfil cargado — saltando scoring")
                return

            engine = ScoringEngine(session)
            results = engine.score_pending_offers(profile_data)

            self._result.offers_scored = len(results)
            logger.info(f"Scoring completado: {len(results)} ofertas evaluadas")

    def run_phase_generate_cvs(self) -> None:
        """Fase 3: Generación de CVs adaptados."""
        logger.info("─── FASE 3: GENERACIÓN DE CVs ───")

        with get_session() as session:
            repo = ProfileRepository(session)
            profile_data = repo.get_as_profile_data()

            if not profile_data:
                logger.warning("No hay perfil cargado — saltando generación de CVs")
                return

            config = self._config
            from pathlib import Path

            # Ofertas elegibles (scored, score >= umbral)
            offers_with_scores = session.execute(
                select(JobOffer, JobScore)
                .outerjoin(JobScore, JobOffer.id == JobScore.job_offer_id)
                .where(
                    JobOffer.status == "scored",
                    JobScore.total_score >= config.min_score_to_apply,
                )
                .order_by(JobScore.total_score.desc())
            ).all()

            if not offers_with_scores:
                logger.info("No hay ofertas elegibles para generar CV")
                return

            generator = CVGenerator(session)
            renderer = CVRenderer()
            cv_repo = CVRepository(session)

            profile_orm = session.scalar(
                select(CandidateProfile)
                .order_by(CandidateProfile.created_at.desc())
                .limit(1)
            )

            from jobpilot.scoring.models import ScoreResult

            generated = 0
            for offer, score in offers_with_scores:
                existing = cv_repo.get_for_offer(offer.id)
                if existing and Path(existing.file_path).exists():
                    continue

                score_result = (
                    ScoreResult(
                        total_score=float(score.total_score or 0),
                        skill_match=float(score.skill_match or 0),
                        experience_match=float(score.experience_match or 0),
                        education_match=0.0,
                        location_match=0.0,
                        salary_match=0.0,
                        reasoning="",
                        recommendation="",
                        score_method="gemini",
                        tokens_used=0,
                        cache_hit=False,
                    )
                    if score
                    else None
                )

                try:
                    adapted = generator.adapt_cv(profile_data, offer, score_result)

                    safe_company = (offer.company or "unknown").replace(" ", "_")[:20]
                    filename = f"cv_{safe_company}_{offer.id.hex[:8]}.pdf"
                    filename = "".join(
                        c for c in filename if c.isalnum() or c in "_.-."
                    ).lower()
                    output_path = config.cv_generated_dir / filename

                    renderer.render(profile_data, adapted, output_path)

                    if profile_orm:
                        cv_repo.save(offer, profile_orm, adapted, output_path)

                    offer.status = "cv_ready"
                    session.flush()
                    generated += 1

                except Exception as e:
                    logger.error(f"Error generando CV para '{offer.title[:40]}': {e}")
                    self._result.errors.append(
                        {
                            "phase": "generate_cv",
                            "offer": offer.title[:60],
                            "error": str(e),
                        }
                    )

            self._result.cvs_generated = generated
            logger.info(f"CVs generados: {generated}")

    def run_phase_apply(self) -> None:
        """Fase 4: Postulación automática con intervención humana."""
        logger.info(
            f"─── FASE 4: POSTULACIÓN "
            f"{'[DRY-RUN]' if self._dry_run else '[REAL]'} ───"
        )

        with get_session() as session:
            repo = ProfileRepository(session)
            profile_data = repo.get_as_profile_data()

            if not profile_data:
                logger.warning("No hay perfil cargado — saltando postulación")
                return

            # Construir notifiers para intervención
            notifiers = self._build_notifiers()
            intervention_handler = InterventionHandler(session, notifiers=notifiers)

            manager = AutomationManager(session)

            # Ejecutar ciclo de apply
            results = manager.run_apply_cycle(
                profile=profile_data,
                dry_run=self._dry_run,
                portal=(
                    self._portals[0]
                    if self._portals and len(self._portals) == 1
                    else None
                ),
            )

            # Procesar resultados
            for r in results:
                status = r.get("status", "")
                if status == "applied":
                    self._result.applications_sent += 1
                elif status == "dry_run":
                    self._result.applications_dry_run += 1
                elif status == "failed":
                    self._result.applications_failed += 1
                elif status == "needs_human":
                    self._result.interventions_requested += 1

                    # Disparar intervención humana
                    answer = intervention_handler.request_intervention(
                        application_id=_find_application_id(session, r.get("offer_id")),
                        reason="unknown_question",
                        question=_build_question_from_result(r),
                        job_title=r.get("title", ""),
                        company=r.get("company", ""),
                        portal=r.get("portal", ""),
                    )

                    if answer:
                        self._result.interventions_resolved += 1
                    else:
                        self._result.interventions_timeout += 1

            logger.info(
                f"Postulación completada: "
                f"{self._result.applications_sent} enviadas, "
                f"{self._result.applications_dry_run} dry-run, "
                f"{self._result.applications_failed} fallidas"
            )

    # ── Pre-condiciones ───────────────────────────────────────────────────────
    def _verify_preconditions(self) -> bool:
        """Verifica que el sistema está listo para ejecutar."""
        from jobpilot.database.engine import verify_connection

        # 1. Base de datos
        if not verify_connection():
            self._result.abort_reason = "database_unavailable"
            logger.error("Pre-check fallido: PostgreSQL no disponible")
            return False

        # 2. Perfil cargado
        with get_session() as session:
            profile_count = (
                session.scalar(select(func.count()).select_from(CandidateProfile)) or 0
            )

            if profile_count == 0:
                self._result.abort_reason = "no_profile"
                logger.error(
                    "Pre-check fallido: No hay perfil cargado. Ejecuta --setup primero."
                )
                return False

        logger.info("Pre-checks: OK (DB conectada, perfil cargado)")
        return True

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _run_phase(self, phase_name: str, phase_fn) -> None:
        """Ejecuta una fase con manejo de errores y audit log."""
        phase_start = time.time()

        try:
            phase_fn()

            # Audit log de fase exitosa
            with get_session() as session:
                session.add(
                    AuditLog(
                        entity_type="orchestrator",
                        action=phase_name,
                        status="success",
                        detail={
                            "elapsed_seconds": round(time.time() - phase_start, 1),
                            "dry_run": self._dry_run,
                        },
                    )
                )

        except Exception as e:
            elapsed = time.time() - phase_start
            logger.error(f"Error en fase [{phase_name}]: {e}")
            self._result.errors.append(
                {
                    "phase": phase_name,
                    "error": str(e),
                    "type": type(e).__name__,
                    "elapsed_seconds": round(elapsed, 1),
                }
            )

            # Audit log de error
            with get_session() as session:
                session.add(
                    AuditLog(
                        entity_type="orchestrator",
                        action=phase_name,
                        status="error",
                        error=str(e)[:500],
                        detail={"elapsed_seconds": round(elapsed, 1)},
                    )
                )

    def _build_notifiers(self) -> list[Any]:
        """Construye la lista de notifiers habilitados."""
        from typing import Any
        notifiers: list[Any] = []

        if self._enable_console:
            notifiers.append(ConsoleNotifier())

        if self._enable_telegram:
            try:
                telegram = TelegramNotifier()
                if telegram._configured:
                    notifiers.append(telegram)
            except Exception as e:
                logger.debug(f"Telegram notifier no disponible: {e}")

        return notifiers

    def _log_cycle_audit(self) -> None:
        """Registra el resultado del ciclo completo en audit_log."""
        try:
            with get_session() as session:
                session.add(
                    AuditLog(
                        entity_type="orchestrator",
                        action="full_cycle",
                        status="success" if self._result.success else "error",
                        detail=self._result.summary(),
                        error=(
                            self._result.abort_reason if self._result.aborted else None
                        ),
                    )
                )
        except Exception as e:
            logger.error(f"Error registrando audit del ciclo: {e}")


# ── Utilidades del módulo ─────────────────────────────────────────────────────
def _find_application_id(session: Session, offer_id_str: str | None) -> Any:
    """Busca el application_id más reciente para una oferta."""
    if not offer_id_str:
        # Crear una application temporal para linkear la intervención
        import uuid as uuid_mod

        app = Application(
            job_offer_id=(
                uuid_mod.UUID(offer_id_str) if offer_id_str else uuid_mod.uuid4()
            ),
            status="needs_human",
        )
        session.add(app)
        session.flush()
        return app.id

    import uuid as uuid_mod

    try:
        offer_uuid = uuid_mod.UUID(offer_id_str)
    except (ValueError, TypeError):
        app = Application(
            job_offer_id=uuid_mod.uuid4(),
            status="needs_human",
        )
        session.add(app)
        session.flush()
        return app.id

    # Buscar application existente
    existing = session.scalar(
        select(Application)
        .where(Application.job_offer_id == offer_uuid)
        .order_by(Application.applied_at.desc().nulls_last())
        .limit(1)
    )

    if existing:
        return existing.id

    # Crear nueva
    app = Application(
        job_offer_id=offer_uuid,
        status="needs_human",
    )
    session.add(app)
    session.flush()
    return app.id


def _build_question_from_result(result: dict[str, Any]) -> str:
    """Construye la pregunta de intervención a partir del resultado de apply."""
    message = result.get("message", "")

    # Si hay unknown_questions, concatenarlas
    unknown = result.get("unknown_questions") or []
    if unknown:
        return " | ".join(unknown)

    return message or "Se requiere intervención humana para continuar."
