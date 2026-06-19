"""
JobPilot — Bumeran Automator
Automatiza la postulación en Bumeran Chile usando Playwright.
"""
from __future__ import annotations

import time
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from jobpilot.automation.base import BaseAutomator
from jobpilot.core.logger import get_logger

logger = get_logger("automation.bumeran")


class BumeranAutomator(BaseAutomator):
    """
    Automatizador para Bumeran.
    Maneja el login y el flujo de postulación ("Postularme").
    """

    @property
    def portal_name(self) -> str:
        return "bumeran"

    @property
    def _login_url(self) -> str:
        return "https://www.bumeran.cl/postulantes/login"

    def _check_logged_in(self, page) -> bool:
        """Verifica si la sesión de Bumeran está activa."""
        try:
            page.goto("https://www.bumeran.cl/postulantes/mi-perfil", wait_until="domcontentloaded", timeout=15000)
            
            # Si redirige al login o muestra el formulario de login, no estamos logueados
            if "/login" in page.url:
                return False
                
            # Buscar indicio de que estamos en el perfil
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
        """
        Ejecuta el flujo de postulación en Bumeran.
        Retorna el estado de la aplicación.
        """
        if not self._browser:
            self._launch_browser()

        logger.info(f"[{self.portal_name}] Iniciando postulación a: {job_url}")
        
        try:
            self._page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
            self._human_delay(2.0)
            
            # Bumeran muestra "DataDome" si nos bloquean
            if "DataDome" in self._page.title() or "Verificando" in self._page.title():
                return {
                    "status": "needs_human",
                    "reason": "captcha",
                    "message": "Bloqueo anti-bot detectado por Bumeran (DataDome).",
                }

            # 1. Buscar el botón de postular (suele decir "Postularme" o id="btn-postular")
            apply_button = self._page.locator("button:has-text('Postularme'), a:has-text('Postularme')").first
            
            if apply_button.count() == 0:
                # Quizás ya estamos postulados?
                if self._page.locator("text='Ya te postulaste'").count() > 0 or self._page.locator("text='Postulado'").count() > 0:
                    logger.info(f"[{self.portal_name}] Ya estabas postulado a esta oferta.")
                    return {"status": "applied", "message": "Ya estabas postulado."}
                    
                logger.warning(f"[{self.portal_name}] No se encontró el botón de postular.")
                return {"status": "failed", "message": "Botón de postular no encontrado."}

            if dry_run:
                logger.info(f"[{self.portal_name}] [DRY-RUN] Botón encontrado. Abortando click.")
                return {"status": "dry_run", "message": "Simulación exitosa."}

            # 2. Hacer click en postular
            apply_button.click()
            self._human_delay(3.0)
            
            # 3. Flujo de preguntas o pretensiones de renta
            # Bumeran suele mostrar un modal preguntando pretensiones de renta o preguntas específicas.
            renta_input = self._page.locator("input[name='pretensionRenta'], input[placeholder*='renta']")
            if renta_input.count() > 0:
                # Escribir la renta base o dejarla en base al profile
                # Asumimos 1000000 como default si no hay en profile para este ejemplo
                renta_input.fill("1000000")
                self._human_delay(1.0)
                
            # En Bumeran, tras poner renta y contestar, hay que dar a "Enviar postulación" o "Confirmar"
            confirm_button = self._page.locator("button:has-text('Enviar postulación'), button:has-text('Confirmar')").first
            if confirm_button.count() > 0:
                confirm_button.click()
                self._human_delay(3.0)
                
            # 4. Verificar éxito
            if self._page.locator("text='Postulación enviada'").count() > 0 or self._page.locator("text='Ya te postulaste'").count() > 0:
                return {"status": "applied", "message": "Postulación enviada con éxito."}

            return {
                "status": "needs_human",
                "reason": "unknown_question",
                "message": "Formulario desconocido o paso extra detectado en Bumeran.",
            }

        except PlaywrightTimeoutError:
            logger.error(f"[{self.portal_name}] Timeout cargando oferta.")
            return {"status": "failed", "message": "Timeout cargando oferta."}
        except Exception as e:
            logger.error(f"[{self.portal_name}] Error en postulación: {e}")
            return {"status": "failed", "message": str(e)}
