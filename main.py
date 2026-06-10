"""
JobPilot — Entry Point
CLI principal del sistema. Ejecutar con: python main.py [comando]

Comandos:
  python main.py             → ejecuta ciclo completo (búsqueda → scoring → postulación)
  python main.py --setup     → configura sesiones de portales (login manual)
  python main.py --mock      → fuerza modo mock de Gemini (sin tokens reales)
  python main.py --scrape    → solo scraping, sin postular
  python main.py --score     → solo scoring de ofertas pendientes
  python main.py --status    → muestra estado actual del sistema
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

    # Fase 2: scraping + scoring
    cmd_scrape()
    cmd_score()

    # TODO (S4): from jobpilot.core.orchestrator import Orchestrator
    # TODO (S4): orchestrator.run()


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


def cmd_setup() -> None:
    """Setup inicial: login manual en cada portal y guardado de sesiones."""
    console.print("\n[bold]Setup de Sesiones por Portal[/bold]")
    console.print("[dim]Se abrira un navegador por cada portal para que hagas login manualmente.[/dim]\n")
    console.print("[yellow]Esta funcionalidad se implementara en la Fase 3.[/yellow]")
    # TODO (S3): implementar login manual + guardar session state


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="jobpilot",
        description="JobPilot -- Automatizacion de busqueda y postulacion laboral",
    )
    parser.add_argument("--setup", action="store_true", help="Configurar sesiones de portales (login manual)")
    parser.add_argument("--mock", action="store_true", help="Forzar modo mock de Gemini")
    parser.add_argument("--scrape", action="store_true", help="Solo scraping (sin postular)")
    parser.add_argument("--score", action="store_true", help="Solo scoring de ofertas pendientes")
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

