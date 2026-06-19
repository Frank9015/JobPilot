"""
JobPilot — Laborum Scraper
Scraper basado en Playwright para evadir bloqueos de Cloudflare y DataDome.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

from jobpilot.core.logger import get_logger
from jobpilot.scraper.base import BaseScraper, RawJobData

logger = get_logger("scraper.laborum")


class LaborumScraper(BaseScraper):
    """
    Scraper para Laborum Chile (Plataforma Jobint, idéntica a Bumeran).
    """

    def __init__(self) -> None:
        super().__init__()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    @property
    def portal_name(self) -> str:
        return "laborum"

    # ── Playwright Lifecycle ──────────────────────────────────────────────────
    def _init_browser(self) -> None:
        if self._browser is not None:
            return

        logger.debug("[laborum] Iniciando navegador Playwright para scraper")
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

    # ── Extracción ────────────────────────────────────────────────────────────
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
                
            query = keyword.replace(" ", "-")
            url = f"https://www.laborum.cl/empleos-busqueda-{query}.html"
            
            logger.info(f"[laborum] Buscando '{keyword}' -> {url}")
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
                self._human_delay(2.0)
                
                # Bumeran/Laborum Jobint platform
                job_cards = self._page.locator("a[href*='/empleos/']").all()
                
                if "DataDome" in self._page.title() or "Verificando" in self._page.title():
                    logger.warning("[laborum] DataDome detectado. Bloqueo inminente.")
                    return raw_jobs

                for card in job_cards:
                    if len(raw_jobs) >= max_results:
                        break
                        
                    href = card.get_attribute("href")
                    if not href or "/empleos/" not in href:
                        continue
                        
                    full_url = f"https://www.laborum.cl{href}" if href.startswith("/") else href
                    
                    external_id = None
                    match = re.search(r"-(\d+)\.html", full_url)
                    if match:
                        external_id = match.group(1)
                        
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
                logger.error(f"[laborum] Error en búsqueda de '{keyword}': {e}")
                
            self._human_delay(1.5)

        logger.info(f"[laborum] Encontradas {len(raw_jobs)} ofertas base.")
        return raw_jobs

    def get_job_detail(self, url: str) -> RawJobData | None:
        self._init_browser()
        
        logger.debug(f"[laborum] Obteniendo detalle: {url}")
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
            self._human_delay(1.0)
            
            title = ""
            company = ""
            description = ""
            
            h1 = self._page.locator("h1").first
            if h1.count() > 0:
                title = h1.inner_text()
                
            body = self._page.locator("body")
            raw_html = body.inner_html()
            full_text = body.inner_text()
            
            desc_locator = self._page.locator("div[id*='descripcion'], div[class*='Description']")
            if desc_locator.count() > 0:
                description = desc_locator.first.inner_text()
            else:
                description = full_text[:4000]
                
            if not title:
                return None
                
            return RawJobData(
                portal=self.portal_name,
                url=url,
                title=title,
                company=company,
                description=description,
                raw_html=raw_html[:10000] if raw_html else None,
                published_at=datetime.now(timezone.utc),
            )
            
        except Exception as e:
            logger.error(f"[laborum] Error obteniendo detalle: {e}")
            return None
