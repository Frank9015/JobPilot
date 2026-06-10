"""
Alembic Environment Script
Lee DATABASE_URL desde .env para las migraciones.
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool
from dotenv import load_dotenv

# ── Cargar .env ───────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

# ── Path de src/ para imports ─────────────────────────────────────────────────
sys.path.insert(0, str(ROOT / "src"))

# ── Importar modelos para autogenerate ───────────────────────────────────────
from jobpilot.database.models import Base  # noqa: E402

# ── Configuración Alembic ─────────────────────────────────────────────────────
config = context.config
fileConfig(config.config_file_name)

# Sobreescribir URL desde variable de entorno
database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


# ── Modo offline (genera SQL sin conectarse) ──────────────────────────────────
def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Modo online (conecta a la BD real) ────────────────────────────────────────
def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
