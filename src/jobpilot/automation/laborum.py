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
            page.goto(
                "https://www.laborum.cl/postulantes/mi-perfil",
                wait_until="domcontentloaded",
                timeout=15000,
            )

            if "/login" in page.url:
                return False

            if (
                page.locator("text='Datos personales'").count() > 0
                or page.locator("text='Mi CV'").count() > 0
            ):
                return True

            return False
        except Exception as e:
            logger.warning(f"[{self.portal_name}] Error verificando login: {e}")
            return False

    def apply_to_job(
        self,
        job_offer: Any,
        profile: Any,
        cv_path: Any | None = None,
        dry_run: bool = True,
    ) -> Any:
        if not self._browser:
            self._launch_browser()

        logger.info(f"[{self.portal_name}] Iniciando postulación a: {job_offer.url}")

        try:
            self._page.goto(job_offer.url, wait_until="domcontentloaded", timeout=30000)
            self._human_delay(2.0)

            if "DataDome" in self._page.title() or "Verificando" in self._page.title():
                from jobpilot.automation.linkedin import ApplyResult

                return ApplyResult(
                    success=False, status="needs_human",
                    message="Bloqueo anti-bot detectado por Laborum (DataDome).",
                )

            apply_button = self._page.locator(
                "button:has-text('Postularme'), a:has-text('Postularme')"
            ).first

            if apply_button.count() == 0:
                if (
                    self._page.locator("text='Ya te postulaste'").count() > 0
                    or self._page.locator("text='Postulado'").count() > 0
                ):
                    logger.info(
                        f"[{self.portal_name}] Ya estabas postulado a esta oferta."
                    )
                    from jobpilot.automation.linkedin import ApplyResult

                    return ApplyResult(
                        success=True, status="already_applied", message="Ya estabas postulado."
                    )

                logger.warning(
                    f"[{self.portal_name}] No se encontró el botón de postular."
                )
                from jobpilot.automation.linkedin import ApplyResult

                return ApplyResult(
                    success=False, status="failed", message="Botón de postular no encontrado."
                )

            if dry_run:
                logger.info(
                    f"[{self.portal_name}] [DRY-RUN] Botón encontrado. Abortando click."
                )
                from jobpilot.automation.linkedin import ApplyResult

                return ApplyResult(success=True, status="dry_run", message="Simulación exitosa.")

            apply_button.click()
            self._human_delay(3.0)

            renta_input = self._page.locator(
                "input[name='pretensionRenta'], input[placeholder*='renta']"
            )
            if renta_input.count() > 0:
                renta_input.fill("1000000")
                self._human_delay(1.0)

            confirm_button = self._page.locator(
                "button:has-text('Enviar postulación'), button:has-text('Confirmar')"
            ).first
            if confirm_button.count() > 0:
                confirm_button.click()
                self._human_delay(3.0)

            if (
                self._page.locator("text='Postulación enviada'").count() > 0
                or self._page.locator("text='Ya te postulaste'").count() > 0
            ):
                from jobpilot.automation.linkedin import ApplyResult

                return ApplyResult(
                    success=True, status="applied",
                    message="Postulación enviada con éxito.",
                    fields_filled=1,
                    fields_total=1,
                )

            from jobpilot.automation.linkedin import ApplyResult

            return ApplyResult(
                success=False, status="needs_human",
                message="Formulario desconocido o paso extra detectado en Laborum.",
            )

        except PlaywrightTimeoutError:
            logger.error(f"[{self.portal_name}] Timeout cargando oferta.")
            from jobpilot.automation.linkedin import ApplyResult

            return ApplyResult(success=False, status="failed", message="Timeout cargando oferta.")
        except Exception as e:
            logger.error(f"[{self.portal_name}] Error en postulación: {e}")
            from jobpilot.automation.linkedin import ApplyResult

            return ApplyResult(success=False, status="failed", message=str(e))
