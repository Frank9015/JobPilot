"""
JobPilot — Profile Repository
CRUD para el perfil del candidato en PostgreSQL.
"""

from __future__ import annotations


from sqlalchemy.orm import Session
from sqlalchemy import select

from jobpilot.core.logger import get_logger
from jobpilot.database.models import (
    CandidateProfile,
    Education,
    Project,
    Skill,
    WorkExperience,
)
from jobpilot.profile.models import ProfileData

logger = get_logger("profile.repository")


class ProfileRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Obtener perfil activo ─────────────────────────────────────────────────
    def get_active(self) -> CandidateProfile | None:
        """Retorna el perfil más reciente, o None si no existe ninguno."""
        stmt = (
            select(CandidateProfile)
            .order_by(CandidateProfile.created_at.desc())
            .limit(1)
        )
        return self._session.scalar(stmt)

    def exists(self) -> bool:
        return self.get_active() is not None

    # ── Crear perfil desde ProfileData ───────────────────────────────────────
    def create_from_profile_data(
        self,
        data: ProfileData,
        cv_file_path: str | None = None,
    ) -> CandidateProfile:
        """
        Persiste un ProfileData completo en PostgreSQL.
        Borra el perfil anterior si existe (solo se mantiene uno activo).
        """
        # Eliminar perfil anterior si existe
        existing = self.get_active()
        if existing:
            logger.info(f"Reemplazando perfil anterior: {existing.full_name}")
            self._session.delete(existing)
            self._session.flush()

        # Crear nuevo perfil principal
        profile = CandidateProfile(
            full_name=data.personal_info.full_name,
            email=data.personal_info.email,
            phone=data.personal_info.phone,
            location=data.personal_info.location,
            summary=data.personal_info.summary,
            linkedin_url=data.personal_info.linkedin_url,
            github_url=data.personal_info.github_url,
            cv_file_path=cv_file_path,
        )
        self._session.add(profile)
        self._session.flush()  # obtener ID antes de agregar relaciones

        # Educación
        for edu in data.education:
            self._session.add(
                Education(
                    profile_id=profile.id,
                    institution=edu.institution,
                    degree=edu.degree,
                    field=edu.field,
                    start_date=edu.start_date,
                    end_date=edu.end_date,
                    gpa=edu.gpa,
                )
            )

        # Experiencia laboral
        for exp in data.work_experience:
            self._session.add(
                WorkExperience(
                    profile_id=profile.id,
                    company=exp.company,
                    role=exp.role,
                    start_date=exp.start_date,
                    end_date=exp.end_date,
                    is_current=exp.is_current,
                    description=exp.description,
                    achievements=exp.achievements or [],
                )
            )

        # Habilidades
        for skill in data.skills:
            self._session.add(
                Skill(
                    profile_id=profile.id,
                    name=skill.name,
                    category=skill.category,
                    level=skill.level,
                )
            )

        # Proyectos
        for proj in data.projects:
            self._session.add(
                Project(
                    profile_id=profile.id,
                    name=proj.name,
                    description=proj.description,
                    tech_stack=proj.tech_stack or [],
                    url=proj.url,
                    start_date=proj.start_date,
                    end_date=proj.end_date,
                )
            )

        self._session.flush()
        logger.info(
            f"Perfil guardado: {profile.full_name} | "
            f"{len(data.skills)} skills | "
            f"{len(data.education)} educación | "
            f"{len(data.projects)} proyectos | "
            f"{len(data.work_experience)} experiencias"
        )
        return profile

    # ── Leer perfil como ProfileData ─────────────────────────────────────────
    def get_as_profile_data(self) -> ProfileData | None:
        """Retorna el perfil activo como ProfileData Pydantic."""
        from jobpilot.profile.models import (
            PersonalInfo,
            EducationData,
            WorkExperienceData,
            SkillData,
            SkillCategory,
            SkillLevel,
            ProjectData,
        )

        profile = self.get_active()
        if not profile:
            return None

        personal_info = PersonalInfo(
            full_name=profile.full_name,
            email=profile.email,
            phone=profile.phone,
            location=profile.location,
            summary=profile.summary,
            linkedin_url=profile.linkedin_url,
            github_url=profile.github_url,
        )

        education = [
            EducationData(
                institution=e.institution,
                degree=e.degree,
                field=e.field,
                start_date=e.start_date,
                end_date=e.end_date,
                gpa=float(e.gpa) if e.gpa else None,
            )
            for e in profile.education
        ]

        work_experience = [
            WorkExperienceData(
                company=w.company,
                role=w.role,
                start_date=w.start_date,
                end_date=w.end_date,
                is_current=w.is_current,
                description=w.description,
                achievements=w.achievements or [],
            )
            for w in profile.work_experience
        ]

        skills = [
            SkillData(
                name=s.name,
                category=(
                    SkillCategory(s.category) if s.category else SkillCategory.OTHER
                ),
                level=SkillLevel(s.level) if s.level else SkillLevel.BASIC,
            )
            for s in profile.skills
        ]

        projects = [
            ProjectData(
                name=p.name,
                description=p.description,
                tech_stack=p.tech_stack or [],
                url=p.url,
                start_date=p.start_date,
                end_date=p.end_date,
            )
            for p in profile.projects
        ]

        return ProfileData(
            personal_info=personal_info,
            education=education,
            work_experience=work_experience,
            skills=skills,
            projects=projects,
        )
