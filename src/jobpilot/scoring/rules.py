"""
JobPilot — Heuristic Scoring Rules
Motor de scoring basado en heurísticas como fallback cuando Gemini
no está disponible (cuota agotada, mock mode, error).
"""
from __future__ import annotations

import re
from typing import Any

from jobpilot.core.config import get_config
from jobpilot.core.logger import get_logger
from jobpilot.profile.models import ProfileData, SkillCategory
from jobpilot.scoring.models import ScoreResult

logger = get_logger("scoring.rules")


class HeuristicScorer:
    """
    Calcula scoring de compatibilidad usando reglas heurísticas.
    No consume tokens de Gemini — es el fallback automático.
    """

    def __init__(self) -> None:
        self._config = get_config()

    def score(
        self,
        job_title: str,
        job_description: str | None,
        job_requirements: str | None,
        job_location: str | None,
        job_salary_min: int | None,
        job_salary_max: int | None,
        profile: ProfileData,
    ) -> ScoreResult:
        """Calcula scoring heurístico de una oferta contra el perfil."""

        # Combinar textos de la oferta para análisis
        offer_text = " ".join(filter(None, [
            job_title, job_description, job_requirements,
        ])).lower()

        if not offer_text.strip():
            return ScoreResult(
                total_score=0.0,
                reasoning="Oferta sin texto para analizar.",
                score_method="heuristic",
                recommendation="No postular — sin datos suficientes",
            )

        # Calcular cada dimensión
        skill_score, matched, missing = self._score_skills(offer_text, profile)
        experience_score = self._score_experience(offer_text, profile)
        education_score = self._score_education(offer_text, profile)
        location_score = self._score_location(job_location, profile)
        salary_score = self._score_salary(job_salary_min, job_salary_max)

        # Puntaje total ponderado
        weights = self._config.score_weights
        total = (
            skill_score * weights["skill_match"] / 100
            + experience_score * weights["experience_match"] / 100
            + education_score * weights["education_match"] / 100
            + location_score * weights["location_match"] / 100
            + salary_score * weights["salary_match"] / 100
        )

        # Recomendación
        min_score = self._config.min_score_to_apply
        if total >= min_score:
            recommendation = f"Postular -- score {total:.1f} >= umbral {min_score}"
        elif total >= min_score - 10:
            recommendation = f"Revisar -- score {total:.1f} cercano al umbral {min_score}"
        else:
            recommendation = f"No postular -- score {total:.1f} < umbral {min_score}"

        reasoning = (
            f"Heuristico: skills={skill_score:.0f} ({len(matched)}/{len(matched)+len(missing)} match), "
            f"exp={experience_score:.0f}, edu={education_score:.0f}, "
            f"loc={location_score:.0f}, sal={salary_score:.0f}. "
            f"Skills encontrados: {', '.join(matched[:8]) or 'ninguno'}. "
            f"Skills faltantes: {', '.join(missing[:5]) or 'ninguno'}."
        )

        return ScoreResult(
            total_score=round(total, 2),
            skill_match=round(skill_score, 2),
            experience_match=round(experience_score, 2),
            education_match=round(education_score, 2),
            location_match=round(location_score, 2),
            salary_match=round(salary_score, 2),
            reasoning=reasoning,
            matched_skills=matched,
            missing_skills=missing,
            recommendation=recommendation,
            score_method="heuristic",
        )

    # ── Skill Match ───────────────────────────────────────────────────────────
    def _score_skills(
        self,
        offer_text: str,
        profile: ProfileData,
    ) -> tuple[float, list[str], list[str]]:
        """
        Calcula match de skills del perfil contra el texto de la oferta.
        Retorna (score, matched_skills, missing_from_offer).
        """
        # Skills técnicos del perfil (excluir soft skills)
        tech_skills = [
            s for s in profile.skills
            if s.category != SkillCategory.SOFT
        ]

        if not tech_skills:
            return 50.0, [], []  # Sin skills = neutro

        matched: list[str] = []
        not_matched: list[str] = []

        for skill in tech_skills:
            # Normalizar nombre del skill para búsqueda
            skill_name = skill.name.lower()
            # Buscar como palabra completa o parte de compuesto
            # Ej: "Python" matchea "python", "python3", "python developer"
            pattern = re.compile(
                r'\b' + re.escape(skill_name) + r'(?:\b|[\s,.\-/])',
                re.IGNORECASE,
            )
            if pattern.search(offer_text):
                matched.append(skill.name)
            else:
                not_matched.append(skill.name)

        if not matched and not not_matched:
            return 50.0, [], []

        # Score = porcentaje de skills del perfil que aparecen en la oferta
        score = (len(matched) / len(tech_skills)) * 100

        # Bonus: si la oferta menciona skills que tenemos de nivel intermedio+
        intermediate_plus = [
            s.name for s in tech_skills
            if s.level in ("intermediate", "advanced") and s.name in matched
        ]
        if intermediate_plus:
            score = min(100.0, score + len(intermediate_plus) * 3)

        # Skills pedidos en la oferta que NO tenemos (heurístico simple)
        common_tech_keywords = [
            "docker", "kubernetes", "aws", "azure", "gcp", "java", "c#", "c++",
            "go", "rust", "ruby", "php", "swift", "kotlin", "scala",
            "angular", "vue", "svelte", "next.js", "nuxt", "spring",
            "flask", "laravel", "rails",
            "mongodb", "redis", "elasticsearch", "kafka", "rabbitmq",
            "terraform", "ansible", "ci/cd", "jenkins", "github actions",
            "graphql", "grpc", "microservices",
        ]
        profile_skills_lower = {s.name.lower() for s in tech_skills}
        missing_from_offer: list[str] = []
        for kw in common_tech_keywords:
            if kw in offer_text and kw not in profile_skills_lower:
                missing_from_offer.append(kw)

        return score, matched, missing_from_offer

    # ── Experience Match ──────────────────────────────────────────────────────
    def _score_experience(self, offer_text: str, profile: ProfileData) -> float:
        """Evalúa match de experiencia laboral."""
        # Detectar años de experiencia pedidos
        years_patterns = [
            r'(\d+)\+?\s*(?:años|anios|years?)\s*(?:de\s+)?experiencia',
            r'experiencia\s*(?:de\s*)?(\d+)\+?\s*(?:años|anios|years?)',
            r'(\d+)\+?\s*(?:años|anios|years?)\s*(?:of\s+)?experience',
            r'al\s+menos\s+(\d+)\s*(?:años|anios)',
            r'mínimo\s+(\d+)\s*(?:años|anios)',
        ]

        required_years = 0
        for pattern in years_patterns:
            match = re.search(pattern, offer_text, re.IGNORECASE)
            if match:
                required_years = int(match.group(1))
                break

        # Calcular años del candidato
        candidate_years = 0
        for exp in profile.work_experience:
            if exp.start_date and exp.end_date:
                delta = exp.end_date - exp.start_date
                candidate_years += delta.days / 365.25
            elif exp.start_date and exp.is_current:
                from datetime import date
                delta = date.today() - exp.start_date
                candidate_years += delta.days / 365.25

        # Si la oferta es junior/trainee/práctica, la experiencia no importa tanto
        is_junior = any(w in offer_text for w in [
            "junior", "jr", "trainee", "practicante", "práctica",
            "recién egresado", "recien egresado", "entry level",
            "sin experiencia", "primer empleo",
        ])

        if is_junior:
            return 85.0  # Junior = bonus alto para recién titulados

        if required_years == 0:
            # No pide experiencia específica
            if candidate_years > 0:
                return 75.0
            return 60.0  # Sin experiencia pero tampoco la piden

        # Comparar años
        ratio = candidate_years / required_years if required_years > 0 else 1.0
        if ratio >= 1.0:
            return 95.0
        elif ratio >= 0.5:
            return 65.0
        elif ratio >= 0.25:
            return 40.0
        else:
            return 20.0

    # ── Education Match ───────────────────────────────────────────────────────
    def _score_education(self, offer_text: str, profile: ProfileData) -> float:
        """Evalúa match de formación académica."""
        if not profile.education:
            return 40.0

        # Detectar si la oferta pide título
        requires_degree = any(w in offer_text for w in [
            "título", "titulo", "titulado", "ingeniero", "ingeniería",
            "ingenieria", "licenciado", "licenciatura", "técnico", "tecnico",
            "degree", "bachelor", "carrera", "egresado", "profesional",
            "formación en", "formacion en", "estudios en",
        ])

        # Detectar campo relevante
        informatics_keywords = [
            "informática", "informatica", "computación", "computacion",
            "sistemas", "software", "programación", "programacion",
            "computer science", "informatics", "tecnología", "tecnologia",
            "datos", "data", "desarrollo", "ti", "tic",
        ]

        candidate_has_degree = len(profile.education) > 0
        candidate_field_match = any(
            any(kw in (edu.degree + " " + (edu.field or "")).lower() for kw in informatics_keywords)
            for edu in profile.education
        )

        if requires_degree:
            if candidate_has_degree and candidate_field_match:
                return 95.0
            elif candidate_has_degree:
                return 70.0
            else:
                return 30.0
        else:
            # No pide título explícitamente
            if candidate_has_degree:
                return 85.0
            return 60.0

    # ── Location Match ────────────────────────────────────────────────────────
    def _score_location(self, job_location: str | None, profile: ProfileData) -> float:
        """Evalúa match de ubicación."""
        if not job_location:
            return 70.0  # Sin info = neutro

        job_loc = job_location.lower()
        candidate_loc = (profile.personal_info.location or "").lower()

        # Remoto = siempre match perfecto
        if any(w in job_loc for w in ["remoto", "remote", "teletrabajo"]):
            return 100.0

        # Híbrido = buen match si misma ciudad
        if any(w in job_loc for w in ["híbrido", "hibrido", "hybrid"]):
            if self._same_city(job_loc, candidate_loc):
                return 95.0
            return 60.0

        # Presencial: verificar si misma ciudad
        if self._same_city(job_loc, candidate_loc):
            return 90.0

        # Misma región/país
        if "chile" in job_loc or "santiago" in candidate_loc:
            return 50.0

        return 30.0

    @staticmethod
    def _same_city(loc1: str, loc2: str) -> bool:
        """Verifica si dos ubicaciones están en la misma ciudad."""
        cities = [
            "santiago", "valparaíso", "valparaiso", "concepción", "concepcion",
            "viña del mar", "vina del mar", "temuco", "antofagasta",
            "la serena", "rancagua", "talca", "arica", "iquique",
            "puerto montt", "punta arenas", "osorno", "valdivia",
        ]
        for city in cities:
            if city in loc1 and city in loc2:
                return True
        return False

    # ── Salary Match ──────────────────────────────────────────────────────────
    def _score_salary(
        self,
        job_salary_min: int | None,
        job_salary_max: int | None,
    ) -> float:
        """Evalúa match salarial contra la preferencia mínima del config."""
        config_min = self._config.salary_min

        if not job_salary_min and not job_salary_max:
            return 70.0  # Sin info salarial = neutro

        if config_min == 0:
            return 80.0  # Sin filtro de sueldo = OK

        job_max = job_salary_max or job_salary_min or 0
        if job_max >= config_min:
            return 95.0
        elif job_max >= config_min * 0.8:
            return 70.0
        else:
            return 40.0
