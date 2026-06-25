"""
JobPilot — LinkedIn Easy Apply Automator
Automatiza postulaciones en LinkedIn usando Playwright.
Soporta dry-run para simular sin enviar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from jobpilot.automation.base import BaseAutomator
from jobpilot.automation.form_filler import (
    answer_standard_question,
    detect_fields,
    fill_field,
)
from jobpilot.automation.question_answerer import (
    AnswerResult,
    FormQuestion,
    QuestionAnswerer,
)
from jobpilot.core.logger import get_logger
from jobpilot.database.models import JobOffer
from jobpilot.profile.models import ProfileData

logger = get_logger("automation.linkedin")


@dataclass
class ApplyResult:
    """Resultado de un intento de postulación."""

    success: bool
    status: str  # applied | dry_run | failed | needs_human | already_applied | no_easy_apply
    message: str = ""
    fields_filled: int = 0
    fields_total: int = 0
    unknown_questions: list[str] | None = None
    questions_answered: list[dict] | None = None
    gemini_warnings: list[str] | None = None


class LinkedInAutomator(BaseAutomator):
    """
    Automatizador de LinkedIn Easy Apply.

    Flujo:
    1. Navegar a la oferta.
    2. Detectar botón Easy Apply.
    3. Abrir modal y llenar campos.
    4. Manejar pasos múltiples del formulario.
    5. Subir CV adaptado.
    6. Enviar (o simular si dry_run).
    """

    @property
    def portal_name(self) -> str:
        return "linkedin"

    @property
    def _login_url(self) -> str:
        return "https://www.linkedin.com/login"

    # ── Verificación de Login ─────────────────────────────────────────────────
    def _check_logged_in(self, page) -> bool:
        """Verifica si hay sesión activa en LinkedIn."""
        try:
            page.goto(
                "https://www.linkedin.com/feed/",
                wait_until="domcontentloaded",
                timeout=15000,
            )
            self._human_delay()

            # Si estamos en el feed, estamos logueados
            if "/feed" in page.url:
                # Verificar presencia de nav global
                nav = (
                    page.locator('[data-test-id="nav-settings"]')
                    .or_(page.locator(".global-nav"))
                    .or_(page.locator("#global-nav"))
                )
                if nav.count() > 0:
                    return True

                # Fallback: si URL es /feed y no hay redirect a login
                return "login" not in page.url

            return False
        except Exception as e:
            logger.warning(f"Error verificando login LinkedIn: {e}")
            return False

    # ── Apply Flow ────────────────────────────────────────────────────────────
    def apply_to_job(
        self,
        job_offer: JobOffer,
        profile: ProfileData,
        cv_path: Path | str | None = None,
        dry_run: bool = True,
        db_session: Session | None = None,
    ) -> ApplyResult:
        """
        Ejecuta el flujo completo de Easy Apply en LinkedIn.

        Args:
            job_offer: La oferta laboral a postular.
            profile: Datos del candidato.
            cv_path: Ruta al PDF del CV adaptado.
            dry_run: Si True, simula todo sin enviar.
            db_session: Sesión de BD para el QuestionAnswerer.

        Returns:
            ApplyResult con el resultado de la operación.
        """
        if not self._page:
            self._launch_browser()

        url = job_offer.url
        logger.info(
            f"{'[DRY-RUN] ' if dry_run else ''}Postulando a: {job_offer.title[:50]} en {url}"
        )

        try:
            # 1. Navegar a la oferta
            self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
            self._human_delay(factor=1.5)

            # 2. Verificar si ya postulamos
            if self._check_already_applied():
                return ApplyResult(
                    success=True, status="already_applied",
                    message="Ya postulaste a esta oferta anteriormente.",
                )

            # 3. Encontrar y clickear botón Easy Apply
            easy_apply_btn = self._find_easy_apply_button()
            if not easy_apply_btn:
                return ApplyResult(
                    success=False, status="no_easy_apply",
                    message="No se encontro boton Easy Apply. Puede requerir postulacion externa.",
                )

            easy_apply_btn.click()
            self._human_delay(factor=2.0)

            # 4. Procesar formulario (puede tener múltiples pasos)
            result = self._process_application_form(
                profile, cv_path, dry_run, job_offer, db_session
            )

            # 5. Imprimir resumen Rich en consola
            self._print_apply_summary(job_offer, result, dry_run)

            return result

        except Exception as e:
            logger.error(f"Error en Easy Apply: {e}")
            return ApplyResult(
                success=False, status="failed",
                message=str(e),
            )

    # ── Detección de botón Easy Apply ─────────────────────────────────────────
    def _find_easy_apply_button(self):
        """Busca el botón de Easy Apply en la página."""
        selectors = [
            "button.jobs-apply-button",
            'button[aria-label*="Easy Apply"]',
            'button[aria-label*="Solicitud sencilla"]',
            'button:has-text("Easy Apply")',
            'button:has-text("Solicitud sencilla")',
            'button:has-text("Solicitar")',
            ".jobs-apply-button--top-card",
        ]

        for selector in selectors:
            try:
                btn = self._page.locator(selector).first
                if btn.is_visible(timeout=2000):
                    logger.debug(f"Boton Easy Apply encontrado: {selector}")
                    return btn
            except Exception:
                continue

        logger.warning("No se encontro boton Easy Apply")
        return None

    def _check_already_applied(self) -> bool:
        """Verifica si ya se postuló a esta oferta."""
        indicators = [
            'span:has-text("Applied")',
            'span:has-text("Postulado")',
            'span:has-text("Ya postulaste")',
            ".artdeco-inline-feedback--success",
        ]
        for selector in indicators:
            try:
                el = self._page.locator(selector)
                if el.count() > 0 and el.first.is_visible(timeout=1000):
                    return True
            except Exception:
                continue
        return False

    # ── Procesamiento del formulario ──────────────────────────────────────────
    def _process_application_form(
        self,
        profile: ProfileData,
        cv_path: Path | str | None,
        dry_run: bool,
        job_offer: JobOffer | None = None,
        db_session: Session | None = None,
    ) -> ApplyResult:
        """
        Procesa el formulario de Easy Apply (puede ser multi-step).
        Usa QuestionAnswerer de Gemini para preguntas desconocidas.
        Retorna el resultado de la postulación.
        """
        max_steps = 8  # LinkedIn raramente tiene más de 5 pasos
        total_filled = 0
        total_fields = 0
        unknown_questions: list[str] = []
        pending_gemini: list[FormQuestion] = []
        all_answered: list[dict] = []

        for step in range(max_steps):
            self._human_delay()

            # Detectar modal abierto
            modal = (
                self._page.locator(".jobs-easy-apply-modal")
                .or_(self._page.locator('[data-test-modal-id="easy-apply-modal"]'))
                .or_(self._page.locator(".artdeco-modal"))
            )

            if modal.count() == 0:
                logger.debug("No hay modal de Easy Apply abierto")
                break

            # Detectar campos del paso actual
            fields = detect_fields(self._page)
            total_fields += len(fields)

            # Llenar campos
            for field_item in fields:
                if not field_item.label:
                    continue

                # CV upload
                if field_item.field_type == "file" and cv_path:
                    if fill_field(self._page, field_item, str(cv_path)):
                        total_filled += 1
                        logger.debug(f"  CV subido: {cv_path}")
                    continue

                # Respuesta estática (form_filler)
                answer = answer_standard_question(field_item.label, profile)
                if answer:
                    if fill_field(self._page, field_item, answer):
                        total_filled += 1
                        logger.debug(f"  Campo '{field_item.label}' -> '{answer[:30]}'")
                        all_answered.append({
                            "question": field_item.label,
                            "answer": answer,
                            "source": "profile_mapping",
                        })
                else:
                    # Pregunta desconocida → acumular para Gemini
                    unknown_questions.append(field_item.label)
                    pending_gemini.append(FormQuestion(
                        label=field_item.label,
                        html_type=field_item.field_type,
                        options=field_item.options,
                        required=field_item.required,
                    ))

            # Detectar botón de siguiente paso o enviar
            action = self._detect_next_action()

            if action == "submit":
                # Antes de enviar: resolver preguntas pendientes con Gemini
                gemini_result = self._resolve_with_gemini(
                    pending_gemini, profile, job_offer, db_session
                )
                if gemini_result:
                    for q in gemini_result.questions:
                        if q.answer:
                            # Buscar el campo correspondiente y llenarlo
                            filled = self._fill_gemini_answer(q)
                            if filled:
                                total_filled += 1
                            all_answered.append({
                                "question": q.label,
                                "answer": q.answer,
                                "source": q.answer_source,
                                "confidence": q.confidence,
                                "reasoning": q.reasoning,
                                "type": q.question_type.value if hasattr(q.question_type, 'value') else str(q.question_type),
                            })

                warnings = gemini_result.warnings if gemini_result else []

                if dry_run:
                    logger.info(
                        f"[DRY-RUN] Formulario listo. "
                        f"{total_filled}/{total_fields} campos llenos. "
                        f"NO se envia."
                    )
                    self._dismiss_modal()
                    return ApplyResult(
                        success=True, status="dry_run",
                        message=f"Dry-run exitoso: {total_filled}/{total_fields} campos llenos.",
                        fields_filled=total_filled,
                        fields_total=total_fields,
                        unknown_questions=(
                            unknown_questions if unknown_questions else None
                        ),
                        questions_answered=all_answered if all_answered else None,
                        gemini_warnings=warnings if warnings else None,
                    )
                else:
                    # ENVIAR REAL
                    return self._submit_application(
                        total_filled, total_fields, unknown_questions,
                        all_answered, warnings,
                    )

            elif action == "next":
                self._click_next()
                self._human_delay(factor=1.5)
                continue

            elif action == "review":
                # Resolver preguntas pendientes antes de review
                gemini_result = self._resolve_with_gemini(
                    pending_gemini, profile, job_offer, db_session
                )
                if gemini_result:
                    for q in gemini_result.questions:
                        if q.answer:
                            self._fill_gemini_answer(q)
                            total_filled += 1
                            all_answered.append({
                                "question": q.label,
                                "answer": q.answer,
                                "source": q.answer_source,
                                "confidence": q.confidence,
                                "reasoning": q.reasoning,
                                "type": q.question_type.value if hasattr(q.question_type, 'value') else str(q.question_type),
                            })

                warnings = gemini_result.warnings if gemini_result else []

                if dry_run:
                    logger.info(f"[DRY-RUN] En pantalla de revision. NO se envia.")
                    self._dismiss_modal()
                    return ApplyResult(
                        success=True, status="dry_run",
                        message=f"Dry-run completado en revision: {total_filled} campos.",
                        fields_filled=total_filled,
                        fields_total=total_fields,
                        questions_answered=all_answered if all_answered else None,
                        gemini_warnings=warnings if warnings else None,
                    )
                self._click_submit()
                self._human_delay(factor=2.0)
                break

            else:
                logger.warning(f"Accion no reconocida en paso {step + 1}")
                break

        # Verificar resultado
        if not dry_run:
            success = self._check_application_success()
            return ApplyResult(
                success=success,
                status="applied" if success else "failed",
                message=(
                    "Postulacion enviada exitosamente"
                    if success
                    else "No se pudo confirmar el envio"
                ),
                fields_filled=total_filled,
                fields_total=total_fields,
                questions_answered=all_answered if all_answered else None,
            )

        return ApplyResult(
            success=False, status="failed",
            message="Formulario no pudo completarse.",
            fields_filled=total_filled,
            fields_total=total_fields,
            unknown_questions=unknown_questions if unknown_questions else None,
        )

    # ── Resolución con Gemini ──────────────────────────────────────────────────
    def _resolve_with_gemini(
        self,
        pending: list[FormQuestion],
        profile: ProfileData,
        job_offer: JobOffer | None,
        db_session: Session | None,
    ) -> AnswerResult | None:
        """Envía preguntas pendientes a QuestionAnswerer."""
        if not pending or not job_offer:
            return None

        if not db_session:
            logger.warning("Sin sesión BD — no se pueden resolver preguntas con Gemini")
            return None

        try:
            answerer = QuestionAnswerer(db_session)
            result = answerer.answer_all(pending, profile, job_offer)
            pending.clear()  # Ya procesadas
            return result
        except Exception as e:
            logger.error(f"Error en QuestionAnswerer: {e}")
            return None

    def _fill_gemini_answer(self, q: FormQuestion) -> bool:
        """Llena un campo del formulario con la respuesta de Gemini."""
        from jobpilot.automation.form_filler import FormField, fill_field

        # Intentar encontrar el campo por label
        try:
            # Buscar por aria-label, placeholder, o label text
            selectors = [
                f'input[aria-label*="{q.label[:30]}"]',
                f'textarea[aria-label*="{q.label[:30]}"]',
                f'select[aria-label*="{q.label[:30]}"]',
            ]
            for sel in selectors:
                element = self._page.locator(sel)
                if element.count() > 0 and element.first.is_visible(timeout=1000):
                    field_obj = FormField(
                        label=q.label,
                        field_type=q.html_type,
                        selector=sel,
                        options=q.options,
                    )
                    return fill_field(self._page, field_obj, q.answer)
        except Exception as e:
            logger.warning(f"No se pudo llenar campo Gemini '{q.label[:30]}': {e}")

        return False

    # ── Rich Console Output ───────────────────────────────────────────────────
    def _print_apply_summary(
        self,
        job_offer: JobOffer,
        result: ApplyResult,
        dry_run: bool,
    ) -> None:
        """Imprime un resumen visual del intento de postulación."""
        width = 55
        border = "─" * width

        status_icon = {
            "applied": "✅",
            "dry_run": "🧪",
            "failed": "❌",
            "already_applied": "🔄",
            "no_easy_apply": "⛔",
            "needs_human": "👤",
        }.get(result.status, "❓")

        lines = [
            f"╭─── LinkedIn Easy Apply {border[24:]}╮",
            f"│ Vacante: {job_offer.title[:width-11]:<{width-11}} │",
            f"│ Empresa: {(job_offer.company or '?')[:width-11]:<{width-11}} │",
            f"│ Campos: {result.fields_filled}/{result.fields_total} llenados{' ' * (width - 25)}│",
        ]

        if result.questions_answered:
            lines.append(f"│{'':─<{width+1}}│")
            lines.append(f"│ Preguntas: {len(result.questions_answered)} respondidas{' ' * (width - 30)}│")
            for qa in result.questions_answered[:6]:  # Max 6 preguntas visibles
                source_icon = "✅" if qa.get('source') == 'gemini' else "📋"
                conf = qa.get('confidence', '')
                conf_tag = f" ({conf})" if conf else ""
                q_text = qa['question'][:25]
                a_text = qa['answer'][:15]
                line = f"│  {source_icon} {q_text} → {a_text}{conf_tag}"
                lines.append(f"{line:<{width+2}}│")

        if result.gemini_warnings:
            lines.append(f"│{'':─<{width+1}}│")
            for w in result.gemini_warnings[:3]:
                w_text = w[:width - 5]
                lines.append(f"│  ⚠️ {w_text:<{width-4}}│")

        mode = "DRY-RUN — No enviado" if dry_run else result.status.upper()
        lines.append(f"│{'':─<{width+1}}│")
        lines.append(f"│ {status_icon} Estado: {mode:<{width-11}}│")
        lines.append(f"╰{'─' * (width+1)}╯")

        for line in lines:
            logger.info(line)

    # ── Navegación del formulario ─────────────────────────────────────────────
    def _detect_next_action(self) -> str:
        """Detecta la acción disponible: 'next', 'review', 'submit'."""
        # Submit
        submit_selectors = [
            'button[aria-label*="Submit"]',
            'button[aria-label*="Enviar"]',
            'button:has-text("Submit application")',
            'button:has-text("Enviar solicitud")',
        ]
        for sel in submit_selectors:
            try:
                btn = self._page.locator(sel)
                if btn.count() > 0 and btn.first.is_visible(timeout=1000):
                    return "submit"
            except Exception:
                continue

        # Review
        review_selectors = [
            'button[aria-label*="Review"]',
            'button[aria-label*="Revisar"]',
            'button:has-text("Review")',
            'button:has-text("Revisar")',
        ]
        for sel in review_selectors:
            try:
                btn = self._page.locator(sel)
                if btn.count() > 0 and btn.first.is_visible(timeout=1000):
                    return "review"
            except Exception:
                continue

        # Next
        next_selectors = [
            'button[aria-label*="Next"]',
            'button[aria-label*="Siguiente"]',
            'button:has-text("Next")',
            'button:has-text("Siguiente")',
            'button:has-text("Continue")',
            'button:has-text("Continuar")',
        ]
        for sel in next_selectors:
            try:
                btn = self._page.locator(sel)
                if btn.count() > 0 and btn.first.is_visible(timeout=1000):
                    return "next"
            except Exception:
                continue

        return "unknown"

    def _click_next(self) -> None:
        """Clickea el botón de siguiente paso."""
        next_selectors = [
            'button[aria-label*="Next"]',
            'button[aria-label*="Siguiente"]',
            'button:has-text("Next")',
            'button:has-text("Siguiente")',
            'button:has-text("Continue")',
            'button:has-text("Continuar")',
        ]
        for sel in next_selectors:
            try:
                btn = self._page.locator(sel).first
                if btn.is_visible(timeout=1000):
                    btn.click()
                    return
            except Exception:
                continue

    def _click_submit(self) -> None:
        """Clickea el botón de envío."""
        submit_selectors = [
            'button[aria-label*="Submit"]',
            'button[aria-label*="Enviar"]',
            'button:has-text("Submit application")',
            'button:has-text("Enviar solicitud")',
        ]
        for sel in submit_selectors:
            try:
                btn = self._page.locator(sel).first
                if btn.is_visible(timeout=1000):
                    btn.click()
                    return
            except Exception:
                continue

    def _dismiss_modal(self) -> None:
        """Cierra el modal de Easy Apply sin enviar."""
        dismiss_selectors = [
            'button[aria-label="Dismiss"]',
            'button[aria-label="Descartar"]',
            'button[aria-label="Close"]',
            'button[aria-label="Cerrar"]',
            ".artdeco-modal__dismiss",
        ]
        for sel in dismiss_selectors:
            try:
                btn = self._page.locator(sel).first
                if btn.is_visible(timeout=1000):
                    btn.click()
                    self._human_delay()
                    # Confirmar descarte si hay diálogo
                    confirm = self._page.locator('button:has-text("Discard")').or_(
                        self._page.locator('button:has-text("Descartar")')
                    )
                    if confirm.count() > 0 and confirm.first.is_visible(timeout=2000):
                        confirm.first.click()
                    return
            except Exception:
                continue

    def _submit_application(
        self,
        fields_filled: int,
        fields_total: int,
        unknown_questions: list[str],
        questions_answered: list[dict] | None = None,
        gemini_warnings: list[str] | None = None,
    ) -> ApplyResult:
        """Envía la postulación real."""
        self._click_submit()
        self._human_delay(factor=2.0)

        success = self._check_application_success()
        return ApplyResult(
            success=success,
            status="applied" if success else "failed",
            message=(
                "Postulacion enviada exitosamente"
                if success
                else "Error al enviar postulacion"
            ),
            fields_filled=fields_filled,
            fields_total=fields_total,
            unknown_questions=unknown_questions if unknown_questions else None,
            questions_answered=questions_answered,
            gemini_warnings=gemini_warnings,
        )

    def _check_application_success(self) -> bool:
        """Verifica si la postulación se envió con éxito."""
        success_indicators = [
            'h3:has-text("Your application was sent")',
            'h3:has-text("Tu solicitud fue enviada")',
            'h3:has-text("Application submitted")',
            ".artdeco-inline-feedback--success",
            'img[alt*="application was sent"]',
        ]
        for sel in success_indicators:
            try:
                el = self._page.locator(sel)
                if el.count() > 0 and el.first.is_visible(timeout=5000):
                    return True
            except Exception:
                continue
        return False
