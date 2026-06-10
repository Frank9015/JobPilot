"""
JobPilot — Test Scoring E2E
Prueba end-to-end del pipeline scraping + scoring.

Modo 1 (default): Inserta 5 ofertas hardcoded realistas y ejecuta scoring.
Modo 2 (--live):  Scrapea ofertas reales de LinkedIn y ejecuta scoring.

Uso:
    python tests/test_scoring.py           # Mock/heurístico con ofertas hardcoded
    python tests/test_scoring.py --live    # Scrape real + scoring real con Gemini
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

# Forzar UTF-8 en Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Asegurar path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


# ── 5 ofertas laborales realistas de Chile ────────────────────────────────────
SAMPLE_OFFERS = [
    {
        "portal": "linkedin",
        "external_id": "test_001",
        "url": "https://www.linkedin.com/jobs/view/test001",
        "title": "Desarrollador Backend Junior - Python",
        "company": "Falabella Tecnologia",
        "location": "Santiago, Chile",
        "modality": "hybrid",
        "description": (
            "Buscamos un Desarrollador Backend Junior con conocimientos en Python y "
            "Django o FastAPI. El candidato ideal tiene formacion en informatica o "
            "ingenieria en computacion. Trabajara en el equipo de desarrollo de "
            "microservicios REST para nuestro e-commerce. Requisitos: Python, SQL, "
            "Git, APIs REST. Deseable: Docker, PostgreSQL, conocimiento basico de "
            "cloud (AWS o GCP). Ofrecemos modalidad hibrida, horario flexible y "
            "plan de carrera."
        ),
        "requirements": "Python, SQL, Git, APIs REST, Django o FastAPI. Deseable: Docker, PostgreSQL.",
    },
    {
        "portal": "linkedin",
        "external_id": "test_002",
        "url": "https://www.linkedin.com/jobs/view/test002",
        "title": "Ingeniero de Software Full Stack",
        "company": "Mercado Libre Chile",
        "location": "Santiago, Chile",
        "modality": "remote",
        "description": (
            "Estamos buscando un Ingeniero de Software Full Stack con al menos 3 anios "
            "de experiencia profesional. Stack: React, Node.js, Java o Go en el backend. "
            "Base de datos: MySQL, DynamoDB. Infraestructura en AWS. Se requiere experiencia "
            "con CI/CD, Docker, Kubernetes y arquitectura de microservicios. El candidato "
            "debe tener titulo universitario en Ingenieria en Informatica o similar."
        ),
        "requirements": "3+ anios experiencia. React, Node.js, Java/Go, AWS, Docker, Kubernetes, CI/CD.",
    },
    {
        "portal": "linkedin",
        "external_id": "test_003",
        "url": "https://www.linkedin.com/jobs/view/test003",
        "title": "Practicante Desarrollo Web - React",
        "company": "Banco de Chile",
        "location": "Santiago, Chile",
        "modality": "onsite",
        "description": (
            "Practica profesional para estudiantes o recien egresados de Ingenieria en "
            "Informatica. Participaras en el desarrollo de aplicaciones web internas "
            "usando React, JavaScript/TypeScript y APIs REST. Conocimientos deseables: "
            "Node.js, Git, HTML, CSS. No se requiere experiencia previa. Ofrecemos "
            "mentorias con ingenieros senior y posibilidad de contratacion al finalizar."
        ),
        "requirements": "Estudiante o recien egresado de Informatica. React, JavaScript, HTML, CSS, Git.",
    },
    {
        "portal": "linkedin",
        "external_id": "test_004",
        "url": "https://www.linkedin.com/jobs/view/test004",
        "title": "Data Analyst Junior",
        "company": "Cencosud",
        "location": "Santiago, Chile",
        "modality": "hybrid",
        "description": (
            "Buscamos Data Analyst Junior para el area de Business Intelligence. "
            "El candidato trabajara con Python (pandas, matplotlib), SQL y herramientas "
            "de visualizacion como Power BI o Tableau. Se requiere formacion en "
            "Informatica, Estadistica o Ingenieria. Deseable: experiencia con Excel "
            "avanzado y bases de datos relacionales (PostgreSQL, MySQL)."
        ),
        "requirements": "Python, pandas, SQL, Power BI/Tableau. Deseable: PostgreSQL, Excel avanzado.",
    },
    {
        "portal": "linkedin",
        "external_id": "test_005",
        "url": "https://www.linkedin.com/jobs/view/test005",
        "title": "DevOps Engineer Senior",
        "company": "Globant Chile",
        "location": "Remoto, Chile",
        "modality": "remote",
        "description": (
            "Buscamos DevOps Engineer Senior con 5+ anios de experiencia en la gestion "
            "de infraestructura cloud. Stack requerido: AWS o GCP, Terraform, Ansible, "
            "Docker, Kubernetes, Jenkins o GitHub Actions. Experiencia con Linux, "
            "scripting en Bash/Python, monitoreo con Prometheus/Grafana. Se requiere "
            "titulo en Ingenieria en Informatica y certificaciones cloud vigentes."
        ),
        "requirements": "5+ anios. AWS/GCP, Terraform, Docker, Kubernetes, Jenkins, Linux, Bash.",
    },
]


def insert_sample_offers(session) -> list:
    """Inserta las ofertas de prueba en la BD. Retorna las ofertas insertadas."""
    from sqlalchemy import select
    from jobpilot.database.models import JobOffer

    inserted = []
    for data in SAMPLE_OFFERS:
        # Verificar si ya existe
        existing = session.scalar(
            select(JobOffer).where(
                JobOffer.portal == data["portal"],
                JobOffer.external_id == data["external_id"],
            )
        )
        if existing:
            # Resetear status para re-scoring
            existing.status = "new"
            inserted.append(existing)
            continue

        offer = JobOffer(
            portal=data["portal"],
            external_id=data["external_id"],
            url=data["url"],
            title=data["title"],
            company=data.get("company"),
            location=data.get("location"),
            modality=data.get("modality"),
            description=data.get("description"),
            requirements=data.get("requirements"),
            status="new",
        )
        session.add(offer)
        session.flush()
        inserted.append(offer)

    return inserted


def run_test(live: bool = False) -> None:
    """Ejecuta el test E2E de scoring."""
    from jobpilot.core.config import get_config, get_settings
    from jobpilot.core.logger import setup_logging
    from jobpilot.core.token_guardian import TokenGuardian
    from jobpilot.database.engine import get_session
    from jobpilot.profile.repository import ProfileRepository
    from jobpilot.scoring.engine import ScoringEngine

    setup_logging()
    settings = get_settings()
    config = get_config()

    console.print(Panel.fit(
        "[bold blue]Test E2E: Scraping + Scoring[/bold blue]\n"
        f"[dim]Modo: {'LIVE (Gemini real)' if not settings.gemini_mock_mode else 'MOCK'}[/dim]",
        border_style="blue",
    ))

    with get_session() as session:
        # 1. Cargar perfil
        repo = ProfileRepository(session)
        profile_data = repo.get_as_profile_data()
        if not profile_data:
            console.print("[red]ERROR: No hay perfil en BD. Ejecuta 'python main.py --setup' primero.[/red]")
            return

        console.print(f"Perfil cargado: [bold]{profile_data.personal_info.full_name}[/bold]")
        console.print(f"Skills: {len(profile_data.skills)} | Proyectos: {len(profile_data.projects)}\n")

        # 2. Insertar ofertas
        if live:
            console.print("[bold]Modo LIVE: Scrapeando ofertas reales de LinkedIn...[/bold]")
            from jobpilot.scraper.linkedin import LinkedInScraper
            scraper = LinkedInScraper()
            try:
                raw_jobs = scraper.search(
                    keywords=config.search_keywords[:1],  # Solo primer keyword para el test
                    location=config.search_location,
                    max_results=5,
                )
                if raw_jobs:
                    # Enriquecer con detalles
                    for job in raw_jobs[:3]:  # Solo 3 detalles para limitar rate
                        detail = scraper.get_job_detail(job.url)
                        if detail and detail.description:
                            job.description = detail.description
                            job.requirements = detail.requirements

                    from jobpilot.scraper.base import BaseScraper
                    stats = scraper.save_offers(raw_jobs, session)
                    console.print(
                        f"Scrape: {stats.new_saved} nuevas, "
                        f"{stats.duplicates_skipped} duplicados\n"
                    )
                else:
                    console.print("[yellow]Sin resultados de LinkedIn. Usando ofertas hardcoded.[/yellow]")
                    insert_sample_offers(session)
            finally:
                scraper.close()
        else:
            console.print("Insertando 5 ofertas de prueba hardcoded...")
            offers = insert_sample_offers(session)
            console.print(f"[green]{len(offers)} ofertas listas para scoring[/green]\n")

        # 3. Ejecutar scoring
        engine = ScoringEngine(session)
        results = engine.score_pending_offers(profile_data)

        if not results:
            console.print("[yellow]No hubo ofertas pendientes de scoring.[/yellow]")
            return

        # 4. Tabla de resultados
        table = Table(
            title="Resultados de Scoring",
            show_header=True,
            header_style="bold cyan",
            show_lines=True,
        )
        table.add_column("#", justify="right", style="dim", width=3)
        table.add_column("Oferta", max_width=30)
        table.add_column("Empresa", max_width=18)
        table.add_column("Score", justify="right", style="bold", width=8)
        table.add_column("Skills", justify="right", width=7)
        table.add_column("Exp", justify="right", width=5)
        table.add_column("Edu", justify="right", width=5)
        table.add_column("Loc", justify="right", width=5)
        table.add_column("Metodo", justify="center", width=10)

        # Necesitamos los títulos de las ofertas — obtenerlos via job_score
        from sqlalchemy import select as sq
        from jobpilot.database.models import JobScore as JS, JobOffer as JO

        # Obtener los scores más recientes con sus ofertas
        recent_scores = session.scalars(
            sq(JS).order_by(JS.scored_at.desc()).limit(len(results))
        ).all()

        # Mapear offer_id → offer para lookup
        score_offer_pairs = []
        for js in reversed(recent_scores):  # revertir para mantener orden de procesamiento
            offer = session.get(JO, js.job_offer_id)
            if offer:
                score_offer_pairs.append(offer)

        # Usar las ofertas mapeadas (o results si no hay suficientes)
        display_offers = score_offer_pairs if len(score_offer_pairs) == len(results) else [None] * len(results)

        for i, result in enumerate(results):
            offer = display_offers[i] if i < len(display_offers) else None
            offer_title = (offer.title[:30] if offer else "?")
            offer_company = ((offer.company or "?")[:18] if offer else "?")
            score_style = (
                "green" if result.total_score >= config.min_score_to_apply
                else "yellow" if result.total_score >= config.min_score_to_apply - 10
                else "red"
            )
            table.add_row(
                str(i + 1),
                offer_title,
                offer_company,
                f"[{score_style}]{result.total_score:.1f}%[/{score_style}]",
                f"{result.skill_match:.0f}",
                f"{result.experience_match:.0f}",
                f"{result.education_match:.0f}",
                f"{result.location_match:.0f}",
                result.score_method,
            )

        console.print(table)

        # 5. Recomendaciones
        console.print("\n[bold]Recomendaciones:[/bold]")
        for i, result in enumerate(results, 1):
            icon = "[green]>>[/green]" if result.total_score >= config.min_score_to_apply else "[red]x[/red]"
            console.print(f"  {icon} {result.recommendation}")

        # 6. Verificar gemini_cache y gemini_usage_log
        console.print("\n[bold]Verificacion de BD:[/bold]")

        from jobpilot.database.models import GeminiCache, GeminiUsageLog
        from sqlalchemy import func

        cache_count = session.scalar(
            sq(func.count()).select_from(GeminiCache)
        )
        usage_count = session.scalar(
            sq(func.count()).select_from(GeminiUsageLog)
        )

        console.print(f"  gemini_cache:     {cache_count} entradas")
        console.print(f"  gemini_usage_log: {usage_count} registros")

        # Estadísticas del guardián
        guardian = TokenGuardian(session)
        stats = guardian.get_daily_stats()
        console.print(
            f"\n  Gemini hoy: {stats['flash_requests']}/{stats['flash_limit']} requests, "
            f"{stats['tokens_used']:,}/{stats['token_limit']:,} tokens"
        )
        if stats['cache_hits'] > 0:
            console.print(f"  Cache hits: {stats['cache_hits']} ({stats['tokens_saved']:,} tokens ahorrados)")

        console.print("\n[bold green]Test E2E completado.[/bold green]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test E2E de scoring")
    parser.add_argument("--live", action="store_true", help="Usar LinkedIn real en vez de ofertas hardcoded")
    args = parser.parse_args()

    run_test(live=args.live)
