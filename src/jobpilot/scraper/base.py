"""
JobPilot — Base Scraper
Clase abstracta para todos los scrapers de portales laborales.
Cada portal concreto (LinkedIn, Bumeran, etc.) hereda de BaseScraper.
"""

from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from datetime import datetime

import httpx
from pydantic import BaseModel
from sqlalchemy.orm import Session

from jobpilot.core.config import get_config
from jobpilot.core.logger import get_logger
from jobpilot.database.models import AuditLog, JobOffer

logger = get_logger("scraper.base")


# ── Modelo de datos crudos del scraper ────────────────────────────────────────
class RawJobData(BaseModel):
    """Datos crudos extraídos de un portal antes de persistir en BD."""

    portal: str
    external_id: str | None = None
    url: str
    title: str
    company: str | None = None
    location: str | None = None
    modality: str | None = None  # remote, hybrid, onsite
    salary_min: int | None = None
    salary_max: int | None = None
    currency: str = "CLP"
    description: str | None = None
    requirements: str | None = None
    raw_html: str | None = None
    published_at: datetime | None = None


class ScrapeStats(BaseModel):
    """Estadísticas de un ciclo de scraping."""

    portal: str
    total_found: int = 0
    new_saved: int = 0
    duplicates_skipped: int = 0
    errors: int = 0
    elapsed_seconds: float = 0.0


# ── User-Agents para rotación ─────────────────────────────────────────────────
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]


# ── Clase base abstracta ─────────────────────────────────────────────────────
class BaseScraper(ABC):
    """
    Interfaz base para scrapers de portales laborales.

    Subclases deben implementar:
        - portal_name: nombre del portal (ej: 'linkedin')
        - search(): búsqueda de ofertas
        - get_job_detail(): extracción de detalle de una oferta
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._client: httpx.Client | None = None

    @property
    @abstractmethod
    def portal_name(self) -> str:
        """Nombre identificador del portal (ej: 'linkedin', 'bumeran')."""
        ...

    # ── HTTP Client ───────────────────────────────────────────────────────────
    def _get_client(self) -> httpx.Client:
        """Retorna un httpx.Client con User-Agent aleatorio y timeouts."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                headers={
                    "User-Agent": random.choice(_USER_AGENTS),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "es-CL,es;q=0.9,en;q=0.5",
                    "Accept-Encoding": "gzip, deflate, br",
                    "DNT": "1",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                },
                timeout=httpx.Timeout(self._config.action_timeout, connect=10.0),
                follow_redirects=True,
            )
        return self._client

    def close(self) -> None:
        """Cierra el cliente HTTP."""
        if self._client and not self._client.is_closed:
            self._client.close()
            self._client = None

    # ── Anti-detección ────────────────────────────────────────────────────────
    def _human_delay(self, factor: float = 1.0) -> None:
        """Espera un tiempo aleatorio entre requests para simular comportamiento humano."""
        delay = random.uniform(
            self._config.delay_min * factor,
            self._config.delay_max * factor,
        )
        time.sleep(delay)

    # ── Métodos abstractos ────────────────────────────────────────────────────
    @abstractmethod
    def search(
        self,
        keywords: list[str],
        location: str,
        max_results: int,
    ) -> list[RawJobData]:
        """
        Busca ofertas en el portal y retorna una lista de datos crudos.
        No persiste nada en BD — eso lo hace save_offers().
        """
        ...

    @abstractmethod
    def get_job_detail(self, url: str) -> RawJobData | None:
        """
        Navega a la URL de una oferta y extrae la descripción completa.
        Retorna None si la oferta ya no existe o hubo error.
        """
        ...

    # ── Persistencia en BD ────────────────────────────────────────────────────
    def save_offers(
        self,
        raw_jobs: list[RawJobData],
        session: Session,
    ) -> ScrapeStats:
        """
        Persiste ofertas crudas en la tabla job_offer.
        Detecta duplicados por (portal, external_id) y los ignora.
        Retorna estadísticas del proceso.
        """
        # Inicializar deduplicador
        from jobpilot.scraper.deduplicator import CrossPortalDeduplicator

        deduplicator = CrossPortalDeduplicator(session)

        stats = ScrapeStats(portal=self.portal_name, total_found=len(raw_jobs))

        for raw in raw_jobs:
            try:
                # Verificar duplicado usando el deduplicador cruzado
                if deduplicator.is_duplicate(
                    portal=self.portal_name,
                    external_id=raw.external_id,
                    title=raw.title,
                    company=raw.company,
                ):
                    stats.duplicates_skipped += 1
                    continue

                offer = JobOffer(
                    portal=self.portal_name,
                    external_id=raw.external_id,
                    url=raw.url,
                    title=raw.title,
                    company=raw.company,
                    location=raw.location,
                    modality=raw.modality,
                    salary_min=raw.salary_min,
                    salary_max=raw.salary_max,
                    currency=raw.currency,
                    description=raw.description,
                    requirements=raw.requirements,
                    raw_html=raw.raw_html,
                    published_at=raw.published_at,
                    status="new",
                )
                session.add(offer)
                session.flush()
                stats.new_saved += 1

                # Agregar al caché del deduplicador para evitar duplicados en la misma corrida
                deduplicator.add_to_cache(
                    portal=self.portal_name,
                    external_id=raw.external_id,
                    title=raw.title,
                    company=raw.company,
                )

            except Exception as e:
                logger.warning(f"Error guardando oferta '{raw.title}': {e}")
                stats.errors += 1

        # Registro de auditoría
        session.add(
            AuditLog(
                entity_type="scrape_cycle",
                action="scrape",
                status="success" if stats.errors == 0 else "partial",
                detail={
                    "portal": self.portal_name,
                    "found": stats.total_found,
                    "saved": stats.new_saved,
                    "duplicates": stats.duplicates_skipped,
                    "errors": stats.errors,
                },
            )
        )

        logger.info(
            f"[{self.portal_name}] Scrape completo: "
            f"{stats.new_saved} nuevas, "
            f"{stats.duplicates_skipped} duplicados, "
            f"{stats.errors} errores "
            f"(de {stats.total_found} encontradas)"
        )
        return stats
