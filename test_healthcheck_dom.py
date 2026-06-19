"""
JobPilot — DOM Healthcheck Script (Phase 1)
Navega a las páginas principales de los portales laborales para verificar que 
la estructura DOM principal (login, búsqueda, botones) no haya cambiado.
"""
import asyncio
from playwright.async_api import async_playwright
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DOM-Healthcheck")

PORTALS = {
    "laborum": {
        "url": "https://www.laborum.cl",
        "selectors": ["input[placeholder*='puesto']", "button:has-text('Buscar')"]
    },
    "bumeran": {
        "url": "https://www.bumeran.com.pe", # o el portal configurado
        "selectors": ["input[placeholder*='puesto']", "button:has-text('Buscar')"]
    },
    "sence": {
        "url": "https://www.bne.cl",
        "selectors": ["a:has-text('Ingresar')", "input[id='q']", "button:has-text('Buscar')"]
    },
    "indeed": {
        "url": "https://cl.indeed.com",
        "selectors": ["input[id*='text-input-what']", "button:has-text('Buscar')"]
    }
}

async def check_portal(p, name, data):
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page()
    try:
        logger.info(f"Comprobando {name} en {data['url']}...")
        await page.goto(data['url'], wait_until="domcontentloaded", timeout=30000)
        
        for sel in data['selectors']:
            count = await page.locator(sel).count()
            if count > 0:
                logger.info(f"[{name}] OK - Selector encontrado: {sel}")
            else:
                logger.warning(f"[{name}] FAIL - Selector no encontrado: {sel}")
                
    except Exception as e:
        logger.error(f"[{name}] Error navegando al portal: {e}")
    finally:
        await browser.close()

async def main():
    async with async_playwright() as p:
        tasks = []
        for name, data in PORTALS.items():
            tasks.append(check_portal(p, name, data))
        
        await asyncio.gather(*tasks)
        logger.info("Healthcheck DOM completado.")

if __name__ == "__main__":
    asyncio.run(main())
