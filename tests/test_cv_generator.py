"""
JobPilot — Test CV Generator E2E
Prueba la generacion de CV adaptado + renderizado PDF.
Usa las ofertas de test de la Semana 2 ya en BD.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

# Forzar UTF-8 en Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.panel import Panel

console = Console()


def run_test() -> None:
    from jobpilot.core.config import get_config, get_settings
    from jobpilot.core.logger import setup_logging
    from jobpilot.cv.generator import CVGenerator
    from jobpilot.cv.renderer import CVRenderer
    from jobpilot.cv.repository import CVRepository
    from jobpilot.database.engine import get_session
    from jobpilot.database.models import CandidateProfile, JobOffer, JobScore
    from jobpilot.profile.repository import ProfileRepository
    from jobpilot.scoring.models import ScoreResult
    from sqlalchemy import select

    setup_logging()
    settings = get_settings()
    config = get_config()

    console.print(Panel.fit(
        "[bold blue]Test E2E: CV Generator + Renderer[/bold blue]\n"
        f"[dim]Mock: {settings.gemini_mock_mode}[/dim]",
        border_style="blue",
    ))

    with get_session() as session:
        # 1. Cargar perfil
        repo = ProfileRepository(session)
        profile_data = repo.get_as_profile_data()
        if not profile_data:
            console.print("[red]No hay perfil en BD.[/red]")
            return

        console.print(f"Perfil: [bold]{profile_data.personal_info.full_name}[/bold]")

        # 2. Buscar una oferta con score alto
        result = session.execute(
            select(JobOffer, JobScore)
            .outerjoin(JobScore, JobOffer.id == JobScore.job_offer_id)
            .where(JobScore.total_score >= config.min_score_to_apply)
            .order_by(JobScore.total_score.desc())
            .limit(1)
        ).first()

        if not result:
            console.print("[yellow]No hay ofertas con score >= umbral. Usando la primera oferta disponible.[/yellow]")
            offer = session.scalar(select(JobOffer).limit(1))
            score = None
            if not offer:
                console.print("[red]No hay ofertas en BD. Ejecuta primero el test de scoring.[/red]")
                return
        else:
            offer, score = result

        console.print(f"Oferta: [bold]{offer.title}[/bold] ({offer.company})")
        if score:
            console.print(f"Score: {score.total_score:.1f}%")

        # 3. Generar CV adaptado
        console.print("\n[bold]Generando CV adaptado...[/bold]")
        generator = CVGenerator(session)

        score_result = ScoreResult(
            total_score=float(score.total_score or 0),
            skill_match=float(score.skill_match or 0),
            experience_match=float(score.experience_match or 0),
        ) if score else None

        adapted = generator.adapt_cv(profile_data, offer, score_result)

        console.print(f"  Metodo: {adapted.adaptation_method}")
        console.print(f"  Resumen: {adapted.adapted_summary[:80]}...")
        console.print(f"  Skills destacados: {', '.join(adapted.highlighted_skills[:6])}")
        console.print(f"  Orden secciones: {adapted.sections_order}")
        if adapted.reformulated_descriptions:
            console.print(f"  Descripciones reformuladas: {len(adapted.reformulated_descriptions)}")

        # 4. Renderizar PDF
        console.print("\n[bold]Renderizando PDF...[/bold]")
        renderer = CVRenderer()

        output_dir = config.cv_generated_dir
        pdf_path = output_dir / f"test_cv_{offer.id.hex[:8]}.pdf"
        html_path = output_dir / f"test_cv_{offer.id.hex[:8]}.html"

        # Preview HTML
        renderer.render_preview_html(profile_data, adapted, html_path)
        console.print(f"  HTML preview: {html_path}")

        # PDF
        rendered = renderer.render(profile_data, adapted, pdf_path)
        file_size_kb = rendered.stat().st_size / 1024
        console.print(f"  PDF generado: {rendered} ({file_size_kb:.1f} KB)")

        # 5. Verificaciones
        console.print("\n[bold]Verificaciones:[/bold]")

        # PDF existe y tiene tamano razonable
        assert pdf_path.exists(), "PDF no existe"
        assert file_size_kb > 5, f"PDF demasiado pequeno: {file_size_kb} KB"
        console.print(f"  [green]PDF existe y tiene {file_size_kb:.1f} KB[/green]")

        # HTML existe
        assert html_path.exists(), "HTML no existe"
        html_content = html_path.read_text(encoding="utf-8")
        assert profile_data.personal_info.full_name in html_content, "Nombre no encontrado en HTML"
        console.print(f"  [green]HTML contiene el nombre del candidato[/green]")

        # Guardar en BD
        profile_orm = session.scalar(
            select(CandidateProfile).order_by(CandidateProfile.created_at.desc()).limit(1)
        )
        if profile_orm:
            cv_repo = CVRepository(session)
            cv_orm = cv_repo.save(offer, profile_orm, adapted, pdf_path)
            console.print(f"  [green]CV guardado en BD: {cv_orm.id}[/green]")

        console.print(f"\n[bold green]Test E2E CV Generator completado.[/bold green]")
        console.print(f"[dim]Abre el PDF para verificar visualmente: {pdf_path}[/dim]")


if __name__ == "__main__":
    run_test()
