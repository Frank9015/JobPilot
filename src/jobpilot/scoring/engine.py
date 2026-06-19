"""
JobPilot — Scoring Engine
Motor de scoring semántico que evalúa compatibilidad entre ofertas y perfil.
Usa Gemini Flash como motor principal con fallback a heurísticas.
Integra TokenGuardian para caché y control de cuota.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobpilot.core.config import get_config, get_settings
from jobpilot.core.logger import get_logger
from jobpilot.core.token_guardian import (
    GeminiModel,
    GeminiOperation,
    QuotaExceededError,
    TokenGuardian,
)
from jobpilot.database.models import JobOffer, JobScore
from jobpilot.profile.models import ProfileData
from jobpilot.scoring.models import ScoreResult
from jobpilot.scoring.rules import HeuristicScorer

logger = get_logger("scoring.engine")

# Ruta a los fixtures de mock
FIXTURES_DIR = (
    Path(__file__).parent.parent.parent.parent / "tests" / "fixtures" / "gemini"
)


class ScoringEngine:
    """
    Motor de scoring para evaluar compatibilidad oferta-perfil.

    Flujo:
    1. Verificar caché (gemini_cache) → si existe, retornar
    2. Verificar cuota (TokenGuardian)
    3. Llamar a Gemini Flash con prompt optimizado
    4. Guardar en caché + registrar uso
    5. Persistir score en tabla job_score
    6. Si falla Gemini → fallback a HeuristicScorer

    Uso:
        engine = ScoringEngine(session)
        result = engine.score_job(job_offer, profile_data)
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._config = get_config()
        self._settings = get_settings()
        self._guardian = TokenGuardian(session)
        self._heuristic = HeuristicScorer()

    # ── Scoring principal ─────────────────────────────────────────────────────
    def score_job(
        self,
        job_offer: JobOffer,
        profile: ProfileData,
    ) -> ScoreResult:
        """
        Calcula el score de compatibilidad entre una oferta y el perfil.
        Intenta Gemini Flash, fallback a heurísticas si falla.
        """
        # 0. Verificar si ya tiene score
        existing_score = self._session.scalar(
            select(JobScore).where(JobScore.job_offer_id == job_offer.id)
        )
        if existing_score:
            logger.debug(
                f"Score existente para '{job_offer.title[:40]}': {existing_score.total_score}"
            )
            return self._orm_to_result(existing_score)

        # 1. Mock mode
        if self._settings.gemini_mock_mode:
            result = self._score_mock(job_offer, profile)
        else:
            # 2. Intentar Gemini, fallback a heurístico
            result = self._score_with_gemini(job_offer, profile)

        # 3. Persistir en BD
        self._persist_score(job_offer, profile, result)

        return result

    # ── Scoring con Gemini Flash ──────────────────────────────────────────────
    def _score_with_gemini(
        self,
        job_offer: JobOffer,
        profile: ProfileData,
    ) -> ScoreResult:
        """Intenta scoring con Gemini Flash. Fallback a heurísticas si falla."""

        # Preparar datos para cache key
        offer_text = self._build_offer_text(job_offer)
        profile_summary = profile.to_scoring_summary()
        cache_input = f"{offer_text}|||{profile_summary}"

        # 1. Verificar caché
        cached = self._guardian.get_cached(GeminiOperation.SCORE_JOB, cache_input)
        if cached:
            logger.info(f"Cache hit para '{job_offer.title[:40]}'")
            self._guardian.record_usage(
                GeminiModel.FLASH,
                GeminiOperation.SCORE_JOB,
                tokens_in=0,
                tokens_out=0,
                cache_hit=True,
            )
            result = ScoreResult(**cached)
            result.cache_hit = True
            return result

        # 2. Verificar cuota
        try:
            self._guardian.check_quota(GeminiModel.FLASH, GeminiOperation.SCORE_JOB)
        except QuotaExceededError:
            logger.warning(
                f"Cuota agotada — fallback heuristico para '{job_offer.title[:40]}'"
            )
            return self._score_heuristic(job_offer, profile)

        # 3. Llamar a Gemini Flash
        try:
            result = self._call_gemini(job_offer, profile, offer_text, profile_summary)

            # 4. Guardar en caché
            self._guardian.save_cache(
                operation=GeminiOperation.SCORE_JOB,
                model=GeminiModel.FLASH,
                input_data=cache_input,
                output=result.model_dump(),
                tokens_used=result.tokens_used,
            )

            return result

        except Exception as e:
            logger.error(f"Error en Gemini scoring: {e} — fallback heuristico")
            return self._score_heuristic(job_offer, profile)

    def _call_gemini(
        self,
        job_offer: JobOffer,
        profile: ProfileData,
        offer_text: str,
        profile_summary: str,
    ) -> ScoreResult:
        """Ejecuta la llamada real a Gemini Flash y parsea la respuesta."""
        from google import genai

        client = genai.Client(api_key=self._settings.gemini_api_key)
        prompt = self._build_scoring_prompt(offer_text, profile_summary)

        logger.info(f"Scoring con Gemini Flash: '{job_offer.title[:50]}'")
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

        # Registrar uso
        self._guardian.record_usage(
            GeminiModel.FLASH,
            GeminiOperation.SCORE_JOB,
            tokens_in,
            tokens_out,
            cache_hit=False,
        )

        # Parsear respuesta JSON
        data = self._parse_gemini_response(response_text)

        return ScoreResult(
            total_score=float(data.get("total_score", 0)),
            skill_match=float(data.get("skill_match", 0)),
            experience_match=float(data.get("experience_match", 0)),
            education_match=float(data.get("education_match", 0)),
            location_match=float(data.get("location_match", 0)),
            salary_match=float(data.get("salary_match", 0)),
            reasoning=data.get("reasoning", ""),
            matched_skills=data.get("matched_skills", []),
            missing_skills=data.get("missing_skills", []),
            recommendation=data.get("recommendation", ""),
            score_method="gemini",
            tokens_used=tokens_in + tokens_out,
        )

    # ── Scoring heurístico (fallback) ─────────────────────────────────────────
    def _score_heuristic(
        self,
        job_offer: JobOffer,
        profile: ProfileData,
    ) -> ScoreResult:
        """Delega al motor heurístico como fallback."""
        return self._heuristic.score(
            job_title=job_offer.title,
            job_description=job_offer.description,
            job_requirements=job_offer.requirements,
            job_location=job_offer.location,
            job_salary_min=job_offer.salary_min,
            job_salary_max=job_offer.salary_max,
            profile=profile,
        )

    # ── Scoring mock ──────────────────────────────────────────────────────────
    def _score_mock(
        self,
        job_offer: JobOffer,
        profile: ProfileData,
    ) -> ScoreResult:
        """Usa fixture predefinido para modo mock."""
        mock_file = FIXTURES_DIR / "mock_score_response.json"
        if not mock_file.exists():
            logger.warning("Mock score fixture no encontrado — usando heuristico")
            return self._score_heuristic(job_offer, profile)

        with open(mock_file, encoding="utf-8") as f:
            data = json.load(f)

        logger.info(
            f"[yellow]MOCK[/yellow] Score para '{job_offer.title[:40]}': {data.get('total_score', 0)}"
        )

        return ScoreResult(
            total_score=float(data.get("total_score", 0)),
            skill_match=float(data.get("skill_match", 0)),
            experience_match=float(data.get("experience_match", 0)),
            education_match=float(data.get("education_match", 0)),
            location_match=float(data.get("location_match", 0)),
            salary_match=float(data.get("salary_match", 0)),
            reasoning=data.get("reasoning", ""),
            matched_skills=data.get("matched_skills", []),
            missing_skills=data.get("missing_skills", []),
            recommendation=data.get("recommendation", ""),
            score_method="mock",
        )

    # ── Batch scoring ─────────────────────────────────────────────────────────
    def score_pending_offers(self, profile: ProfileData) -> list[ScoreResult]:
        """
        Ejecuta scoring sobre todas las ofertas con status='new'.
        Retorna lista de resultados.
        """
        offers = self._session.scalars(
            select(JobOffer).where(JobOffer.status == "new")
        ).all()

        if not offers:
            logger.info("No hay ofertas pendientes de scoring")
            return []

        logger.info(f"Scoring de {len(offers)} ofertas pendientes...")
        results: list[ScoreResult] = []

        for i, offer in enumerate(offers, 1):
            try:
                result = self.score_job(offer, profile)
                results.append(result)

                # Actualizar status de la oferta
                offer.status = "scored"
                self._session.flush()

                logger.info(
                    f"  [{i}/{len(offers)}] {offer.title[:45]}: "
                    f"{result.total_score:.1f}% ({result.score_method})"
                )

            except Exception as e:
                logger.error(
                    f"  [{i}/{len(offers)}] Error scoring '{offer.title[:40]}': {e}"
                )
                offer.status = "error"
                self._session.flush()

        # Resumen
        if results:
            avg = sum(r.total_score for r in results) / len(results)
            above_threshold = sum(
                1 for r in results if r.total_score >= self._config.min_score_to_apply
            )
            logger.info(
                f"Scoring completo: promedio={avg:.1f}%, "
                f"{above_threshold}/{len(results)} sobre umbral {self._config.min_score_to_apply}%"
            )

        return results

    # ── Persistencia ──────────────────────────────────────────────────────────
    def _persist_score(
        self,
        job_offer: JobOffer,
        profile: ProfileData,
        result: ScoreResult,
    ) -> None:
        """Guarda el resultado de scoring en la tabla job_score."""
        from jobpilot.database.models import CandidateProfile

        # Obtener profile_id desde BD
        profile_orm = self._session.scalar(
            select(CandidateProfile)
            .order_by(CandidateProfile.created_at.desc())
            .limit(1)
        )
        if not profile_orm:
            logger.warning("No se encontro perfil en BD para asociar al score")
            return

        score = JobScore(
            job_offer_id=job_offer.id,
            profile_id=profile_orm.id,
            total_score=result.total_score,
            skill_match=result.skill_match,
            experience_match=result.experience_match,
            education_match=result.education_match,
            location_match=result.location_match,
            salary_match=result.salary_match,
            gemini_reasoning=result.reasoning,
            score_method=result.score_method,
        )
        self._session.add(score)
        self._session.flush()

    # ── Construcción de prompts ───────────────────────────────────────────────
    @staticmethod
    def _build_offer_text(job_offer: JobOffer) -> str:
        """Construye texto compacto de la oferta para el prompt."""
        parts = [f"Titulo: {job_offer.title}"]
        if job_offer.company:
            parts.append(f"Empresa: {job_offer.company}")
        if job_offer.location:
            parts.append(f"Ubicacion: {job_offer.location}")
        if job_offer.modality:
            parts.append(f"Modalidad: {job_offer.modality}")
        if job_offer.description:
            # Limitar a 2000 chars para economía de tokens
            parts.append(f"Descripcion:\n{job_offer.description[:2000]}")
        if job_offer.requirements:
            parts.append(f"Requisitos:\n{job_offer.requirements[:800]}")
        if job_offer.salary_min or job_offer.salary_max:
            salary = f"${job_offer.salary_min or '?'} - ${job_offer.salary_max or '?'} {job_offer.currency}"
            parts.append(f"Sueldo: {salary}")
        return "\n".join(parts)

    @staticmethod
    def _build_scoring_prompt(offer_text: str, profile_summary: str) -> str:
        """Construye el prompt de scoring optimizado para token economy."""
        return f"""Eres un evaluador de compatibilidad laboral. Analiza la siguiente oferta de empleo contra el perfil del candidato.

REGLAS CRITICAS:
- Evalua OBJETIVAMENTE cada dimension de 0 a 100.
- NO inventes skills que el candidato no tiene.
- Para un candidato recien egresado, considera que poca experiencia es NORMAL para roles junior.
- Sé realista con los puntajes: un junior aplicando a un rol senior debe tener score bajo.

OFERTA DE EMPLEO:
---
{offer_text}
---

PERFIL DEL CANDIDATO:
---
{profile_summary}
---

Responde UNICAMENTE con un JSON valido con esta estructura:
{{
  "skill_match": <0-100>,
  "experience_match": <0-100>,
  "education_match": <0-100>,
  "location_match": <0-100>,
  "salary_match": <0-100>,
  "total_score": <promedio ponderado: skills 40%, experiencia 25%, educacion 15%, ubicacion 10%, salario 10%>,
  "reasoning": "<explicacion breve en español de 2-3 oraciones>",
  "matched_skills": ["skill1", "skill2"],
  "missing_skills": ["skill3", "skill4"],
  "recommendation": "Postular | No postular | Revisar — <razon breve>"
}}

Responde SOLO con el JSON, sin markdown, sin texto adicional."""

    @staticmethod
    def _parse_gemini_response(response_text: str) -> dict:
        """Limpia y parsea la respuesta JSON de Gemini."""
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(text)

    # ── Conversión ORM → Result ───────────────────────────────────────────────
    @staticmethod
    def _orm_to_result(score: JobScore) -> ScoreResult:
        """Convierte un JobScore ORM a ScoreResult Pydantic."""
        return ScoreResult(
            total_score=float(score.total_score or 0),
            skill_match=float(score.skill_match or 0),
            experience_match=float(score.experience_match or 0),
            education_match=float(score.education_match or 0),
            location_match=float(score.location_match or 0),
            salary_match=float(score.salary_match or 0),
            reasoning=score.gemini_reasoning or "",
            score_method=score.score_method or "unknown",
        )
