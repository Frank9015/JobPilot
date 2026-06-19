"""
JobPilot Dashboard — Profile Router
Endpoints para perfil del candidato y upload de CV.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, UploadFile, File
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from jobpilot.core.config import get_config
from jobpilot.database.engine import get_session
from jobpilot.database.models import CandidateProfile

router = APIRouter()


@router.get("")
async def get_profile() -> dict[str, Any]:
    """Retorna el perfil activo del candidato con sus relaciones."""
    with get_session() as s:
        profile = s.scalar(
            select(CandidateProfile)
            .options(
                joinedload(CandidateProfile.skills),
                joinedload(CandidateProfile.education),
                joinedload(CandidateProfile.work_experience),
                joinedload(CandidateProfile.projects),
            )
            .order_by(CandidateProfile.created_at.desc())
            .limit(1)
        )
        if not profile:
            return {"exists": False}

        skills_list = [
            {"name": sk.name, "level": sk.level, "category": sk.category}
            for sk in (profile.skills or [])
        ]
        education_list = [
            {
                "institution": ed.institution,
                "degree": ed.degree,
                "field": ed.field,
                "start_date": ed.start_date.isoformat() if ed.start_date else None,
                "end_date": ed.end_date.isoformat() if ed.end_date else None,
            }
            for ed in (profile.education or [])
        ]
        experience_list = [
            {
                "company": exp.company,
                "role": exp.role,
                "start_date": exp.start_date.isoformat() if exp.start_date else None,
                "end_date": exp.end_date.isoformat() if exp.end_date else None,
                "is_current": exp.is_current,
                "description": exp.description,
            }
            for exp in (profile.work_experience or [])
        ]
        projects_list = [
            {
                "name": proj.name,
                "description": proj.description,
                "tech_stack": proj.tech_stack,
                "url": proj.url,
            }
            for proj in (profile.projects or [])
        ]

        return {
            "exists": True,
            "id": str(profile.id),
            "full_name": profile.full_name,
            "email": profile.email,
            "phone": profile.phone,
            "location": profile.location,
            "summary": profile.summary,
            "linkedin_url": profile.linkedin_url,
            "github_url": profile.github_url,
            "source_file": profile.cv_file_path,
            "created_at": (
                profile.created_at.isoformat() if profile.created_at else None
            ),
            "skills": skills_list,
            "education": education_list,
            "work_experience": experience_list,
            "projects": projects_list,
            "total_skills": len(skills_list),
            "total_experience": len(experience_list),
            "total_projects": len(projects_list),
        }


@router.post("/upload-cv")
async def upload_cv(file: UploadFile = File(...)) -> dict[str, Any]:
    """Upload de CV maestro (PDF). Guarda el archivo."""
    config = get_config()
    cv_dir = config.cv_master_dir
    cv_dir.mkdir(parents=True, exist_ok=True)

    dest = cv_dir / file.filename
    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)

    return {
        "success": True,
        "filename": file.filename,
        "path": str(dest),
        "size_kb": round(len(content) / 1024, 1),
        "message": f"CV guardado en {dest}. Ejecuta --setup para re-parsear.",
    }
