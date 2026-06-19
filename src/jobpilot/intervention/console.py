"""
JobPilot — Console Notifier
Implementación de InterventionNotifier para la terminal.
Muestra alertas con Rich y acepta respuestas por input().
"""

from __future__ import annotations

import uuid

from rich.console import Console
from rich.panel import Panel

from jobpilot.core.logger import get_logger

logger = get_logger("intervention.console")
console = Console()


class ConsoleNotifier:
    """
    Notificador por consola usando Rich.
    Muestra la solicitud como un panel destacado y espera input del usuario.
    """

    _pending_answer: str | None = None
    _pending_id: uuid.UUID | None = None

    @property
    def channel_name(self) -> str:
        return "console"

    def notify(self, intervention) -> bool:
        """Muestra una alerta visual en la terminal."""
        reason_labels = {
            "captcha": "🔒 CAPTCHA detectado",
            "mfa": "🔐 Verificación MFA requerida",
            "unknown_question": "❓ Pregunta desconocida",
            "error": "⚠️ Error que requiere atención",
        }

        label = reason_labels.get(intervention.reason, f"🚨 {intervention.reason}")

        # Construir mensaje
        lines = [
            f"[bold red]{label}[/bold red]",
            "",
            f"[bold]Oferta:[/bold] {intervention.job_title}",
            f"[bold]Empresa:[/bold] {intervention.company}",
            f"[bold]Portal:[/bold] {intervention.portal.upper()}",
        ]

        if intervention.question:
            lines.append("")
            lines.append(
                f"[bold yellow]Pregunta:[/bold yellow] {intervention.question}"
            )

        if intervention.context:
            for k, v in intervention.context.items():
                lines.append(f"[dim]{k}: {v}[/dim]")

        content = "\n".join(lines)

        console.print()
        console.print(
            Panel(
                content,
                title="🚨 INTERVENCIÓN HUMANA REQUERIDA",
                border_style="bold red",
                padding=(1, 2),
            )
        )

        return True

    def wait_for_response(
        self,
        intervention_id: uuid.UUID,
        timeout_seconds: int,
        poll_interval: int,
    ) -> str | None:
        """
        Espera la respuesta del usuario por input().

        Para CAPTCHAs y MFA, el usuario resuelve manualmente en el browser
        y presiona Enter. Para preguntas, escribe la respuesta.
        """
        console.print(
            "\n[bold cyan]Opciones:[/bold cyan]\n"
            "  • Escribe tu respuesta y presiona Enter\n"
            "  • Escribe [bold]'skip'[/bold] para saltar esta oferta\n"
            "  • Escribe [bold]'done'[/bold] si ya resolviste el CAPTCHA/MFA en el browser\n"
            f"  • Timeout automático en {timeout_seconds}s\n"
        )

        try:
            # Usar un timeout simple con threading
            import threading

            result_holder: list[str | None] = [None]

            def _read_input():
                try:
                    answer = input("  >> Tu respuesta: ").strip()
                    result_holder[0] = answer if answer else None
                except EOFError:
                    result_holder[0] = None

            input_thread = threading.Thread(target=_read_input, daemon=True)
            input_thread.start()
            input_thread.join(timeout=timeout_seconds)

            answer = result_holder[0]

            if answer is None:
                console.print(
                    "[yellow]⏳ Timeout — saltando a la siguiente oferta[/yellow]\n"
                )
                return None

            if answer.lower() == "skip":
                console.print("[yellow]⏭️ Oferta saltada por el usuario[/yellow]\n")
                return None

            console.print(f"[green]✓ Respuesta recibida[/green]\n")
            return answer

        except KeyboardInterrupt:
            console.print("\n[yellow]Intervención cancelada por el usuario[/yellow]\n")
            return None
