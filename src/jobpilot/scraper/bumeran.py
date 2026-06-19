"""
JobPilot — Bumeran Scraper
Scraper basado en Playwright para evadir bloqueos de Cloudflare y DataDome.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

from playwright.sync_api import sync_playwright

from jobpilot.core.logger import get_logger
from jobpilot.scraper.base import BaseScraper, RawJobData

logger = get_logger("scraper.bumeran")


class BumeranScraper(BaseScraper):
    """
    Scraper para Bumeran Chile.
    Utiliza Playwright para navegación, ya que HTTP puro es bloqueado agresivamente.
    """

    def __init__(self) -> None:
        super().__init__()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    @property
    def portal_name(self) -> str:
        return "bumeran"

    # ── Playwright Lifecycle ──────────────────────────────────────────────────
    def _init_browser(self) -> None:
        """Inicializa Playwright si no está iniciado."""
        if self._browser is not None:
            return

        logger.debug("[bumeran] Iniciando navegador Playwright para scraper")
        self._playwright = sync_playwright().start()
        
        # Usamos chromium headful o headless dependiendo del entorno.
        # Bumeran suele detectar headless, así que usamos un contexto modificado.
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
        )
        self._context = self._browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            locale="es-CL",
        )
        self._page = self._context.new_page()
        
        # Ocultar webdriver
        self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

    def close(self) -> None:
        """Cierra el navegador y la sesión HTTP base si existiera."""
        super().close()
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None
        self._page = None

    # ── Extracción ────────────────────────────────────────────────────────────
    def search(
        self,
        keywords: list[str],
        location: str,
        max_results: int,
    ) -> list[RawJobData]:
        """Busca ofertas en Bumeran iterando sobre la grilla de resultados."""
        self._init_browser()
        raw_jobs = []

        for keyword in keywords:
            if len(raw_jobs) >= max_results:
                break
                
            query = keyword.replace(" ", "-")
            url = f"https://www.bumeran.cl/empleos-busqueda-{query}.html"
            
            logger.info(f"[bumeran] Buscando '{keyword}' -> {url}")
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
                self._human_delay(2.0)
                
                # Bumeran muestra una lista de tarjetas con clase que suele empezar con "JobCard" o "sc-"
                # Haremos un query general para anclas de empleo
                job_cards = self._page.locator("a[href*='/empleos/']").all()
                
                # Si hay data-dome, la página pedirá un captcha.
                if "DataDome" in self._page.title() or "Verificando" in self._page.title():
                    logger.warning("[bumeran] DataDome detectado. Bloqueo inminente.")
                    return raw_jobs

                # Extraer datos básicos
                # Las tarjetas suelen tener el título en h2 o h3 y la empresa en un div
                for card in job_cards:
                    if len(raw_jobs) >= max_results:
                        break
                        
                    href = card.get_attribute("href")
                    if not href or "/empleos/" not in href:
                        continue
                        
                    full_url = f"https://www.bumeran.cl{href}" if href.startswith("/") else href
                    
                    # Extraer ID del URL (termina en -111111.html)
                    external_id = None
                    match = re.search(r"-(\d+)\.html", full_url)
                    if match:
                        external_id = match.group(1)
                        
                    # Extraer título y empresa de la tarjeta
                    title_text = ""
                    company_text = ""
                    try:
                        all_texts = [line.strip() for line in card.inner_text().split('\n') if line.strip()]
                        ignore_prefixes = ("publicado", "actualizado", "nuevo", "destacado", "urgente")
                        valid_texts = [t for t in all_texts if not t.lower().startswith(ignore_prefixes)]
                        
                        if valid_texts:
                            title_text = valid_texts[0]
                            if len(valid_texts) > 1:
                                company_text = valid_texts[1]
                    except Exception:
                        pass
                        
                    if not title_text:
                        continue
                        
                    raw_jobs.append(RawJobData(
                        portal=self.portal_name,
                        external_id=external_id,
                        url=full_url,
                        title=title_text,
                        company=company_text if company_text else None,
                        location=location,
                    ))
                    
            except Exception as e:
                logger.error(f"[bumeran] Error en búsqueda de '{keyword}': {e}")
                
            self._human_delay(1.5)

        logger.info(f"[bumeran] Encontradas {len(raw_jobs)} ofertas base.")
        return raw_jobs

    def get_job_detail(self, url: str) -> RawJobData | None:
        """Navega a la oferta para extraer la descripción completa."""
        self._init_browser()
        
        logger.debug(f"[bumeran] Obteniendo detalle: {url}")
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
            self._human_delay(1.0)
            
            title = ""
            company = ""
            description = ""
            
            # Buscar el título principal
            h1 = self._page.locator("h1").first
            if h1.count() > 0:
                title = h1.inner_text()
                
            # Extraer la descripción (suele estar en un div con id o clase description)
            # En bumeran suele ser un elemento que contiene el texto de responsabilidades
            body = self._page.locator("body")
            raw_html = body.inner_html()
            
            # Extraemos todo el texto visible temporalmente
            full_text = body.inner_text()
            
            # TODO: Mejorar selectores específicos de Bumeran a medida que cambie el DOM.
            # Por ahora, extraemos todo el inner_text como descripción fallback si no hay un contenedor claro.
            desc_locator = self._page.locator("div[id*='descripcion'], div[class*='Description']")
            if desc_locator.count() > 0:
                description = desc_locator.first.inner_text()
            else:
                description = full_text[:4000]  # Fallback
                
            if not title:
                return None
                
            return RawJobData(
                portal=self.portal_name,
                url=url,
                title=title,
                company=company,
                description=description,
                raw_html=raw_html[:10000] if raw_html else None, # Limitar tamaño
                published_at=datetime.now(timezone.utc),
            )
            
        except Exception as e:
            logger.error(f"[bumeran] Error obteniendo detalle: {e}")
            return None
