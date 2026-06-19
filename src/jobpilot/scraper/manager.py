"""
JobPilot — Scraper Manager
Orquesta la ejecución de scrapers de múltiples portales.
"""

from __future__ import annotations

import time


from jobpilot.core.config import get_config
from jobpilot.core.logger import get_logger
from jobpilot.database.engine import get_session
from jobpilot.database.models import AuditLog
from jobpilot.scraper.base import BaseScraper, ScrapeStats

logger = get_logger("scraper.manager")


# ── Registry de scrapers ──────────────────────────────────────────────────────
def _build_scraper_registry() -> dict[str, type[BaseScraper]]:
    """Construye el mapa de nombre_portal -> clase_scraper."""
    from jobpilot.scraper.linkedin import LinkedInScraper
    from jobpilot.scraper.bumeran import BumeranScraper
    from jobpilot.scraper.laborum import LaborumScraper
    from jobpilot.scraper.indeed import IndeedScraper
    from jobpilot.scraper.sence import SenceScraper

    return {
        "linkedin": LinkedInScraper,
        "bumeran": BumeranScraper,
        "laborum": LaborumScraper,
        "indeed": IndeedScraper,
        "sence": SenceScraper,
    }


class ScraperManager:
    """
    Gestiona la ejecución coordinada de scrapers de múltiples portales.

    Uso:
        manager = ScraperManager()
        results = manager.run_scrape_cycle()
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._registry = _build_scraper_registry()

    def run_scrape_cycle(self) -> list[ScrapeStats]:
        """
        Ejecuta un ciclo completo de scraping en todos los portales habilitados.
        Retorna lista de estadísticas por portal.
        """
        enabled = self._config.enabled_portals
        available = set(self._registry.keys())
        portals_to_run = [p for p in enabled if p in available]

        if not portals_to_run:
            logger.warning("No hay portales habilitados con scraper disponible")
            not_available = [p for p in enabled if p not in available]
            if not_available:
                logger.info(
                    f"Portales habilitados sin scraper implementado: {not_available}"
                )
            return []

        logger.info(
            f"Iniciando ciclo de scraping: {', '.join(portals_to_run)} "
            f"({self._config.max_results_per_portal} max/portal)"
        )

        all_stats: list[ScrapeStats] = []
        cycle_start = time.time()

        for portal_name in portals_to_run:
            stats = self._run_single_portal(portal_name)
            all_stats.append(stats)

        elapsed = time.time() - cycle_start

        # Resumen
        total_new = sum(s.new_saved for s in all_stats)
        total_dupes = sum(s.duplicates_skipped for s in all_stats)
        total_errors = sum(s.errors for s in all_stats)

        logger.info(
            f"Ciclo de scraping completo en {elapsed:.1f}s: "
            f"{total_new} nuevas, {total_dupes} duplicados, {total_errors} errores"
        )

        return all_stats

    def _run_single_portal(self, portal_name: str) -> ScrapeStats:
        """Ejecuta el scraper de un portal individual."""
        scraper_class = self._registry[portal_name]
        scraper = scraper_class()

        logger.info(f"--- Scraping [{portal_name.upper()}] ---")
        start_time = time.time()

        try:
            # 1. Buscar ofertas
            raw_jobs = scraper.search(
                keywords=self._config.search_keywords,
                location=self._config.search_location,
                max_results=self._config.max_results_per_portal,
            )

            if not raw_jobs:
                logger.info(f"[{portal_name}] Sin resultados de busqueda")
                return ScrapeStats(
                    portal=portal_name,
                    elapsed_seconds=time.time() - start_time,
                )

            # 2. Enriquecer con detalle (descripción completa)
            enriched = self._enrich_with_details(scraper, raw_jobs)

            # 3. Guardar en BD
            with get_session() as session:
                stats = scraper.save_offers(enriched, session)
                stats.elapsed_seconds = time.time() - start_time

            return stats

        except Exception as e:
            logger.error(f"[{portal_name}] Error en scraping: {e}")
            elapsed = time.time() - start_time
            # Registrar error en audit_log
            with get_session() as session:
                session.add(
                    AuditLog(
                        entity_type="scrape_cycle",
                        action="scrape",
                        status="error",
                        error=str(e),
                        detail={"portal": portal_name},
                    )
                )
            return ScrapeStats(
                portal=portal_name,
                errors=1,
                elapsed_seconds=elapsed,
            )
        finally:
            scraper.close()

    def _enrich_with_details(
        self,
        scraper: BaseScraper,
        raw_jobs: list,
        max_details: int = 10,
    ) -> list:
        """
        Enriquece las ofertas con la descripción completa.
        Solo enriquece las primeras max_details para evitar rate limiting.
        """
        enriched_count = 0

        for job in raw_jobs:
            # Solo enriquecer si no tiene descripción
            if job.description:
                continue
            if enriched_count >= max_details:
                break

            detail = scraper.get_job_detail(job.url)
            if detail and detail.description:
                job.description = detail.description
                job.requirements = detail.requirements or job.requirements
                job.modality = detail.modality or job.modality
                enriched_count += 1
                logger.debug(f"Detalle enriquecido: {job.title[:50]}")

        if enriched_count > 0:
            logger.info(
                f"Enriquecidas {enriched_count} ofertas con descripcion completa"
            )

        return raw_jobs

    # ── Utilidades ────────────────────────────────────────────────────────────
    def get_available_portals(self) -> list[str]:
        """Retorna portales con scraper implementado."""
        return list(self._registry.keys())

    def get_enabled_portals(self) -> list[str]:
        """Retorna portales habilitados en config que tienen scraper."""
        return [p for p in self._config.enabled_portals if p in self._registry]
