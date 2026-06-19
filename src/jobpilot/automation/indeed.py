"""
JobPilot — Indeed Automator
Automatiza la postulación en Indeed Chile.
"""

from __future__ import annotations

from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from jobpilot.automation.base import BaseAutomator
from jobpilot.core.logger import get_logger

logger = get_logger("automation.indeed")


class IndeedAutomator(BaseAutomator):
    """
    Automatizador para Indeed.
    Maneja login y flujos de 'Easy Apply' (Postulación vía Indeed).
    """

    @property
    def portal_name(self) -> str:
        return "indeed"

    @property
    def _login_url(self) -> str:
        return "https://secure.indeed.com/auth"

    def _check_logged_in(self, page) -> bool:
        try:
            page.goto(
                "https://cl.indeed.com/", wait_until="domcontentloaded", timeout=15000
            )

            # Buscar el botón de perfil o cuenta (usualmente un botón circular en el header)
            # O la URL de profile
            if (
                page.locator("a[href*='/profile']").count() > 0
                or page.locator("[aria-label='cuenta']").count() > 0
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

            if "Cloudflare" in self._page.title() or "hCaptcha" in self._page.content():
                from jobpilot.automation.linkedin import ApplyResult

                return ApplyResult(
                    success=False, status="needs_human",
                    message="Bloqueo anti-bot detectado por Indeed (Cloudflare/hCaptcha).",
                )

            # En Indeed, hay "Postularse vía Indeed" (Easy Apply) o "Postularse en el sitio de la empresa"
            # Intentaremos buscar el Easy Apply.
            apply_button = self._page.locator(
                "button:has-text('Postularse ahora'), button:has-text('Postular vía Indeed')"
            ).first

            if apply_button.count() == 0:
                if (
                    self._page.locator(
                        "button:has-text('Postularse en el sitio')"
                    ).count()
                    > 0
                ):
                    logger.warning(
                        f"[{self.portal_name}] Requiere postulación externa. No soportado aún."
                    )
                if (
                    self._page.locator("text='Ya te postulaste'").count() > 0
                    or self._page.locator("text='Postulación enviada'").count() > 0
                ):
                    logger.info(
                        f"[{self.portal_name}] Ya estabas postulado a esta oferta."
                    )
                    from jobpilot.automation.linkedin import ApplyResult

                    return ApplyResult(
                        success=True, status="already_applied", message="Ya estabas postulado."
                    )

                logger.warning(
                    f"[{self.portal_name}] No se encontró el botón de 'Postularse ahora'."
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

            # El flujo de Indeed Easy Apply tiene múltiples pasos (Continuar, Revisar, Postular)
            max_steps = 10
            for _ in range(max_steps):
                # Si aparece un mensaje de éxito
                if (
                    self._page.locator("text='Se envió tu postulación'").count() > 0
                    or self._page.locator("text='postulación enviada'").count() > 0
                ):
                    from jobpilot.automation.linkedin import ApplyResult

                    return ApplyResult(
                        success=True, status="applied",
                        message="Postulación enviada con éxito.",
                        fields_filled=1,
                        fields_total=1,
                    )

                # Si hay botón "Continuar"
                continue_btn = self._page.locator("button:has-text('Continuar')").first
                if continue_btn.count() > 0 and continue_btn.is_visible():
                    continue_btn.click()
                    self._human_delay(2.0)
                    continue

                # Si hay botón "Postularse" en el último paso de revisión
                submit_btn = self._page.locator("button:has-text('Postularse')").first
                if submit_btn.count() > 0 and submit_btn.is_visible():
                    submit_btn.click()
                    self._human_delay(3.0)
                    continue

                # Si pide CV, seleccionar el ya cargado
                # (Suele saltarse automáticamente si apretamos continuar)

                # Si no encontramos qué clickear, salir del loop para intervención manual
                break

            # Si salimos del loop sin éxito, revisar si de verdad se mandó
            if (
                self._page.locator("text='Tu postulación ha sido enviada'").count() > 0
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
                message="Formulario extenso o paso extra detectado en Indeed.",
            )

        except PlaywrightTimeoutError:
            logger.error(f"[{self.portal_name}] Timeout cargando oferta.")
            from jobpilot.automation.linkedin import ApplyResult

            return ApplyResult(success=False, status="failed", message="Timeout cargando oferta.")
        except Exception as e:
            logger.error(f"[{self.portal_name}] Error en postulación: {e}")
            from jobpilot.automation.linkedin import ApplyResult

            return ApplyResult(success=False, status="failed", message=str(e))
