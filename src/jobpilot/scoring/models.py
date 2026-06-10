"""
JobPilot — Scoring Pydantic Models
Modelos de validación para el sistema de scoring de ofertas laborales.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ScoreResult(BaseModel):
    """Resultado del análisis de compatibilidad entre oferta y perfil."""
    total_score: float = Field(0.0, ge=0.0, le=100.0, description="Puntaje total ponderado (0-100)")
    skill_match: float = Field(0.0, ge=0.0, le=100.0, description="Match de habilidades técnicas")
    experience_match: float = Field(0.0, ge=0.0, le=100.0, description="Match de experiencia laboral")
    education_match: float = Field(0.0, ge=0.0, le=100.0, description="Match de formación académica")
    location_match: float = Field(0.0, ge=0.0, le=100.0, description="Match de ubicación/modalidad")
    salary_match: float = Field(0.0, ge=0.0, le=100.0, description="Match de rango salarial")

    reasoning: str = Field("", description="Explicación detallada del scoring")
    matched_skills: list[str] = Field(default_factory=list, description="Skills del perfil que coinciden")
    missing_skills: list[str] = Field(default_factory=list, description="Skills pedidos por la oferta que faltan")
    recommendation: str = Field("", description="Recomendación: Postular / No postular / Revisar")

    score_method: str = Field("gemini", description="Método usado: 'gemini' o 'heuristic'")
    tokens_used: int = Field(0, description="Tokens consumidos (0 si mock o heurístico)")
    cache_hit: bool = Field(False, description="Si el resultado vino del caché")


class ScoreRequest(BaseModel):
    """Datos de entrada para solicitar un scoring."""
    job_title: str
    job_company: str | None = None
    job_location: str | None = None
    job_description: str | None = None
    job_requirements: str | None = None
    profile_summary: str = Field(..., description="Resumen compacto del perfil (para el prompt)")
