"""
Script de prueba: parseo del CV maestro real con Gemini Pro.
Ejecutar con: python tests/test_parse_cv.py
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jobpilot.core.config import get_settings, get_config
from jobpilot.profile.parser import parse_cv
from jobpilot.database.engine import get_session, init_db
from jobpilot.profile.repository import ProfileRepository

CV_PATH = Path(__file__).parent.parent / "data" / "cv_master" / "Franco_Borotto_CV_ES.pdf"

def main():
    settings = get_settings()
    print(f"\n=== MODO: {'MOCK' if settings.gemini_mock_mode else 'REAL (Gemini Pro)'} ===\n")

    # Parsear
    print(f"Parseando: {CV_PATH.name}")
    result = parse_cv(CV_PATH)

    if not result.success:
        print(f"ERROR: {result.error}")
        sys.exit(1)

    profile = result.profile
    print(f"\n--- DATOS EXTRAIDOS ---")
    print(f"Nombre:    {profile.personal_info.full_name}")
    print(f"Email:     {profile.personal_info.email}")
    print(f"Ubicacion: {profile.personal_info.location}")
    print(f"LinkedIn:  {profile.personal_info.linkedin_url}")
    print(f"GitHub:    {profile.personal_info.github_url}")

    print(f"\nEducacion ({len(profile.education)}):")
    for e in profile.education:
        print(f"  - {e.degree} en {e.institution} ({e.end_date or 'en curso'})")

    print(f"\nExperiencia ({len(profile.work_experience)}):")
    for w in profile.work_experience:
        period = f"{w.start_date} - {'presente' if w.is_current else w.end_date}"
        print(f"  - {w.role} @ {w.company} ({period})")

    print(f"\nHabilidades ({len(profile.skills)}):")
    for s in profile.skills:
        print(f"  - {s.name} [{s.category}] ({s.level})")

    print(f"\nProyectos ({len(profile.projects)}):")
    for p in profile.projects:
        stack = ', '.join(p.tech_stack[:5]) if p.tech_stack else 'N/A'
        print(f"  - {p.name} | {stack}")

    if not settings.gemini_mock_mode:
        print(f"\nTokens usados: {result.tokens_used:,}")

    # Guardar en BD
    print(f"\n--- GUARDANDO EN POSTGRESQL ---")
    with get_session() as session:
        repo = ProfileRepository(session)
        db_profile = repo.create_from_profile_data(
            profile,
            cv_file_path=str(CV_PATH),
        )
        print(f"Perfil guardado con ID: {db_profile.id}")

    print(f"\n Parseo y guardado completados exitosamente!")

    # Resumen de scoring
    print(f"\n--- RESUMEN PARA SCORING (compact) ---")
    print(profile.to_scoring_summary())

if __name__ == "__main__":
    main()
