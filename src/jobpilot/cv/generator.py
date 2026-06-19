"""
JobPilot — CV Generator
Adapta inteligentemente el CV del candidato para cada oferta usando Gemini.
REGLA FUNDAMENTAL: NUNCA inventa experiencia, skills o logros.
Solo reorganiza, enfatiza y reformula contenido REAL del perfil.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field
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
from jobpilot.scoring.models import ScoreResult

logger = get_logger("cv.generator")

FIXTURES_DIR = (
    Path(__file__).parent.parent.parent.parent / "tests" / "fixtures" / "gemini"
)


# ── Modelo de CV adaptado ─────────────────────────────────────────────────────
class AdaptedCV(BaseModel):
    """Resultado de la adaptacion inteligente del CV por Gemini."""

    emphasis_notes: str = Field("", description="Notas sobre que se enfatizo y por que")
    sections_order: list[str] = Field(
        default_factory=lambda: ["skills", "experience", "projects", "education"],
        description="Orden recomendado de secciones para esta oferta",
    )
    adapted_summary: str = Field(
        "", description="Resumen profesional adaptado a la oferta"
    )
    highlighted_skills: list[str] = Field(
        default_factory=list, description="Skills a destacar visualmente"
    )
    highlighted_projects: list[str] = Field(
        default_factory=list, description="Proyectos a destacar"
    )
    reformulated_descriptions: dict[str, str] = Field(
        default_factory=dict,
        description="Descripciones reformuladas (key=nombre proyecto/exp, value=nueva descripcion)",
    )
    tokens_used: int = 0
    adaptation_method: str = "gemini"  # gemini | template_only | mock


class CVGenerator:
    """
    Genera CVs adaptados inteligentemente para cada oferta laboral.

    Flujo:
    1. Gemini analiza la oferta y el perfil.
    2. Sugiere reorganizacion, enfasis y reformulaciones.
    3. El renderer usa estas sugerencias para generar el PDF.

    NUNCA inventa contenido — solo reorganiza lo existente.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._config = get_config()
        self._settings = get_settings()
        self._guardian = TokenGuardian(session)

    def adapt_cv(
        self,
        profile: ProfileData,
        job_offer: JobOffer,
        score_result: ScoreResult | None = None,
    ) -> AdaptedCV:
        """
        Genera una adaptacion del CV para una oferta especifica.
        Usa Gemini Flash para inteligencia, fallback a template basico.
        """
        # Mock mode
        if self._settings.gemini_mock_mode:
            return self._adapt_mock(profile, job_offer)

        # Intentar con Gemini
        return self._adapt_with_gemini(profile, job_offer, score_result)

    # ── Adaptacion con Gemini ─────────────────────────────────────────────────
    def _adapt_with_gemini(
        self,
        profile: ProfileData,
        job_offer: JobOffer,
        score_result: ScoreResult | None,
    ) -> AdaptedCV:
        """Usa Gemini Flash para adaptar el CV inteligentemente."""

        profile_summary = profile.to_scoring_summary()
        offer_text = self._build_offer_text(job_offer)
        cache_input = f"adapt_cv:{offer_text}|||{profile_summary}"

        # 1. Cache
        cached = self._guardian.get_cached(GeminiOperation.ADAPT_CV, cache_input)
        if cached:
            logger.info(f"Cache hit para adaptacion CV: '{job_offer.title[:40]}'")
            self._guardian.record_usage(
                GeminiModel.FLASH,
                GeminiOperation.ADAPT_CV,
                tokens_in=0,
                tokens_out=0,
                cache_hit=True,
            )
            result = AdaptedCV(**cached)
            result.adaptation_method = "gemini"
            return result

        # 2. Cuota
        try:
            self._guardian.check_quota(GeminiModel.FLASH, GeminiOperation.ADAPT_CV)
        except QuotaExceededError:
            logger.warning("Cuota agotada — generando CV con template basico")
            return self._adapt_template_only(profile, job_offer, score_result)

        # 3. Llamar a Gemini
        try:
            result = self._call_gemini(
                profile, job_offer, offer_text, profile_summary, score_result
            )

            # 4. Guardar en cache
            self._guardian.save_cache(
                operation=GeminiOperation.ADAPT_CV,
                model=GeminiModel.FLASH,
                input_data=cache_input,
                output=result.model_dump(),
                tokens_used=result.tokens_used,
            )

            return result

        except Exception as e:
            logger.error(f"Error en Gemini CV adapt: {e} — usando template basico")
            return self._adapt_template_only(profile, job_offer, score_result)

    def _call_gemini(
        self,
        profile: ProfileData,
        job_offer: JobOffer,
        offer_text: str,
        profile_summary: str,
        score_result: ScoreResult | None,
    ) -> AdaptedCV:
        """Ejecuta la llamada a Gemini para adaptacion del CV."""
        from google import genai

        client = genai.Client(api_key=self._settings.gemini_api_key)
        prompt = self._build_adapt_prompt(
            profile, job_offer, offer_text, profile_summary, score_result
        )

        logger.info(f"Adaptando CV con Gemini para: '{job_offer.title[:50]}'")
        response = client.models.generate_content(
            model=self._config.gemini_model_flash,
            contents=prompt,
        )

        response_text = response.text
        tokens_in = (
            response.usage_metadata.prompt_token_count if response.usage_metadata else 0
        )
        tokens_out = (
            response.usage_metadata.candidates_token_count
            if response.usage_metadata
            else 0
        )

        self._guardian.record_usage(
            GeminiModel.FLASH,
            GeminiOperation.ADAPT_CV,
            tokens_in,
            tokens_out,
            cache_hit=False,
        )

        data = self._parse_response(response_text)

        return AdaptedCV(
            emphasis_notes=data.get("emphasis_notes", ""),
            sections_order=data.get(
                "sections_order", ["skills", "experience", "projects", "education"]
            ),
            adapted_summary=data.get("adapted_summary", ""),
            highlighted_skills=data.get("highlighted_skills", []),
            highlighted_projects=data.get("highlighted_projects", []),
            reformulated_descriptions=data.get("reformulated_descriptions", {}),
            tokens_used=tokens_in + tokens_out,
            adaptation_method="gemini",
        )

    # ── Fallback: template only ───────────────────────────────────────────────
    def _adapt_template_only(
        self,
        profile: ProfileData,
        job_offer: JobOffer,
        score_result: ScoreResult | None,
    ) -> AdaptedCV:
        """Adaptacion basica sin Gemini: reordena secciones y destaca skills coincidentes."""
        offer_text = f"{job_offer.title} {job_offer.description or ''} {job_offer.requirements or ''}".lower()

        # Skills que coinciden con la oferta
        matched = [s.name for s in profile.skills if s.name.lower() in offer_text]

        # Proyectos relevantes
        highlighted_projects = []
        for proj in profile.projects:
            if any(tech.lower() in offer_text for tech in (proj.tech_stack or [])):
                highlighted_projects.append(proj.name)

        # Orden de secciones: si hay experiencia laboral, ponerla primero
        if profile.work_experience:
            sections_order = ["experience", "skills", "projects", "education"]
        else:
            sections_order = ["skills", "projects", "education"]

        return AdaptedCV(
            emphasis_notes=f"Template basico: {len(matched)} skills coincidentes destacados.",
            sections_order=sections_order,
            adapted_summary=profile.personal_info.summary or "",
            highlighted_skills=matched,
            highlighted_projects=highlighted_projects,
            adaptation_method="template_only",
        )

    # ── Mock mode ─────────────────────────────────────────────────────────────
    def _adapt_mock(self, profile: ProfileData, job_offer: JobOffer) -> AdaptedCV:
        """Usa fixture predefinido."""
        mock_file = FIXTURES_DIR / "mock_cv_adapt_response.json"
        if not mock_file.exists():
            logger.warning(
                "Mock CV adapt fixture no encontrado — usando template basico"
            )
            return self._adapt_template_only(profile, job_offer, None)

        with open(mock_file, encoding="utf-8") as f:
            data = json.load(f)

        logger.info(f"[yellow]MOCK[/yellow] CV adaptado para '{job_offer.title[:40]}'")
        return AdaptedCV(
            emphasis_notes=data.get("emphasis_notes", ""),
            sections_order=data.get("sections_order", []),
            adapted_summary=data.get("adapted_summary", ""),
            highlighted_skills=data.get("highlighted_skills", []),
            highlighted_projects=data.get("highlighted_projects", []),
            reformulated_descriptions=data.get("reformulated_descriptions", {}),
            adaptation_method="mock",
        )

    # ── Prompt de adaptacion ──────────────────────────────────────────────────
    @staticmethod
    def _build_adapt_prompt(
        profile: ProfileData,
        job_offer: JobOffer,
        offer_text: str,
        profile_summary: str,
        score_result: ScoreResult | None,
    ) -> str:
        score_info = ""
        if score_result:
            score_info = f"""
Score de compatibilidad: {score_result.total_score:.1f}%
Skills coincidentes: {', '.join(score_result.matched_skills)}
Skills faltantes: {', '.join(score_result.missing_skills)}
"""
        return f"""Eres un experto en optimizacion de CVs para postulaciones laborales.

REGLAS CRITICAS — INVIOLABLES:
1. NUNCA inventes experiencia laboral que el candidato NO tiene.
2. NUNCA agregues tecnologias o skills que NO aparecen en el perfil.
3. NUNCA afirmes niveles de conocimiento que no existen.
4. SOLO puedes: reorganizar secciones, enfatizar skills existentes, reformular descripciones con las MISMAS actividades reales.

OFERTA DE EMPLEO:
---
{offer_text}
---

PERFIL DEL CANDIDATO:
---
{profile_summary}
---
{score_info}

Genera adaptaciones para el CV del candidato. Responde UNICAMENTE con JSON valido:
{{
  "emphasis_notes": "<explicacion breve de que adaptaste y por que>",
  "sections_order": ["skills", "projects", "education"],
  "adapted_summary": "<resumen profesional de 2-3 lineas adaptado a la oferta, usando SOLO datos reales>",
  "highlighted_skills": ["skill1", "skill2"],
  "highlighted_projects": ["proyecto1"],
  "reformulated_descriptions": {{
    "Nombre Proyecto": "<descripcion reformulada enfatizando aspectos relevantes para la oferta>"
  }}
}}

Responde SOLO con el JSON, sin markdown ni explicaciones."""

    @staticmethod
    def _build_offer_text(job_offer: JobOffer) -> str:
        parts = [f"Titulo: {job_offer.title}"]
        if job_offer.company:
            parts.append(f"Empresa: {job_offer.company}")
        if job_offer.location:
            parts.append(f"Ubicacion: {job_offer.location}")
        if job_offer.description:
            parts.append(f"Descripcion:\n{job_offer.description[:2000]}")
        if job_offer.requirements:
            parts.append(f"Requisitos:\n{job_offer.requirements[:800]}")
        return "\n".join(parts)

    @staticmethod
    def _parse_response(response_text: str) -> dict:
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(text)
