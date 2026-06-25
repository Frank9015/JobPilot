"""
JobPilot — Question Answerer
Motor inteligente de respuesta a preguntas de formularios de postulación.
Usa Gemini Flash para clasificar y responder preguntas desconocidas
basándose en el perfil completo del candidato.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from sqlalchemy.orm import Session

from jobpilot.core.config import get_config, get_settings
from jobpilot.core.logger import get_logger
from jobpilot.core.token_guardian import (
    GeminiModel,
    GeminiOperation,
    QuotaExceededError,
    TokenGuardian,
)
from jobpilot.database.models import JobOffer
from jobpilot.profile.models import ProfileData

logger = get_logger("automation.question_answerer")

# Ruta a fixtures de mock
FIXTURES_DIR = (
    Path(__file__).parent.parent.parent.parent / "tests" / "fixtures" / "gemini"
)


# ── Tipos de pregunta ─────────────────────────────────────────────────────────
class QuestionType(str, Enum):
    YES_NO = "yes_no"
    NUMBER = "number"
    FREE_TEXT = "free_text"
    SALARY = "salary"
    LOCATION = "location"
    AVAILABILITY = "availability"
    EXPERIENCE_YEARS = "experience_years"
    VISA_WORK_PERMIT = "visa_work_permit"
    TECH_SPECIFIC = "tech_specific"
    UNKNOWN = "unknown"


@dataclass
class FormQuestion:
    """Pregunta extraída de un formulario de postulación."""

    label: str
    html_type: str  # text, select, radio, textarea, number, etc.
    options: list[str] = field(default_factory=list)
    required: bool = False

    # Campos que se llenan después del análisis
    question_type: QuestionType = QuestionType.UNKNOWN
    answer: str = ""
    answer_source: str = ""  # "profile_mapping" | "gemini" | "default"
    confidence: str = ""  # "high" | "medium" | "low"
    reasoning: str = ""


@dataclass
class AnswerResult:
    """Resultado del proceso de respuesta batch."""

    questions: list[FormQuestion]
    warnings: list[str] = field(default_factory=list)
    tokens_used: int = 0
    from_cache: bool = False


class QuestionAnswerer:
    """
    Motor inteligente de respuesta a preguntas de formularios.

    Flujo:
    1. Recibe lista de preguntas no resueltas por el form_filler estático.
    2. Construye un prompt batch con todas las preguntas + perfil + oferta.
    3. Envía a Gemini Flash (o mock).
    4. Parsea respuestas y valida coherencia.
    5. Retorna preguntas con respuestas listas para inyectar.

    Uso:
        answerer = QuestionAnswerer(session)
        result = answerer.answer_all(questions, profile, job_offer)
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._config = get_config()
        self._settings = get_settings()
        self._guardian = TokenGuardian(session)

    def answer_all(
        self,
        questions: list[FormQuestion],
        profile: ProfileData,
        job_offer: JobOffer,
    ) -> AnswerResult:
        """
        Responde todas las preguntas usando Gemini o mock.

        Args:
            questions: Preguntas sin respuesta del formulario.
            profile: Perfil completo del candidato.
            job_offer: Oferta laboral actual.

        Returns:
            AnswerResult con preguntas respondidas y warnings.
        """
        if not questions:
            return AnswerResult(questions=[])

        logger.info(f"Respondiendo {len(questions)} preguntas con IA...")

        if self._settings.gemini_mock_mode:
            return self._answer_mock(questions, profile)

        return self._answer_with_gemini(questions, profile, job_offer)

    # ── Gemini ────────────────────────────────────────────────────────────────
    def _answer_with_gemini(
        self,
        questions: list[FormQuestion],
        profile: ProfileData,
        job_offer: JobOffer,
    ) -> AnswerResult:
        """Responde preguntas usando Gemini Flash."""

        prompt = self._build_prompt(questions, profile, job_offer)
        cache_input = prompt  # Usar prompt completo como cache key

        # 1. Verificar caché
        cached = self._guardian.get_cached(
            GeminiOperation.ANSWER_QUESTION, cache_input
        )
        if cached:
            logger.info("Cache hit para respuestas de formulario")
            self._guardian.record_usage(
                GeminiModel.FLASH,
                GeminiOperation.ANSWER_QUESTION,
                tokens_in=0,
                tokens_out=0,
                cache_hit=True,
            )
            return self._parse_gemini_result(questions, cached, from_cache=True)

        # 2. Verificar cuota
        try:
            self._guardian.check_quota(
                GeminiModel.FLASH, GeminiOperation.ANSWER_QUESTION
            )
        except QuotaExceededError:
            logger.warning("Cuota agotada — usando respuestas por defecto")
            return self._answer_defaults(questions, profile)

        # 3. Llamar a Gemini
        try:
            from google import genai

            client = genai.Client(api_key=self._settings.gemini_api_key)
            response = client.models.generate_content(
                model=self._config.gemini_model_flash,
                contents=prompt,
            )

            response_text = response.text
            tokens_in = (
                response.usage_metadata.prompt_token_count
                if response.usage_metadata
                else 0
            )
            tokens_out = (
                response.usage_metadata.candidates_token_count
                if response.usage_metadata
                else 0
            )

            # Registrar uso
            self._guardian.record_usage(
                GeminiModel.FLASH,
                GeminiOperation.ANSWER_QUESTION,
                tokens_in,
                tokens_out,
                cache_hit=False,
            )

            # Parsear respuesta
            data = self._parse_response_json(response_text)

            # Guardar en caché
            self._guardian.save_cache(
                operation=GeminiOperation.ANSWER_QUESTION,
                model=GeminiModel.FLASH,
                input_data=cache_input,
                output=data,
                tokens_used=tokens_in + tokens_out,
            )

            result = self._parse_gemini_result(
                questions, data, tokens_used=tokens_in + tokens_out
            )

            # 4. Validar coherencia
            validation_warnings = self._validate_answers(result.questions, profile)
            result.warnings.extend(validation_warnings)

            return result

        except Exception as e:
            logger.error(f"Error en Gemini para preguntas: {e} — usando defaults")
            return self._answer_defaults(questions, profile)

    # ── Prompt builder ────────────────────────────────────────────────────────
    def _build_prompt(
        self,
        questions: list[FormQuestion],
        profile: ProfileData,
        job_offer: JobOffer,
    ) -> str:
        """Construye el prompt batch para Gemini."""

        profile_summary = profile.to_scoring_summary()

        # Construir bloque de preguntas
        questions_block = []
        for i, q in enumerate(questions):
            entry = f"  {i}. Pregunta: \"{q.label}\"\n     Tipo HTML: {q.html_type}"
            if q.options:
                entry += f"\n     Opciones disponibles: {', '.join(q.options)}"
            if q.required:
                entry += "\n     (Campo obligatorio)"
            questions_block.append(entry)

        questions_text = "\n".join(questions_block)

        return f"""Eres un asistente de postulación laboral. Tu tarea es responder las preguntas de un formulario de postulación en nombre del candidato.

REGLAS CRITICAS:
- Responde UNICAMENTE con datos reales del candidato. NUNCA inventes información.
- Si el candidato NO tiene una certificación, responde "No" honestamente.
- Si el candidato NO tiene experiencia en algo, responde honestamente.
- Para preguntas de Si/No, responde exactamente "Sí" o "No".
- Para preguntas numéricas, responde solo con el número.
- Para selects/radio con opciones, elige la opción que mejor se ajuste (texto exacto de la opción).
- Para texto libre, responde de forma profesional y concisa (máximo 2 oraciones).
- Las fechas deben ser consistentes con la experiencia real del candidato.
- La pretensión salarial debe ser "Negociable" a menos que el perfil indique otra cosa.
- Para disponibilidad, responde "Inmediata" salvo que el candidato esté empleado actualmente.

OFERTA DE EMPLEO:
---
Título: {job_offer.title}
Empresa: {job_offer.company or 'No especificada'}
Ubicación: {job_offer.location or 'No especificada'}
Descripción: {(job_offer.description or '')[:800]}
---

PERFIL DEL CANDIDATO:
---
{profile_summary}
---

PREGUNTAS DEL FORMULARIO:
---
{questions_text}
---

Responde UNICAMENTE con un JSON válido con esta estructura:
{{
  "answers": [
    {{
      "question_index": <índice de la pregunta (0-based)>,
      "answer": "<respuesta exacta para el campo>",
      "confidence": "high|medium|low",
      "reasoning": "<explicación breve de por qué esta respuesta>"
    }}
  ],
  "warnings": ["<advertencia si alguna respuesta podría ser problemática>"]
}}

Responde SOLO con el JSON, sin markdown, sin texto adicional."""

    # ── Parser de respuesta ───────────────────────────────────────────────────
    @staticmethod
    def _parse_response_json(response_text: str) -> dict:
        """Limpia y parsea la respuesta JSON de Gemini."""
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            )
        return json.loads(text)

    def _parse_gemini_result(
        self,
        questions: list[FormQuestion],
        data: dict,
        tokens_used: int = 0,
        from_cache: bool = False,
    ) -> AnswerResult:
        """Mapea respuestas de Gemini a los FormQuestion originales."""
        answers_list = data.get("answers", [])
        warnings = data.get("warnings", [])

        for answer_data in answers_list:
            idx = answer_data.get("question_index", -1)
            if 0 <= idx < len(questions):
                q = questions[idx]
                q.answer = str(answer_data.get("answer", ""))
                q.answer_source = "gemini"
                q.confidence = answer_data.get("confidence", "medium")
                q.reasoning = answer_data.get("reasoning", "")

                # Clasificar tipo semántico basado en la respuesta de Gemini
                q.question_type = self._infer_question_type(q)

        # Preguntas sin respuesta → default
        for q in questions:
            if not q.answer:
                q.answer = ""
                q.answer_source = "default"
                q.confidence = "low"
                warnings.append(f"Sin respuesta para: '{q.label}'")

        return AnswerResult(
            questions=questions,
            warnings=warnings,
            tokens_used=tokens_used,
            from_cache=from_cache,
        )

    # ── Clasificador de tipo semántico ────────────────────────────────────────
    @staticmethod
    def _infer_question_type(q: FormQuestion) -> QuestionType:
        """Infiere el tipo semántico de una pregunta basándose en su label."""
        import re

        label = q.label.lower()

        # Visa / Permiso de trabajo
        if re.search(
            r"visa|sponsor|autorizad[oa]|permiso.*trabajo|legal.*right|work.*permit",
            label,
        ):
            return QuestionType.VISA_WORK_PERMIT

        # Salario
        if re.search(
            r"salar[iy]|sueldo|remunerac|pretens[ió]|renta|compensation|pay",
            label,
        ):
            return QuestionType.SALARY

        # Años de experiencia
        if re.search(
            r"a[nñ]os?.*experiencia|years?.*experience|experience.*years?",
            label,
        ):
            return QuestionType.EXPERIENCE_YEARS

        # Disponibilidad
        if re.search(
            r"disponib|start.*date|fecha.*inicio|when.*start|cu[áa]ndo|notice.*period",
            label,
        ):
            return QuestionType.AVAILABILITY

        # Ubicación
        if re.search(
            r"ubicaci[óo]n|location|city|ciudad|relocat|mudarse",
            label,
        ):
            return QuestionType.LOCATION

        # Tecnología específica
        if re.search(
            r"certific|experiencia.*con|experience.*with|proficien|conocimiento.*en|familiar.*with",
            label,
        ):
            return QuestionType.TECH_SPECIFIC

        # Sí/No (radio o select con 2 opciones)
        if q.html_type == "radio" and len(q.options) == 2:
            return QuestionType.YES_NO

        # Numérico
        if q.html_type == "number":
            return QuestionType.NUMBER

        # Texto libre
        if q.html_type in ("textarea", "text"):
            return QuestionType.FREE_TEXT

        return QuestionType.UNKNOWN

    # ── Validación de coherencia ──────────────────────────────────────────────
    @staticmethod
    def _validate_answers(
        questions: list[FormQuestion],
        profile: ProfileData,
    ) -> list[str]:
        """
        Valida que las respuestas generadas no contradigan el perfil.
        Retorna lista de warnings.
        """
        warnings: list[str] = []
        from datetime import date

        # Calcular años reales de experiencia
        total_days = 0
        for exp in profile.work_experience:
            if exp.start_date:
                end = exp.end_date or date.today()
                total_days += (end - exp.start_date).days
        real_years = max(0, total_days // 365)

        candidate_skills = {s.name.lower() for s in profile.skills}

        for q in questions:
            if not q.answer:
                continue

            # Verificar años de experiencia
            if q.question_type == QuestionType.EXPERIENCE_YEARS:
                try:
                    declared = int(q.answer)
                    if declared > real_years + 1:
                        warnings.append(
                            f"Experiencia declarada ({declared} años) excede "
                            f"la experiencia real ({real_years} años): '{q.label}'"
                        )
                except (ValueError, TypeError):
                    pass

            # Verificar tecnologías
            if q.question_type == QuestionType.TECH_SPECIFIC:
                if q.answer.lower() in ("sí", "si", "yes", "true"):
                    # Extraer nombre de la tecnología de la pregunta
                    label_lower = q.label.lower()
                    # Si la pregunta menciona una tech que no tenemos, warning
                    found_match = any(
                        skill in label_lower for skill in candidate_skills
                    )
                    if not found_match:
                        warnings.append(
                            f"Respuesta afirmativa para tecnología no listada "
                            f"en el perfil: '{q.label}'"
                        )

        return warnings

    # ── Respuestas por defecto (fallback sin Gemini) ──────────────────────────
    @staticmethod
    def _answer_defaults(
        questions: list[FormQuestion],
        profile: ProfileData,
    ) -> AnswerResult:
        """Responde con valores seguros por defecto cuando Gemini no está disponible."""
        from datetime import date

        warnings: list[str] = []

        for q in questions:
            q.answer_source = "default"
            q.confidence = "low"
            q.question_type = QuestionAnswerer._infer_question_type(q)

            if q.question_type == QuestionType.YES_NO:
                # Asumir respuesta positiva para permisos de trabajo
                if q.question_type == QuestionType.VISA_WORK_PERMIT:
                    q.answer = "Sí"
                else:
                    q.answer = "Sí"
                    warnings.append(
                        f"Respuesta por defecto 'Sí' para: '{q.label}'"
                    )

            elif q.question_type == QuestionType.EXPERIENCE_YEARS:
                total_days = sum(
                    ((exp.end_date or date.today()) - exp.start_date).days
                    for exp in profile.work_experience
                    if exp.start_date
                )
                q.answer = str(max(0, total_days // 365))

            elif q.question_type == QuestionType.SALARY:
                q.answer = "Negociable"

            elif q.question_type == QuestionType.AVAILABILITY:
                is_employed = any(exp.is_current for exp in profile.work_experience)
                q.answer = "2 semanas" if is_employed else "Inmediata"

            elif q.question_type == QuestionType.LOCATION:
                q.answer = profile.personal_info.location or "Santiago, Chile"

            elif q.question_type == QuestionType.VISA_WORK_PERMIT:
                q.answer = "Sí"

            elif q.html_type == "select" and q.options:
                q.answer = q.options[0] if q.options else ""
                warnings.append(
                    f"Primera opción seleccionada por defecto para: '{q.label}'"
                )

            else:
                q.answer = ""
                warnings.append(f"Sin respuesta disponible para: '{q.label}'")

        return AnswerResult(questions=questions, warnings=warnings)

    # ── Mock ──────────────────────────────────────────────────────────────────
    def _answer_mock(
        self,
        questions: list[FormQuestion],
        profile: ProfileData,
    ) -> AnswerResult:
        """Responde con datos mockeados para modo desarrollo."""
        mock_file = FIXTURES_DIR / "mock_question_answers.json"

        if mock_file.exists():
            try:
                with open(mock_file, encoding="utf-8") as f:
                    data = json.load(f)
                logger.info("[MOCK] Usando fixture de respuestas")
                return self._parse_gemini_result(questions, data)
            except Exception as e:
                logger.warning(f"Error leyendo mock fixture: {e}")

        # Fallback: generar respuestas por defecto
        logger.info("[MOCK] Generando respuestas por defecto")
        return self._answer_defaults(questions, profile)
