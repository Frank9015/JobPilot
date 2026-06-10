"""
JobPilot — Database Engine
Conexión SQLAlchemy con pool de conexiones y sesión async-compatible.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from jobpilot.core.config import get_settings
from jobpilot.core.logger import get_logger

logger = get_logger("database")

# ── Engine ────────────────────────────────────────────────────────────────────
def build_engine():
    settings = get_settings()
    engine = create_engine(
        settings.database_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        echo=False,  # SQL detallado solo en logs de archivo, no en consola
    )

    # Verificar conexión al iniciar
    @event.listens_for(engine, "connect")
    def on_connect(dbapi_conn, conn_record):
        logger.debug("Nueva conexión a PostgreSQL establecida")

    return engine


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = build_engine()
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
        )
    return _SessionLocal


# ── Context manager de sesión ─────────────────────────────────────────────────
@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Context manager que provee una sesión de BD con commit/rollback automático.
    
    Uso:
        with get_session() as session:
            session.add(obj)
    """
    factory = get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── Inicialización de tablas ──────────────────────────────────────────────────
def init_db() -> None:
    """Crea todas las tablas si no existen. Usar en setup inicial."""
    from jobpilot.database.models import Base  # import tardío para evitar circular

    engine = get_engine()
    Base.metadata.create_all(engine)
    logger.info("Tablas de PostgreSQL verificadas/creadas OK")


def verify_connection() -> bool:
    """Verifica que la conexión a PostgreSQL funciona."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Conexión a PostgreSQL [green]OK[/green]")
        return True
    except Exception as e:
        logger.error(f"[red]Error de conexión a PostgreSQL[/red]: {e}")
        return False
