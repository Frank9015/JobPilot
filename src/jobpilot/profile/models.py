"""
JobPilot — Profile Pydantic Models
Modelos de validación para el perfil del candidato.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class SkillLevel(str, Enum):
    BASIC = "basic"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class SkillCategory(str, Enum):
    LANGUAGE = "language"
    FRAMEWORK = "framework"
    TOOL = "tool"
    SOFT = "soft"
    OTHER = "other"


# ── Sub-modelos ───────────────────────────────────────────────────────────────
class SkillData(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    category: SkillCategory = SkillCategory.OTHER
    level: SkillLevel = SkillLevel.BASIC


class EducationData(BaseModel):
    institution: str = Field(..., min_length=1)
    degree: str = Field(..., min_length=1)
    field: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    gpa: float | None = Field(None, ge=1.0, le=7.0)


class WorkExperienceData(BaseModel):
    company: str = Field(..., min_length=1)
    role: str = Field(..., min_length=1)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = False
    description: str | None = None
    achievements: list[str] = Field(default_factory=list)


class ProjectData(BaseModel):
    name: str = Field(..., min_length=1)
    description: str | None = None
    tech_stack: list[str] = Field(default_factory=list)
    url: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class PersonalInfo(BaseModel):
    full_name: str = Field(..., min_length=2)
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    summary: str | None = None


# ── Modelo principal del perfil ───────────────────────────────────────────────
class ProfileData(BaseModel):
    """
    Representación completa del perfil del candidato.
    Este modelo es la fuente de verdad para scoring y generación de CV.
    """

    personal_info: PersonalInfo
    education: list[EducationData] = Field(default_factory=list)
    work_experience: list[WorkExperienceData] = Field(default_factory=list)
    skills: list[SkillData] = Field(default_factory=list)
    projects: list[ProjectData] = Field(default_factory=list)

    def skill_names(self) -> list[str]:
        """Retorna lista de nombres de habilidades (para comparación en scoring)."""
        return [s.name.lower() for s in self.skills]

    def skills_by_category(self, category: SkillCategory) -> list[SkillData]:
        return [s for s in self.skills if s.category == category]

    def to_scoring_summary(self) -> str:
        """
        Genera un resumen compacto del perfil para incluir en prompts de Gemini.
        Reduce tokens al máximo sin perder información relevante.
        """
        lines = [
            f"Candidato: {self.personal_info.full_name}",
            f"Ubicación: {self.personal_info.location or 'No especificada'}",
        ]

        if self.education:
            edu = self.education[0]
            lines.append(
                f"Educación: {edu.degree} en {edu.institution} ({edu.end_date or 'en curso'})"
            )

        if self.work_experience:
            lines.append("Experiencia laboral:")
            for exp in self.work_experience:
                period = f"{exp.start_date} – {'presente' if exp.is_current else exp.end_date}"
                lines.append(f"  - {exp.role} en {exp.company} ({period})")
        else:
            lines.append("Experiencia laboral: Sin experiencia formal")

        if self.skills:
            tech_skills = [
                s.name for s in self.skills if s.category != SkillCategory.SOFT
            ]
            soft_skills = [
                s.name for s in self.skills if s.category == SkillCategory.SOFT
            ]
            lines.append(f"Habilidades técnicas: {', '.join(tech_skills)}")
            if soft_skills:
                lines.append(f"Habilidades blandas: {', '.join(soft_skills)}")

        if self.projects:
            lines.append("Proyectos:")
            for proj in self.projects:
                stack = ", ".join(proj.tech_stack[:4]) if proj.tech_stack else "N/A"
                lines.append(f"  - {proj.name} ({stack})")

        return "\n".join(lines)


# ── Resultado del parseo ──────────────────────────────────────────────────────
class ParseResult(BaseModel):
    """Resultado del parseo del CV PDF."""

    success: bool
    profile: ProfileData | None = None
    raw_text: str = ""
    error: str | None = None
    tokens_used: int = 0
    mock_mode: bool = False
