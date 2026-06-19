"""
JobPilot — SENCE (BNE) Scraper
Scraper para la Bolsa Nacional de Empleo (bne.cl).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

from jobpilot.core.logger import get_logger
from jobpilot.scraper.base import BaseScraper, RawJobData

logger = get_logger("scraper.sence")


class SenceScraper(BaseScraper):
    """
    Scraper para la Bolsa Nacional de Empleo de Chile (bne.cl).
    """

    def __init__(self) -> None:
        super().__init__()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    @property
    def portal_name(self) -> str:
        return "sence"

    def _init_browser(self) -> None:
        if self._browser is not None:
            return

        logger.debug("[sence] Iniciando navegador Playwright para scraper")
        self._playwright = sync_playwright().start()
        
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox"]
        )
        self._context = self._browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            locale="es-CL",
        )
        self._page = self._context.new_page()

    def close(self) -> None:
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

    def search(
        self,
        keywords: list[str],
        location: str,
        max_results: int,
    ) -> list[RawJobData]:
        self._init_browser()
        raw_jobs = []

        for keyword in keywords:
            if len(raw_jobs) >= max_results:
                break
                
            query = keyword.replace(" ", "%20")
            url = f"https://www.bne.cl/ofertas?q={query}"
            
            logger.info(f"[sence] Buscando '{keyword}' -> {url}")
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
                self._human_delay(3.0)
                
                # BNE suele mostrar las ofertas en tarjetas
                # Usaremos un selector genérico para encontrar enlaces de ofertas
                job_cards = self._page.locator("a[href*='/oferta/']").all()

                for card in job_cards:
                    if len(raw_jobs) >= max_results:
                        break
                        
                    href = card.get_attribute("href")
                    if not href:
                        continue
                        
                    full_url = f"https://www.bne.cl{href}" if href.startswith("/") else href
                    
                    external_id = None
                    match = re.search(r"/oferta/(\d+)", full_url)
                    if match:
                        external_id = match.group(1)
                        
                    title_text = ""
                    company_text = "Confidencial (BNE)"
                    
                    try:
                        # Extraer título de la tarjeta
                        headers = card.locator("h2, h3, h4").all_inner_texts()
                        if headers:
                            title_text = headers[0].strip()
                        else:
                            all_texts = [t.strip() for t in card.inner_text().split('\n') if t.strip()]
                            if all_texts:
                                title_text = all_texts[0]
                    except Exception:
                        pass
                        
                    if not title_text:
                        continue
                        
                    raw_jobs.append(RawJobData(
                        portal=self.portal_name,
                        external_id=external_id,
                        url=full_url,
                        title=title_text,
                        company=company_text,
                        location=location,
                    ))
                    
            except Exception as e:
                logger.error(f"[sence] Error en búsqueda de '{keyword}': {e}")
                
            self._human_delay(1.5)

        logger.info(f"[sence] Encontradas {len(raw_jobs)} ofertas base.")
        return raw_jobs

    def get_job_detail(self, url: str) -> RawJobData | None:
        self._init_browser()
        
        logger.debug(f"[sence] Obteniendo detalle: {url}")
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
            self._human_delay(1.5)
            
            title = ""
            description = ""
            
            h1 = self._page.locator("h1, h2.title").first
            if h1.count() > 0:
                title = h1.inner_text()
                
            body = self._page.locator("body")
            description = body.inner_text()[:4000]
            raw_html = body.inner_html()[:10000]
                
            if not title:
                return None
                
            return RawJobData(
                portal=self.portal_name,
                url=url,
                title=title,
                company="Confidencial (BNE)",
                description=description,
                raw_html=raw_html,
                published_at=datetime.now(timezone.utc),
            )
            
        except Exception as e:
            logger.error(f"[sence] Error obteniendo detalle: {e}")
            return None
