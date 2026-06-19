"""
JobPilot — Indeed Scraper
Scraper basado en Playwright para Indeed Chile.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

from jobpilot.core.logger import get_logger
from jobpilot.scraper.base import BaseScraper, RawJobData

logger = get_logger("scraper.indeed")


class IndeedScraper(BaseScraper):
    """
    Scraper para Indeed Chile.
    Utiliza Playwright para evadir los fuertes bloqueos de Cloudflare.
    """

    def __init__(self) -> None:
        super().__init__()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    @property
    def portal_name(self) -> str:
        return "indeed"

    def _init_browser(self) -> None:
        if self._browser is not None:
            return

        logger.debug("[indeed] Iniciando navegador Playwright para scraper")
        self._playwright = sync_playwright().start()
        
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
        self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

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
                
            # Formato de búsqueda de Indeed: ?q=palabra+clave&l=ubicacion
            query = keyword.replace(" ", "+")
            loc_query = location.replace(" ", "+")
            url = f"https://cl.indeed.com/jobs?q={query}&l={loc_query}"
            
            logger.info(f"[indeed] Buscando '{keyword}' -> {url}")
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
                self._human_delay(3.0)
                
                # Cloudflare check
                if "Just a moment" in self._page.title() or "Cloudflare" in self._page.title():
                    logger.warning("[indeed] Bloqueo de Cloudflare detectado.")
                    return raw_jobs
                    
                # Extraer job cards: Indeed usa <a> con class o id que contiene "job_" o data-jk
                job_cards = self._page.locator("a[data-jk]").all()

                for card in job_cards:
                    if len(raw_jobs) >= max_results:
                        break
                        
                    href = card.get_attribute("href")
                    if not href:
                        continue
                        
                    full_url = f"https://cl.indeed.com{href}" if href.startswith("/") else href
                    external_id = card.get_attribute("data-jk")
                        
                    title_text = ""
                    company_text = ""
                    
                    try:
                        # En Indeed el título suele estar en un span title o h2 class jobTitle
                        headers = card.locator("h2").all_inner_texts()
                        if headers:
                            title_text = headers[0].strip()
                        else:
                            # Fallback para Indeed
                            span_title = card.locator("span[title]").first
                            if span_title.count() > 0:
                                title_text = span_title.get_attribute("title")
                                
                        # Extraer empresa (suele estar en un div con class companyName o company_location)
                        company_loc = card.locator("[data-testid='company-name']").first
                        if company_loc.count() > 0:
                            company_text = company_loc.inner_text().strip()
                        else:
                            all_text = card.inner_text().split('\n')
                            if len(all_text) > 1:
                                company_text = all_text[1].strip()
                                
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
                logger.error(f"[indeed] Error en búsqueda de '{keyword}': {e}")
                
            self._human_delay(1.5)

        logger.info(f"[indeed] Encontradas {len(raw_jobs)} ofertas base.")
        return raw_jobs

    def get_job_detail(self, url: str) -> RawJobData | None:
        self._init_browser()
        
        logger.debug(f"[indeed] Obteniendo detalle: {url}")
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
            self._human_delay(1.5)
            
            title = ""
            company = ""
            description = ""
            
            # Titulo principal en h1
            h1 = self._page.locator("h1").first
            if h1.count() > 0:
                title = h1.inner_text()
                
            # Descripción (suele estar en div con id jobDescriptionText)
            desc_locator = self._page.locator("#jobDescriptionText")
            if desc_locator.count() > 0:
                description = desc_locator.inner_text()
                raw_html = desc_locator.inner_html()
            else:
                body = self._page.locator("body")
                description = body.inner_text()[:4000]
                raw_html = body.inner_html()[:10000]
                
            if not title:
                return None
                
            return RawJobData(
                portal=self.portal_name,
                url=url,
                title=title,
                company=company,
                description=description,
                raw_html=raw_html,
                published_at=datetime.now(timezone.utc),
            )
            
        except Exception as e:
            logger.error(f"[indeed] Error obteniendo detalle: {e}")
            return None
