"""
JobPilot — Intervention Handler
Orquesta la solicitud de intervención humana cuando la automatización
encuentra situaciones que no puede resolver: CAPTCHAs, MFA, preguntas
desconocidas, errores inesperados.

Flujo:
1. El automator detecta una situación que requiere humano.
2. Handler registra un HumanIntervention en BD.
3. Notifica al usuario por el canal configurado (console/telegram).
4. Espera la respuesta con polling + timeout.
5. Retorna la respuesta al automator o None si hubo timeout.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy.orm import Session

from jobpilot.core.config import get_config
from jobpilot.core.logger import get_logger
from jobpilot.database.models import Application, AuditLog, HumanIntervention

logger = get_logger("intervention.handler")


# ── Protocolo de notificador ──────────────────────────────────────────────────
class InterventionNotifier(Protocol):
    """Interfaz que deben implementar console.py y telegram.py."""

    @property
    def channel_name(self) -> str:
        """Nombre del canal: 'console' o 'telegram'."""
        ...

    def notify(self, intervention: InterventionRequest) -> bool:
        """Envía notificación al usuario. Retorna True si fue exitoso."""
        ...

    def wait_for_response(
        self,
        intervention_id: uuid.UUID,
        timeout_seconds: int,
        poll_interval: int,
    ) -> str | None:
        """Espera la respuesta del usuario. Retorna la respuesta o None si timeout."""
        ...


# ── Modelo de solicitud ──────────────────────────────────────────────────────
class InterventionRequest:
    """Datos de una solicitud de intervención humana."""

    def __init__(
        self,
        intervention_id: uuid.UUID,
        application_id: uuid.UUID,
        reason: str,
        question: str | None = None,
        job_title: str = "",
        company: str = "",
        portal: str = "",
        context: dict[str, Any] | None = None,
    ) -> None:
        self.intervention_id = intervention_id
        self.application_id = application_id
        self.reason = reason
        self.question = question
        self.job_title = job_title
        self.company = company
        self.portal = portal
        self.context = context or {}

    def __repr__(self) -> str:
        return (
            f"InterventionRequest(reason={self.reason!r}, "
            f"question={self.question!r}, job={self.job_title!r})"
        )


# ── Handler principal ─────────────────────────────────────────────────────────
class InterventionHandler:
    """
    Gestiona el ciclo completo de intervención humana.

    Uso:
        handler = InterventionHandler(session, notifiers=[ConsoleNotifier()])
        answer = handler.request_intervention(
            application_id=app.id,
            reason="unknown_question",
            question="¿Cuántos años de experiencia tienes con Kubernetes?",
            job_title="DevOps Engineer",
            company="Globant",
            portal="linkedin",
        )
    """

    def __init__(
        self,
        session: Session,
        notifiers: list[InterventionNotifier] | None = None,
    ) -> None:
        self._session = session
        self._config = get_config()
        self._notifiers = notifiers or []

    def request_intervention(
        self,
        application_id: uuid.UUID,
        reason: str,
        question: str | None = None,
        job_title: str = "",
        company: str = "",
        portal: str = "",
        context: dict[str, Any] | None = None,
    ) -> str | None:
        """
        Solicita intervención humana.

        Args:
            application_id: ID de la postulación en curso.
            reason: Tipo de intervención (captcha|mfa|unknown_question|error).
            question: La pregunta que el humano debe responder.
            job_title: Título de la oferta (para contexto en la notificación).
            company: Empresa (para contexto).
            portal: Portal (para contexto).
            context: Datos adicionales (screenshot path, etc.).

        Returns:
            La respuesta del usuario, o None si hubo timeout.
        """
        # 1. Registrar en BD
        intervention = HumanIntervention(
            application_id=application_id,
            reason=reason,
            question=question,
            notified_at=datetime.now(timezone.utc),
        )
        self._session.add(intervention)
        self._session.flush()

        # Actualizar status de la application
        app = self._session.get(Application, application_id)
        if app:
            app.status = "needs_human"
            self._session.flush()

        logger.warning(
            f"Intervencion solicitada: reason={reason}, "
            f"job='{job_title[:40]}' ({portal}), "
            f"question='{(question or '')[:50]}'"
        )

        # 2. Construir request
        request = InterventionRequest(
            intervention_id=intervention.id,
            application_id=application_id,
            reason=reason,
            question=question,
            job_title=job_title,
            company=company,
            portal=portal,
            context=context,
        )

        # 3. Notificar por todos los canales
        notified_channels: list[str] = []
        for notifier in self._notifiers:
            try:
                success = notifier.notify(request)
                if success:
                    notified_channels.append(notifier.channel_name)
            except Exception as e:
                logger.error(f"Error notificando por [{notifier.channel_name}]: {e}")

        if notified_channels:
            intervention.notification_channel = ",".join(notified_channels)
            self._session.flush()
        else:
            logger.warning("No se pudo notificar por ningun canal")

        # 4. Esperar respuesta (usa el primer notifier que tenga wait)
        answer = None
        timeout = self._config.intervention_timeout
        poll = self._config.intervention_poll_interval

        for notifier in self._notifiers:
            try:
                answer = notifier.wait_for_response(
                    intervention_id=intervention.id,
                    timeout_seconds=timeout,
                    poll_interval=poll,
                )
                if answer is not None:
                    break
            except Exception as e:
                logger.error(f"Error esperando respuesta de [{notifier.channel_name}]: {e}")

        # 5. Registrar resultado
        if answer is not None:
            intervention.answer = answer
            intervention.resolved_at = datetime.now(timezone.utc)
            logger.info(f"Intervencion resuelta: answer='{answer[:50]}'")

            # Restaurar status de application
            if app:
                app.status = "in_progress"
                self._session.flush()
        else:
            logger.warning(
                f"Timeout de intervencion ({timeout}s) para '{job_title[:40]}'"
            )

        # 6. Audit log
        self._session.add(AuditLog(
            entity_type="intervention",
            entity_id=intervention.id,
            action="intervention",
            status="resolved" if answer else "timeout",
            detail={
                "reason": reason,
                "question": question,
                "answer": answer[:200] if answer else None,
                "channels": notified_channels,
                "job_title": job_title[:60],
                "company": company,
                "portal": portal,
                "timeout_seconds": timeout,
            },
        ))
        self._session.flush()

        return answer

    def get_pending_interventions(self) -> list[HumanIntervention]:
        """Retorna intervenciones pendientes de resolución."""
        from sqlalchemy import select

        return list(self._session.scalars(
            select(HumanIntervention)
            .where(HumanIntervention.resolved_at.is_(None))
            .order_by(HumanIntervention.notified_at.asc())
        ).all())

    def resolve_intervention(
        self,
        intervention_id: uuid.UUID,
        answer: str,
    ) -> bool:
        """Resuelve una intervención pendiente manualmente (usado por dashboard/API)."""
        intervention = self._session.get(HumanIntervention, intervention_id)
        if not intervention:
            logger.error(f"Intervencion {intervention_id} no encontrada")
            return False

        if intervention.resolved_at is not None:
            logger.warning(f"Intervencion {intervention_id} ya resuelta")
            return False

        intervention.answer = answer
        intervention.resolved_at = datetime.now(timezone.utc)
        self._session.flush()

        logger.info(f"Intervencion {intervention_id} resuelta manualmente")
        return True
