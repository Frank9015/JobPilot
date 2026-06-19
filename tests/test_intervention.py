"""
JobPilot — Test E2E: Intervention + Orchestrator (Semana 4)
Verifica el flujo completo sin llamadas externas.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select, func

# Asegurar path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_intervention_request_dataclass():
    """InterventionRequest se instancia correctamente."""
    from jobpilot.intervention.handler import InterventionRequest

    req = InterventionRequest(
        intervention_id=uuid.uuid4(),
        application_id=uuid.uuid4(),
        reason="captcha",
        question="Resuelve el CAPTCHA",
        job_title="Desarrollador Python",
        company="Acme",
        portal="linkedin",
    )

    assert req.reason == "captcha"
    assert req.portal == "linkedin"
    assert "captcha" in repr(req)


def test_console_notifier_notify():
    """ConsoleNotifier.notify() retorna True y no lanza excepciones."""
    from jobpilot.intervention.console import ConsoleNotifier
    from jobpilot.intervention.handler import InterventionRequest

    notifier = ConsoleNotifier()
    assert notifier.channel_name == "console"

    req = InterventionRequest(
        intervention_id=uuid.uuid4(),
        application_id=uuid.uuid4(),
        reason="unknown_question",
        question="¿Cuántos años de experiencia con Django?",
        job_title="Backend Dev",
        company="Globant",
        portal="linkedin",
    )

    result = notifier.notify(req)
    assert result is True


def test_telegram_notifier_unconfigured():
    """TelegramNotifier sin credenciales no lanza errores."""
    with patch("jobpilot.intervention.telegram.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            telegram_bot_token="",
            telegram_chat_id="",
        )

        import jobpilot.intervention.telegram as tg_mod

        notifier = tg_mod.TelegramNotifier()
        assert notifier.channel_name == "telegram"
        assert notifier._configured is False

        # notify should return False silently
        mock_req = MagicMock()
        assert notifier.notify(mock_req) is False

        # wait should return None silently
        assert notifier.wait_for_response(uuid.uuid4(), 1, 1) is None


def test_cycle_result_summary():
    """CycleResult.summary() retorna dict válido."""
    from jobpilot.core.orchestrator import CycleResult

    result = CycleResult()
    result.offers_scraped = 5
    result.offers_scored = 3
    result.cvs_generated = 2
    result.applications_dry_run = 2
    result.finished_at = datetime.now(timezone.utc)
    result.elapsed_seconds = 45.3

    summary = result.summary()

    assert summary["offers_scraped"] == 5
    assert summary["offers_scored"] == 3
    assert summary["cvs_generated"] == 2
    assert summary["applications_dry_run"] == 2
    assert summary["elapsed_seconds"] == 45.3
    assert summary["success"] is True
    assert summary["aborted"] is False
    assert "started_at" in summary
    assert "finished_at" in summary


def test_handler_with_db():
    """
    Test de integración: InterventionHandler registra en BD y resuelve.
    Usa la BD real de PostgreSQL.
    """
    from jobpilot.database.engine import get_session, verify_connection
    from jobpilot.database.models import Application, AuditLog, HumanIntervention, JobOffer

    if not verify_connection():
        pytest.skip("PostgreSQL no disponible")

    with get_session() as session:
        # Buscar una oferta existente para linkear
        offer = session.scalar(select(JobOffer).limit(1))
        if not offer:
            pytest.skip("No hay ofertas en BD para test de integración")

        # Crear application
        app = Application(
            job_offer_id=offer.id,
            status="in_progress",
        )
        session.add(app)
        session.flush()

        # Crear handler sin notifiers (test solo BD)
        from jobpilot.intervention.handler import InterventionHandler

        handler = InterventionHandler(session, notifiers=[])

        # Verificar pending antes
        pending_before = handler.get_pending_interventions()
        pending_count_before = len(pending_before)

        # Request intervention (sin notifiers -> no espera respuesta -> retorna None)
        answer = handler.request_intervention(
            application_id=app.id,
            reason="unknown_question",
            question="¿Cuántos años de experiencia con React?",
            job_title=offer.title,
            company=offer.company or "Test",
            portal=offer.portal,
        )

        # Sin notifiers, no puede recibir respuesta
        assert answer is None

        # Verificar que se creó la intervención en BD
        intervention = session.scalar(
            select(HumanIntervention)
            .where(HumanIntervention.application_id == app.id)
            .order_by(HumanIntervention.notified_at.desc())
            .limit(1)
        )
        assert intervention is not None
        assert intervention.reason == "unknown_question"
        assert intervention.question == "¿Cuántos años de experiencia con React?"
        assert intervention.resolved_at is None  # Aún pendiente (timeout)

        # Verificar audit log
        audit = session.scalar(
            select(AuditLog)
            .where(
                AuditLog.entity_type == "intervention",
                AuditLog.entity_id == intervention.id,
            )
            .limit(1)
        )
        assert audit is not None
        assert audit.action == "intervention"
        assert audit.status == "timeout"
        assert audit.detail["reason"] == "unknown_question"

        # Resolver manualmente
        success = handler.resolve_intervention(
            intervention_id=intervention.id,
            answer="3 años de experiencia con React",
        )
        assert success is True

        # Verificar resolución
        session.refresh(intervention)
        assert intervention.answer == "3 años de experiencia con React"
        assert intervention.resolved_at is not None

        # Verificar que get_pending no incluye la resuelta
        pending_after = handler.get_pending_interventions()
        assert len(pending_after) <= pending_count_before

        print(f"✓ Intervención creada y resuelta: {intervention.id}")
        print(f"✓ Audit log registrado: {audit.id}")
        print(f"✓ Test de integración BD completado")


def test_orchestrator_preconditions():
    """Orchestrator verifica pre-condiciones correctamente."""
    from jobpilot.database.engine import verify_connection

    if not verify_connection():
        pytest.skip("PostgreSQL no disponible")

    from jobpilot.core.orchestrator import Orchestrator

    # Crear orchestrator en modo dry-run
    orch = Orchestrator(dry_run=True, mock=True)

    # Pre-check debería pasar (BD conectada, perfil existe de fases anteriores)
    result = orch._verify_preconditions()
    assert result is True
    print("✓ Pre-condiciones verificadas OK")


if __name__ == "__main__":
    print("=" * 60)
    print("  TESTS E2E — Semana 4: Intervención + Orquestador")
    print("=" * 60)

    print("\n--- Test 1: InterventionRequest ---")
    test_intervention_request_dataclass()
    print("✓ PASS")

    print("\n--- Test 2: ConsoleNotifier ---")
    test_console_notifier_notify()
    print("✓ PASS")

    print("\n--- Test 3: TelegramNotifier (sin config) ---")
    test_telegram_notifier_unconfigured()
    print("✓ PASS")

    print("\n--- Test 4: CycleResult ---")
    test_cycle_result_summary()
    print("✓ PASS")

    print("\n--- Test 5: Handler con BD ---")
    try:
        test_handler_with_db()
        print("✓ PASS")
    except Exception as e:
        print(f"✗ SKIP/FAIL: {e}")

    print("\n--- Test 6: Orchestrator preconditions ---")
    try:
        test_orchestrator_preconditions()
        print("✓ PASS")
    except Exception as e:
        print(f"✗ SKIP/FAIL: {e}")

    print("\n" + "=" * 60)
    print("  TODOS LOS TESTS COMPLETADOS")
    print("=" * 60)
