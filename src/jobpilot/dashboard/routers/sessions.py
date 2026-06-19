"""
JobPilot Dashboard — Sessions Router
Endpoints para estado de sesiones de portales (semáforo).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from jobpilot.core.config import get_config
from jobpilot.database.engine import get_session
from jobpilot.database.models import SessionStatus

router = APIRouter()


@router.get("")
async def get_sessions() -> list[dict[str, Any]]:
    """Estado de sesiones por portal (semáforo verde/amarillo/rojo)."""
    config = get_config()
    enabled = config.enabled_portals

    with get_session() as s:
        db_sessions = s.scalars(select(SessionStatus)).all()
        session_map = {ss.portal: ss for ss in db_sessions}

        results = []
        for portal in enabled:
            ss = session_map.get(portal)
            if ss:
                results.append(
                    {
                        "portal": portal,
                        "status": ss.status,  # active | suspicious | expired
                        "reason": ss.reason,
                        "last_checked": (
                            ss.last_checked.isoformat() if ss.last_checked else None
                        ),
                        "last_active": (
                            ss.last_active.isoformat() if ss.last_active else None
                        ),
                        "session_file": ss.session_file,
                    }
                )
            else:
                results.append(
                    {
                        "portal": portal,
                        "status": "expired",
                        "reason": "Sin sesion configurada",
                        "last_checked": None,
                        "last_active": None,
                        "session_file": None,
                    }
                )

    return results


@router.post("/{portal}/login")
def trigger_login(portal: str) -> dict[str, Any]:
    """Inicia el proceso de login manual o automático para un portal."""
    from concurrent.futures import ThreadPoolExecutor

    config = get_config()
    if portal not in config.enabled_portals:
        return {"success": False, "message": f"Portal {portal} no está habilitado"}

    def _do_login() -> bool:
        from jobpilot.automation.manager import AutomationManager
        with get_session() as s:
            manager = AutomationManager(s)
            return manager.setup_portal_session(portal)

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            success = executor.submit(_do_login).result()

        if success:
            return {"success": True, "message": f"Login en {portal} exitoso"}
        else:
            return {"success": False, "message": "Login falló o fue cancelado"}
    except Exception as e:
        return {"success": False, "message": f"Error: {e}"}
