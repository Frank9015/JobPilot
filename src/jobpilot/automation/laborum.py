"""
JobPilot — Laborum Automator
Automatiza la postulación en Laborum Chile usando Playwright.
"""
from __future__ import annotations

from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from jobpilot.automation.base import BaseAutomator
from jobpilot.core.logger import get_logger

logger = get_logger("automation.laborum")


class LaborumAutomator(BaseAutomator):
    """
    Automatizador para Laborum (Plataforma Jobint).
    """

    @property
    def portal_name(self) -> str:
        return "laborum"

    @property
    def _login_url(self) -> str:
        return "https://www.laborum.cl/postulantes/login"

    def _check_logged_in(self, page) -> bool:
        try:
            page.goto("https://www.laborum.cl/postulantes/mi-perfil", wait_until="domcontentloaded", timeout=15000)
            
            if "/login" in page.url:
                return False
                
            if page.locator("text='Datos personales'").count() > 0 or page.locator("text='Mi CV'").count() > 0:
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
            
            if "DataDome" in self._page.title() or "Verificando" in self._page.title():
                return {
                    "status": "needs_human",
                    "reason": "captcha",
                    "message": "Bloqueo anti-bot detectado por Laborum (DataDome).",
                }

            apply_button = self._page.locator("button:has-text('Postularme'), a:has-text('Postularme')").first
            
            if apply_button.count() == 0:
                if self._page.locator("text='Ya te postulaste'").count() > 0 or self._page.locator("text='Postulado'").count() > 0:
                    logger.info(f"[{self.portal_name}] Ya estabas postulado a esta oferta.")
                    return {"status": "applied", "message": "Ya estabas postulado."}
                    
                logger.warning(f"[{self.portal_name}] No se encontró el botón de postular.")
                return {"status": "failed", "message": "Botón de postular no encontrado."}

            if dry_run:
                logger.info(f"[{self.portal_name}] [DRY-RUN] Botón encontrado. Abortando click.")
                return {"status": "dry_run", "message": "Simulación exitosa."}

            apply_button.click()
            self._human_delay(3.0)
            
            renta_input = self._page.locator("input[name='pretensionRenta'], input[placeholder*='renta']")
            if renta_input.count() > 0:
                renta_input.fill("1000000")
                self._human_delay(1.0)
                
            confirm_button = self._page.locator("button:has-text('Enviar postulación'), button:has-text('Confirmar')").first
            if confirm_button.count() > 0:
                confirm_button.click()
                self._human_delay(3.0)
                
            if self._page.locator("text='Postulación enviada'").count() > 0 or self._page.locator("text='Ya te postulaste'").count() > 0:
                return {"status": "applied", "message": "Postulación enviada con éxito."}

            return {
                "status": "needs_human",
                "reason": "unknown_question",
                "message": "Formulario desconocido o paso extra detectado en Laborum.",
            }

        except PlaywrightTimeoutError:
            logger.error(f"[{self.portal_name}] Timeout cargando oferta.")
            return {"status": "failed", "message": "Timeout cargando oferta."}
        except Exception as e:
            logger.error(f"[{self.portal_name}] Error en postulación: {e}")
            return {"status": "failed", "message": str(e)}
