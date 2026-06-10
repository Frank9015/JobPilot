"""
JobPilot — Structured Logger
Logging estructurado con Rich para consola y archivo de log en disco.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from jobpilot.core.config import get_config

# ── Consola Rich ──────────────────────────────────────────────────────────────
console = Console()

# ── Logger principal ──────────────────────────────────────────────────────────
def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configura el logger raíz de JobPilot con Rich + archivo."""
    config = get_config()
    logs_dir: Path = config.logs_dir
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "jobpilot.log"

    log_level = getattr(logging, level.upper(), logging.INFO)

    # Handler de consola con Rich (colores, formato limpio)
    rich_handler = RichHandler(
        console=console,
        rich_tracebacks=True,
        show_time=True,
        show_path=False,
        markup=True,
    )
    rich_handler.setLevel(log_level)

    # Handler de archivo (texto plano para persistencia)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)  # archivo captura todo
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root_logger = logging.getLogger("jobpilot")
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()
    root_logger.addHandler(rich_handler)
    root_logger.addHandler(file_handler)
    root_logger.propagate = False

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Retorna un logger hijo del logger raíz de JobPilot."""
    return logging.getLogger(f"jobpilot.{name}")
