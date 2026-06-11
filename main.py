"""
JobPilot — Entry Point
CLI principal del sistema. Ejecutar con: python main.py [comando]

Comandos:
  python main.py                   -> ciclo completo (scrape -> score -> CV -> apply dry-run)
  python main.py --setup           -> login manual en portales (abre browser visible)
  python main.py --scrape          -> solo scraping de ofertas
  python main.py --score           -> solo scoring de ofertas pendientes
  python main.py --generate-cv     -> genera CVs adaptados para ofertas elegibles
  python main.py --apply           -> postula a ofertas elegibles (dry-run por defecto)
  python main.py --apply --no-dry  -> postula REAL (envia postulaciones)
  python main.py --status          -> muestra estado actual del sistema
  python main.py --mock            -> fuerza modo mock de Gemini
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

# Forzar UTF-8 en la salida estándar de Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Asegurar que src/ está en el path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def print_banner() -> None:
    console.print(
        Panel.fit(
            "[bold blue]>> JobPilot[/bold blue] -- Automatizacion de Busqueda Laboral\n"
            "[dim]Chile | Python 3.13 | Gemini AI | Playwright[/dim]",
            border_style="blue",
        )
    )


def cmd_status() -> None:
    """Muestra el estado actual del sistema."""
    from jobpilot.core.config import get_config, get_settings
    from jobpilot.database.engine import verify_connection

    settings = get_settings()
    config = get_config()

    console.print("\n[bold]Estado del Sistema[/bold]\n")

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Parámetro", style="dim")
    table.add_column("Valor")

    table.add_row("Modo Gemini", "[yellow]MOCK[/yellow]" if settings.gemini_mock_mode else "[green]REAL[/green]")
    table.add_row("PostgreSQL", "[green]Conectado[/green]" if verify_connection() else "[red]Sin conexion[/red]")
    table.add_row("Portales activos", ", ".join(config.enabled_portals))
    table.add_row("Score minimo", f"{config.min_score_to_apply}%")
    table.add_row("Modo headful", "Si" if config.headful else "No")

    console.print(table)
    console.print()


def cmd_run(mock: bool = False) -> None:
    """Ejecuta el ciclo completo del sistema."""
    if mock:
        os.environ["GEMINI_MOCK_MODE"] = "true"
        console.print("[yellow]Modo MOCK activado -- Gemini no realizara llamadas reales[/yellow]")

    from jobpilot.core.config import get_settings
    settings = get_settings()

    if settings.gemini_mock_mode:
        console.print("[yellow]GEMINI_MOCK_MODE=true (configurado en .env)[/yellow]")

    console.print("\n[bold green]> Iniciando ciclo JobPilot...[/bold green]")

    # Pipeline completo: scrape -> score -> generate CV -> apply (dry-run)
    cmd_scrape()
    cmd_score()
    cmd_generate_cvs()
    cmd_apply(dry_run=True)

    # TODO (S4): from jobpilot.core.orchestrator import Orchestrator


def cmd_scrape() -> None:
    """Ejecuta el scraping de ofertas laborales en portales habilitados."""
    from jobpilot.core.logger import setup_logging
    from jobpilot.scraper.manager import ScraperManager

    setup_logging()
    console.print("\n[bold]Scraping de ofertas laborales[/bold]")

    manager = ScraperManager()
    available = manager.get_enabled_portals()
    if not available:
        console.print("[yellow]No hay portales habilitados con scraper implementado[/yellow]")
        return

    console.print(f"[dim]Portales: {', '.join(available)}[/dim]\n")

    stats_list = manager.run_scrape_cycle()

    # Tabla de resumen
    if stats_list:
        table = Table(title="Resumen de Scraping", show_header=True, header_style="bold cyan")
        table.add_column("Portal", style="bold")
        table.add_column("Encontradas", justify="right")
        table.add_column("Nuevas", justify="right", style="green")
        table.add_column("Duplicados", justify="right", style="yellow")
        table.add_column("Errores", justify="right", style="red")
        table.add_column("Tiempo", justify="right")

        for s in stats_list:
            table.add_row(
                s.portal.upper(),
                str(s.total_found),
                str(s.new_saved),
                str(s.duplicates_skipped),
                str(s.errors),
                f"{s.elapsed_seconds:.1f}s",
            )

        console.print(table)
        console.print()


def cmd_score() -> None:
    """Ejecuta scoring de ofertas pendientes contra el perfil del candidato."""
    from jobpilot.core.logger import setup_logging
    from jobpilot.database.engine import get_session
    from jobpilot.profile.repository import ProfileRepository
    from jobpilot.scoring.engine import ScoringEngine

    setup_logging()
    console.print("\n[bold]Scoring de ofertas pendientes[/bold]")

    with get_session() as session:
        # Cargar perfil
        repo = ProfileRepository(session)
        profile_data = repo.get_as_profile_data()
        if not profile_data:
            console.print("[red]No hay perfil cargado. Ejecuta --setup primero.[/red]")
            return

        console.print(f"[dim]Perfil: {profile_data.personal_info.full_name}[/dim]\n")

        # Ejecutar scoring
        engine = ScoringEngine(session)
        results = engine.score_pending_offers(profile_data)

        if not results:
            console.print("[yellow]No hay ofertas pendientes de scoring[/yellow]")
            return

        # Tabla de resultados
        from jobpilot.core.config import get_config
        config = get_config()

        table = Table(title="Resultados de Scoring", show_header=True, header_style="bold cyan")
        table.add_column("Oferta", max_width=35)
        table.add_column("Score", justify="right", style="bold")
        table.add_column("Skills", justify="right")
        table.add_column("Exp", justify="right")
        table.add_column("Edu", justify="right")
        table.add_column("Metodo", justify="center")
        table.add_column("Recomendacion", max_width=30)

        for r in results:
            score_style = (
                "green" if r.total_score >= config.min_score_to_apply
                else "yellow" if r.total_score >= config.min_score_to_apply - 10
                else "red"
            )
            table.add_row(
                r.reasoning[:35] if not hasattr(r, '_job_title') else "",
                f"[{score_style}]{r.total_score:.1f}%[/{score_style}]",
                f"{r.skill_match:.0f}",
                f"{r.experience_match:.0f}",
                f"{r.education_match:.0f}",
                r.score_method,
                r.recommendation[:30] if r.recommendation else "",
            )

        console.print(table)

        # Estadísticas de Gemini
        from jobpilot.core.token_guardian import TokenGuardian
        guardian = TokenGuardian(session)
        gemini_stats = guardian.get_daily_stats()
        console.print(
            f"\n[dim]Gemini hoy: {gemini_stats['flash_requests']}/{gemini_stats['flash_limit']} requests, "
            f"{gemini_stats['tokens_used']:,}/{gemini_stats['token_limit']:,} tokens, "
            f"{gemini_stats['cache_hits']} cache hits[/dim]"
        )
        console.print()


def cmd_generate_cvs() -> None:
    """Genera CVs adaptados para ofertas elegibles."""
    from jobpilot.core.logger import setup_logging
    from jobpilot.database.engine import get_session
    from jobpilot.profile.repository import ProfileRepository
    from jobpilot.cv.generator import CVGenerator
    from jobpilot.cv.renderer import CVRenderer
    from jobpilot.cv.repository import CVRepository
    from jobpilot.scoring.models import ScoreResult
    from sqlalchemy import select
    from jobpilot.database.models import JobOffer, JobScore, CandidateProfile

    setup_logging()
    console.print("\n[bold]Generacion de CVs adaptados[/bold]")

    with get_session() as session:
        repo = ProfileRepository(session)
        profile_data = repo.get_as_profile_data()
        if not profile_data:
            console.print("[red]No hay perfil cargado. Ejecuta --setup primero.[/red]")
            return

        from jobpilot.core.config import get_config
        config = get_config()

        # Ofertas elegibles (scored y score >= umbral)
        offers_with_scores = session.execute(
            select(JobOffer, JobScore)
            .outerjoin(JobScore, JobOffer.id == JobScore.job_offer_id)
            .where(
                JobOffer.status == "scored",
                JobScore.total_score >= config.min_score_to_apply,
            )
            .order_by(JobScore.total_score.desc())
        ).all()

        if not offers_with_scores:
            console.print("[yellow]No hay ofertas elegibles para generar CV[/yellow]")
            return

        console.print(f"[dim]{len(offers_with_scores)} ofertas elegibles (score >= {config.min_score_to_apply}%)[/dim]\n")

        generator = CVGenerator(session)
        renderer = CVRenderer()
        cv_repo = CVRepository(session)

        profile_orm = session.scalar(
            select(CandidateProfile).order_by(CandidateProfile.created_at.desc()).limit(1)
        )

        generated = 0
        for offer, score in offers_with_scores:
            # Verificar si ya existe
            existing = cv_repo.get_for_offer(offer.id)
            if existing and Path(existing.file_path).exists():
                console.print(f"  [dim]Ya existe:[/dim] {offer.title[:45]}")
                continue

            score_result = ScoreResult(
                total_score=float(score.total_score or 0),
                skill_match=float(score.skill_match or 0),
            ) if score else None

            adapted = generator.adapt_cv(profile_data, offer, score_result)

            safe_company = (offer.company or "unknown").replace(" ", "_")[:20]
            filename = f"cv_{safe_company}_{offer.id.hex[:8]}.pdf"
            filename = "".join(c for c in filename if c.isalnum() or c in "_-.").lower()
            output_path = config.cv_generated_dir / filename

            renderer.render(profile_data, adapted, output_path)

            if profile_orm:
                cv_repo.save(offer, profile_orm, adapted, output_path)

            offer.status = "cv_ready"
            session.flush()

            console.print(
                f"  [green]CV generado:[/green] {offer.title[:40]} "
                f"({adapted.adaptation_method})"
            )
            generated += 1

        console.print(f"\n[bold]{generated} CVs generados en {config.cv_generated_dir}[/bold]")


def cmd_apply(dry_run: bool = True) -> None:
    """Ejecuta postulacion automatica a ofertas elegibles."""
    from jobpilot.core.logger import setup_logging
    from jobpilot.database.engine import get_session
    from jobpilot.profile.repository import ProfileRepository
    from jobpilot.automation.manager import AutomationManager

    setup_logging()
    mode = "DRY-RUN" if dry_run else "REAL"
    console.print(f"\n[bold]Postulacion automatica [{mode}][/bold]")

    if not dry_run:
        console.print("[red bold]ATENCION: Modo REAL — se enviaran postulaciones reales.[/red bold]")
        confirm = input("  Escriba 'CONFIRMAR' para continuar: ")
        if confirm.strip() != "CONFIRMAR":
            console.print("[yellow]Cancelado.[/yellow]")
            return

    with get_session() as session:
        repo = ProfileRepository(session)
        profile_data = repo.get_as_profile_data()
        if not profile_data:
            console.print("[red]No hay perfil cargado.[/red]")
            return

        console.print(f"[dim]Perfil: {profile_data.personal_info.full_name}[/dim]\n")

        manager = AutomationManager(session)
        results = manager.run_apply_cycle(profile_data, dry_run=dry_run)

        if not results:
            console.print("[yellow]No hay ofertas elegibles para postular[/yellow]")
            return

        # Tabla de resultados
        table = Table(title=f"Resultados de Postulacion [{mode}]", show_header=True, header_style="bold cyan")
        table.add_column("Oferta", max_width=30)
        table.add_column("Empresa", max_width=15)
        table.add_column("Score", justify="right", width=7)
        table.add_column("Status", justify="center", width=12)
        table.add_column("Campos", justify="right", width=8)
        table.add_column("Mensaje", max_width=30)

        for r in results:
            status_style = {
                "applied": "green", "dry_run": "cyan",
                "failed": "red", "no_easy_apply": "yellow",
                "already_applied": "dim", "needs_human": "magenta",
            }.get(r["status"], "white")

            table.add_row(
                r.get("title", "?")[:30],
                (r.get("company") or "?")[:15],
                f"{r.get('score', 0):.0f}%",
                f"[{status_style}]{r['status']}[/{status_style}]",
                f"{r.get('fields_filled', 0)}/{r.get('fields_total', 0)}",
                (r.get("message") or "")[:30],
            )

        console.print(table)
        console.print()


def cmd_setup() -> None:
    """Setup inicial: login manual en cada portal con browser visible."""
    from jobpilot.core.logger import setup_logging
    from jobpilot.database.engine import get_session
    from jobpilot.automation.manager import AutomationManager

    setup_logging()
    console.print("\n[bold]Setup de Sesiones por Portal[/bold]")
    console.print("[dim]Se abrira un navegador por cada portal para que hagas login manualmente.[/dim]\n")

    with get_session() as session:
        manager = AutomationManager(session)
        results = manager.setup_all_sessions()

        console.print("\n[bold]Resultado del setup:[/bold]")
        for portal, success in results.items():
            status = "[green]OK[/green]" if success else "[red]FALLO[/red]"
            console.print(f"  {portal.upper()}: {status}")
        console.print()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="jobpilot",
        description="JobPilot -- Automatizacion de busqueda y postulacion laboral",
    )
    parser.add_argument("--setup", action="store_true", help="Login manual en portales (abre browser)")
    parser.add_argument("--mock", action="store_true", help="Forzar modo mock de Gemini")
    parser.add_argument("--scrape", action="store_true", help="Solo scraping de ofertas")
    parser.add_argument("--score", action="store_true", help="Solo scoring de ofertas pendientes")
    parser.add_argument("--generate-cv", action="store_true", help="Generar CVs adaptados")
    parser.add_argument("--apply", action="store_true", help="Postular a ofertas elegibles (dry-run)")
    parser.add_argument("--no-dry", action="store_true", help="Enviar postulaciones REALES (con --apply)")
    parser.add_argument("--status", action="store_true", help="Mostrar estado del sistema")

    args = parser.parse_args()

    print_banner()

    try:
        if args.status:
            cmd_status()
        elif args.setup:
            cmd_setup()
        elif args.scrape:
            cmd_scrape()
        elif args.score:
            cmd_score()
        elif args.generate_cv:
            cmd_generate_cvs()
        elif args.apply:
            cmd_apply(dry_run=not args.no_dry)
        else:
            cmd_run(mock=args.mock)
    except KeyboardInterrupt:
        console.print("\n[yellow]JobPilot detenido por el usuario.[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]Error critico: {e}[/red]")
        raise


if __name__ == "__main__":
    main()

