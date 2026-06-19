"""
JobPilot — SENCE (BNE) Automator
Automatiza la postulación en bne.cl.
"""
from __future__ import annotations

from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from jobpilot.automation.base import BaseAutomator
from jobpilot.core.logger import get_logger

logger = get_logger("automation.sence")


class SenceAutomator(BaseAutomator):
    """
    Automatizador para la Bolsa Nacional de Empleo.
    """

    @property
    def portal_name(self) -> str:
        return "sence"

    @property
    def _login_url(self) -> str:
        return "https://www.bne.cl/login"

    def _check_logged_in(self, page) -> bool:
        try:
            page.goto("https://www.bne.cl/mi-perfil", wait_until="domcontentloaded", timeout=15000)
            
            if "login" in page.url:
                return False
                
            if page.locator("text='Cerrar Sesión'").count() > 0 or page.locator("text='Mi Curriculum'").count() > 0:
                return True
                
            return False
        except Exception as e:
            logger.warning(f"[{self.portal_name}] Error verificando login: {e}")
            return False

    def apply_to_job(
        self,
        job_url: str,
        profile_data: Any,
        cv_path: str | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        if not self._browser:
            self._launch_browser()

        logger.info(f"[{self.portal_name}] Iniciando postulación a: {job_url}")
        
        try:
            self._page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
            self._human_delay(2.0)
            
            apply_button = self._page.locator("button:has-text('Postular'), a:has-text('Postular')").first
            
            if apply_button.count() == 0:
                if self._page.locator("text='Ya te has postulado'").count() > 0:
                    return {"status": "applied", "message": "Ya estabas postulado."}
                    
                logger.warning(f"[{self.portal_name}] Botón de postular no encontrado.")
                return {"status": "failed", "message": "Botón no encontrado."}

            if dry_run:
                logger.info(f"[{self.portal_name}] [DRY-RUN] Botón encontrado. Abortando click.")
                return {"status": "dry_run", "message": "Simulación exitosa."}

            apply_button.click()
            self._human_delay(3.0)
            
            # Verificar si pide confirmación
            confirm_button = self._page.locator("button:has-text('Confirmar postulación'), button:has-text('Enviar')").first
            if confirm_button.count() > 0:
                confirm_button.click()
                self._human_delay(2.0)
                
            if self._page.locator("text='Postulación exitosa'").count() > 0 or self._page.locator("text='Ya te has postulado'").count() > 0:
                return {"status": "applied", "message": "Postulación enviada con éxito."}

            return {
                "status": "needs_human",
                "reason": "unknown_question",
                "message": "Formulario desconocido en BNE.",
            }

        except PlaywrightTimeoutError:
            logger.error(f"[{self.portal_name}] Timeout cargando oferta.")
            return {"status": "failed", "message": "Timeout cargando oferta."}
        except Exception as e:
            logger.error(f"[{self.portal_name}] Error en postulación: {e}")
            return {"status": "failed", "message": str(e)}
