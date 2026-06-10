"""
JobPilot — LinkedIn Jobs Scraper
Extrae ofertas laborales de la búsqueda pública de LinkedIn Jobs.
No requiere autenticación — usa la vista pública de búsqueda.
"""
from __future__ import annotations

import re
import html as html_module
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlencode

import httpx

from jobpilot.core.logger import get_logger
from jobpilot.scraper.base import BaseScraper, RawJobData

logger = get_logger("scraper.linkedin")

# ── Constantes ────────────────────────────────────────────────────────────────
LINKEDIN_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LINKEDIN_JOB_DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
LINKEDIN_JOB_VIEW_URL = "https://www.linkedin.com/jobs/view/{job_id}"
RESULTS_PER_PAGE = 25


class LinkedInScraper(BaseScraper):
    """
    Scraper para LinkedIn Jobs usando la API pública guest.

    Estrategia:
    1. Usa el endpoint público de búsqueda (no requiere login).
    2. Parsea HTML de cada tarjeta de oferta para extraer datos básicos.
    3. Opcionalmente navega al detalle de cada oferta para la descripción completa.
    """

    @property
    def portal_name(self) -> str:
        return "linkedin"

    # ── Búsqueda de ofertas ───────────────────────────────────────────────────
    def search(
        self,
        keywords: list[str],
        location: str,
        max_results: int,
    ) -> list[RawJobData]:
        """
        Busca ofertas en LinkedIn Jobs con los keywords dados.
        Itera por cada keyword y acumula resultados sin duplicados.
        """
        all_jobs: dict[str, RawJobData] = {}  # external_id -> RawJobData
        client = self._get_client()

        for keyword in keywords:
            if len(all_jobs) >= max_results:
                break

            remaining = max_results - len(all_jobs)
            jobs = self._search_keyword(client, keyword, location, remaining)

            for job in jobs:
                if job.external_id and job.external_id not in all_jobs:
                    all_jobs[job.external_id] = job

            logger.info(
                f"Keyword '{keyword}': {len(jobs)} encontradas, "
                f"{len(all_jobs)} acumuladas (sin duplicados)"
            )

        results = list(all_jobs.values())[:max_results]
        logger.info(f"LinkedIn search completo: {len(results)} ofertas unicas")
        return results

    def _search_keyword(
        self,
        client: httpx.Client,
        keyword: str,
        location: str,
        max_results: int,
    ) -> list[RawJobData]:
        """Busca un keyword específico con paginación."""
        jobs: list[RawJobData] = []
        start = 0

        while len(jobs) < max_results:
            params = {
                "keywords": keyword,
                "location": location,
                "start": start,
                "sortBy": "DD",  # Date Descending (más recientes primero)
            }

            try:
                self._human_delay(factor=1.5)
                url = f"{LINKEDIN_SEARCH_URL}?{urlencode(params)}"
                logger.debug(f"Requesting: {url}")

                response = client.get(url)

                if response.status_code == 429:
                    logger.warning("LinkedIn rate limit (429). Deteniendo paginacion.")
                    break
                if response.status_code != 200:
                    logger.warning(f"LinkedIn HTTP {response.status_code} en start={start}")
                    break

                page_html = response.text
                if not page_html or len(page_html.strip()) < 100:
                    logger.debug(f"Pagina vacia en start={start}. Fin de resultados.")
                    break

                page_jobs = self._parse_search_results(page_html)
                if not page_jobs:
                    break

                jobs.extend(page_jobs)
                start += RESULTS_PER_PAGE

                logger.debug(f"Pagina start={start - RESULTS_PER_PAGE}: {len(page_jobs)} ofertas")

            except httpx.TimeoutException:
                logger.warning(f"Timeout en LinkedIn search start={start}")
                break
            except Exception as e:
                logger.error(f"Error en LinkedIn search: {e}")
                break

        return jobs[:max_results]

    # ── Parseo de resultados de búsqueda ──────────────────────────────────────
    def _parse_search_results(self, html: str) -> list[RawJobData]:
        """
        Parsea el HTML de la API de búsqueda de LinkedIn.
        Cada oferta viene como un <li> con clases específicas.
        """
        jobs: list[RawJobData] = []

        # Cada tarjeta de oferta está en un <div class="base-card ...">
        # Usamos regex para extraer datos ya que no tenemos BeautifulSoup
        card_pattern = re.compile(
            r'<div[^>]*class="[^"]*base-card[^"]*"[^>]*data-entity-urn="urn:li:jobPosting:(\d+)"[^>]*>(.*?)</div>\s*</li>',
            re.DOTALL,
        )

        # Fallback: buscar pattern alternativo para las tarjetas
        entity_pattern = re.compile(
            r'data-entity-urn="urn:li:jobPosting:(\d+)"',
        )
        title_pattern = re.compile(
            r'<span[^>]*class="sr-only"[^>]*>(.*?)</span>',
            re.DOTALL,
        )
        # Pattern más específico para título de la oferta
        title_link_pattern = re.compile(
            r'<a[^>]*class="[^"]*base-card__full-link[^"]*"[^>]*>\s*<span[^>]*class="sr-only"[^>]*>(.*?)</span>',
            re.DOTALL,
        )
        company_pattern = re.compile(
            r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>\s*(?:<a[^>]*>)?\s*(.*?)\s*(?:</a>)?\s*</h4>',
            re.DOTALL,
        )
        location_pattern = re.compile(
            r'<span[^>]*class="[^"]*job-search-card__location[^"]*"[^>]*>\s*(.*?)\s*</span>',
            re.DOTALL,
        )
        link_pattern = re.compile(
            r'<a[^>]*class="[^"]*base-card__full-link[^"]*"[^>]*href="([^"]*)"',
        )

        # Dividir por tarjetas usando el patrón de entidad
        # Buscar todos los bloques <li> que contengan data-entity-urn
        li_blocks = re.split(r'(?=<li\b)', html)

        for block in li_blocks:
            entity_match = entity_pattern.search(block)
            if not entity_match:
                continue

            job_id = entity_match.group(1)

            # Extraer título
            title = ""
            title_match = title_link_pattern.search(block)
            if title_match:
                title = self._clean_text(title_match.group(1))
            if not title:
                # Fallback: buscar el primer sr-only span
                title_fallback = title_pattern.search(block)
                if title_fallback:
                    title = self._clean_text(title_fallback.group(1))

            if not title:
                continue  # Sin título no sirve

            # Extraer empresa
            company = ""
            company_match = company_pattern.search(block)
            if company_match:
                company = self._clean_text(company_match.group(1))

            # Extraer ubicación
            location = ""
            location_match = location_pattern.search(block)
            if location_match:
                location = self._clean_text(location_match.group(1))

            # Extraer URL
            url = LINKEDIN_JOB_VIEW_URL.format(job_id=job_id)
            link_match = link_pattern.search(block)
            if link_match:
                raw_url = link_match.group(1).split("?")[0]  # Limpiar parámetros de tracking
                if raw_url.startswith("http"):
                    url = raw_url

            # Detectar modalidad de la ubicación
            modality = self._detect_modality(location, block)

            jobs.append(RawJobData(
                portal="linkedin",
                external_id=job_id,
                url=url,
                title=title,
                company=company or None,
                location=location or None,
                modality=modality,
            ))

        return jobs

    # ── Detalle de una oferta ─────────────────────────────────────────────────
    def get_job_detail(self, url: str) -> RawJobData | None:
        """
        Extrae la descripción completa de una oferta desde su URL individual.
        Usa el endpoint guest API de LinkedIn para obtener el detalle.
        """
        # Extraer job_id de la URL
        job_id_match = re.search(r'/jobs/view/(\d+)', url)
        if not job_id_match:
            # Intentar extraer de URL alternativas
            job_id_match = re.search(r'(\d{8,})', url)
        if not job_id_match:
            logger.warning(f"No se pudo extraer job_id de URL: {url}")
            return None

        job_id = job_id_match.group(1)
        detail_url = LINKEDIN_JOB_DETAIL_URL.format(job_id=job_id)

        try:
            self._human_delay(factor=2.0)
            client = self._get_client()
            response = client.get(detail_url)

            if response.status_code == 429:
                logger.warning("Rate limit en job detail. Saltando.")
                return None
            if response.status_code != 200:
                logger.warning(f"HTTP {response.status_code} para detalle de job {job_id}")
                return None

            html = response.text
            return self._parse_job_detail(html, job_id, url)

        except httpx.TimeoutException:
            logger.warning(f"Timeout obteniendo detalle de job {job_id}")
            return None
        except Exception as e:
            logger.error(f"Error obteniendo detalle de job {job_id}: {e}")
            return None

    def _parse_job_detail(self, html: str, job_id: str, url: str) -> RawJobData | None:
        """Parsea el HTML del detalle de una oferta de LinkedIn."""

        # Título
        title_match = re.search(
            r'<h2[^>]*class="[^"]*top-card-layout__title[^"]*"[^>]*>(.*?)</h2>',
            html, re.DOTALL,
        )
        title = self._clean_text(title_match.group(1)) if title_match else ""

        # Empresa
        company_match = re.search(
            r'<a[^>]*class="[^"]*topcard__org-name-link[^"]*"[^>]*>(.*?)</a>',
            html, re.DOTALL,
        )
        if not company_match:
            company_match = re.search(
                r'<span[^>]*class="[^"]*topcard__flavor[^"]*"[^>]*>(.*?)</span>',
                html, re.DOTALL,
            )
        company = self._clean_text(company_match.group(1)) if company_match else None

        # Ubicación
        location_match = re.search(
            r'<span[^>]*class="[^"]*topcard__flavor--bullet[^"]*"[^>]*>(.*?)</span>',
            html, re.DOTALL,
        )
        location = self._clean_text(location_match.group(1)) if location_match else None

        # Descripción completa
        desc_match = re.search(
            r'<div[^>]*class="[^"]*description__text[^"]*"[^>]*>(.*?)</div>\s*(?:</section>|<footer)',
            html, re.DOTALL,
        )
        if not desc_match:
            desc_match = re.search(
                r'<div[^>]*class="[^"]*show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>',
                html, re.DOTALL,
            )
        description = self._html_to_text(desc_match.group(1)) if desc_match else None

        # Criterios / requisitos (a veces aparecen como lista)
        criteria_matches = re.findall(
            r'<span[^>]*class="[^"]*description__job-criteria-text[^"]*"[^>]*>(.*?)</span>',
            html, re.DOTALL,
        )
        requirements = None
        if criteria_matches:
            requirements = " | ".join(self._clean_text(c) for c in criteria_matches)

        if not title:
            return None

        return RawJobData(
            portal="linkedin",
            external_id=job_id,
            url=url,
            title=title,
            company=company,
            location=location,
            modality=self._detect_modality(location or "", html),
            description=description,
            requirements=requirements,
            raw_html=html[:5000] if html else None,  # Guardar solo los primeros 5K chars
        )

    # ── Utilidades de parseo ──────────────────────────────────────────────────
    @staticmethod
    def _clean_text(text: str) -> str:
        """Limpia texto HTML: decodifica entidades, quita tags, normaliza espacios."""
        text = html_module.unescape(text)
        text = re.sub(r'<[^>]+>', '', text)    # Quitar tags HTML
        text = re.sub(r'\s+', ' ', text)       # Normalizar espacios
        return text.strip()

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Convierte HTML con formato a texto legible."""
        text = html
        text = re.sub(r'<br\s*/?>', '\n', text)
        text = re.sub(r'<li[^>]*>', '\n- ', text)
        text = re.sub(r'</?(ul|ol)[^>]*>', '\n', text)
        text = re.sub(r'</?(p|div)[^>]*>', '\n', text)
        text = re.sub(r'<[^>]+>', '', text)
        text = html_module.unescape(text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' +', ' ', text)
        return text.strip()

    @staticmethod
    def _detect_modality(location: str, context: str = "") -> str | None:
        """Detecta modalidad (remote/hybrid/onsite) del texto."""
        combined = f"{location} {context}".lower()
        if any(w in combined for w in ["remoto", "remote", "teletrabajo", "trabajo remoto"]):
            return "remote"
        if any(w in combined for w in ["híbrido", "hibrido", "hybrid"]):
            return "hybrid"
        if any(w in combined for w in ["presencial", "on-site", "onsite", "en oficina"]):
            return "onsite"
        return None
