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
        console.print("[yellow]⚠ Modo MOCK activado — Gemini no realizará llamadas reales[/yellow]")

    from jobpilot.core.config import get_settings
    settings = get_settings()

    if settings.gemini_mock_mode:
        console.print("[yellow]ℹ GEMINI_MOCK_MODE=true (configurado en .env)[/yellow]")

    console.print("\n[bold green]▶ Iniciando ciclo JobPilot...[/bold green]")
    console.print("[dim]El orquestador se implementará en la Semana 4 del MVP[/dim]")

    # TODO (S4): from jobpilot.core.orchestrator import Orchestrator
    # TODO (S4): orchestrator = Orchestrator()
    # TODO (S4): orchestrator.run()


def cmd_setup() -> None:
    """Setup inicial: login manual en cada portal y guardado de sesiones."""
    console.print("\n[bold]⚙ Setup de Sesiones por Portal[/bold]")
    console.print("[dim]Se abrirá un navegador por cada portal para que hagas login manualmente.[/dim]\n")
    console.print("[yellow]Esta funcionalidad se implementará en la Semana 1 del MVP.[/yellow]")
    # TODO (S1): implementar login manual + guardar session state


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="jobpilot",
        description="JobPilot — Automatización de búsqueda y postulación laboral",
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
        else:
            cmd_run(mock=args.mock)
    except KeyboardInterrupt:
        console.print("\n[yellow]⏹ JobPilot detenido por el usuario.[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]✗ Error crítico: {e}[/red]")
        raise


if __name__ == "__main__":
    main()
