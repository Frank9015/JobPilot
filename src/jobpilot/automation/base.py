"""
JobPilot — Base Automator
Clase base para automatización de portales con Playwright.
Maneja ciclo de vida del browser, sesiones persistentes y anti-detección.
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any

from jobpilot.core.config import AppConfig, get_config, get_settings, ROOT_DIR
from jobpilot.core.logger import get_logger

logger = get_logger("automation.base")


class BaseAutomator:
    """
    Clase base para automatizadores de portales laborales.

    Gestiona:
    - Browser Playwright con sesión persistente (cookies/localStorage)
    - Delays anti-detección configurables
    - Detección de situaciones que requieren intervención humana
    - Login manual (setup_session)

    Subclases implementan:
    - portal_name: identificador del portal
    - _login_url: URL de login
    - _check_logged_in(page): verifica si hay sesión activa
    - apply_to_job(...): flujo de postulación
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._settings = get_settings()
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None

    @property
    def portal_name(self) -> str:
        raise NotImplementedError

    @property
    def _login_url(self) -> str:
        raise NotImplementedError

    @property
    def _session_dir(self) -> Path:
        return self._config.sessions_dir / self.portal_name

    @property
    def _cookies_file(self) -> Path:
        return self._session_dir / "cookies.json"

    # ── Browser Lifecycle ─────────────────────────────────────────────────────
    def _launch_browser(self, headful: bool | None = None) -> None:
        """Lanza Chromium con contexto persistente."""
        from playwright.sync_api import sync_playwright

        if headful is None:
            headful = self._config.headful

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=not headful,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )

        # Crear contexto con user-agent realista
        self._context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="es-CL",
            timezone_id="America/Santiago",
        )

        # Cargar cookies si existen
        self._load_session()

        self._page = self._context.new_page()

        # Anti-detección: ocultar webdriver
        self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        logger.info(f"Browser lanzado para [{self.portal_name}] (headful={headful})")

    def close(self) -> None:
        """Guarda sesión y cierra browser."""
        if self._context:
            self._save_session()
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None
        self._page = None
        self._context = None
        logger.debug(f"Browser cerrado para [{self.portal_name}]")

    # ── Session Persistence ───────────────────────────────────────────────────
    def _save_session(self) -> None:
        """Guarda cookies del contexto actual en disco."""
        if not self._context:
            return
        self._session_dir.mkdir(parents=True, exist_ok=True)
        cookies = self._context.cookies()
        with open(self._cookies_file, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2, default=str)
        logger.debug(f"Sesion guardada: {len(cookies)} cookies -> {self._cookies_file}")

    def _load_session(self) -> None:
        """Carga cookies guardadas en el contexto."""
        if not self._cookies_file.exists():
            logger.debug(f"Sin sesion guardada para [{self.portal_name}]")
            return
        try:
            with open(self._cookies_file, encoding="utf-8") as f:
                cookies = json.load(f)
            self._context.add_cookies(cookies)
            logger.info(f"Sesion cargada: {len(cookies)} cookies de {self._cookies_file}")
        except Exception as e:
            logger.warning(f"Error cargando sesion: {e}")

    def has_saved_session(self) -> bool:
        """Verifica si hay una sesión guardada en disco."""
        return self._cookies_file.exists()

    # ── Setup: Login Manual ───────────────────────────────────────────────────
    def setup_session(self) -> bool:
        """
        Abre un browser VISIBLE para que el usuario haga login manualmente.
        Espera a que el usuario complete el login y guarda la sesión.
        Retorna True si el login fue exitoso.
        """
        logger.info(f"Iniciando setup de sesion para [{self.portal_name}]")

        self._launch_browser(headful=True)
        self._page.goto(self._login_url, wait_until="domcontentloaded")

        print(f"\n{'='*60}")
        print(f"  SETUP: {self.portal_name.upper()}")
        print(f"{'='*60}")
        print(f"  Se abrio el navegador en: {self._login_url}")
        print(f"  Por favor, haz login manualmente.")
        print(f"  Resuelve cualquier CAPTCHA o verificacion.")
        print(f"  Cuando termines, presiona ENTER aqui...")
        print(f"{'='*60}\n")

        try:
            input("  >> Presiona ENTER cuando hayas completado el login: ")
        except (EOFError, KeyboardInterrupt):
            logger.info("Setup cancelado por el usuario")
            self.close()
            return False

        # Verificar login
        is_logged = self._check_logged_in(self._page)
        self._save_session()

        if is_logged:
            logger.info(f"Login exitoso en [{self.portal_name}]. Sesion guardada.")
            # Actualizar session_status en BD
            self._update_session_status("active")
        else:
            logger.warning(f"No se pudo verificar login en [{self.portal_name}]. Sesion guardada igualmente.")
            self._update_session_status("suspicious")

        self.close()
        return is_logged

    def _check_logged_in(self, page) -> bool:
        """Verifica si el usuario está logueado. Subclases deben sobreescribir."""
        return True

    # ── Anti-Detection ────────────────────────────────────────────────────────
    def _human_delay(self, factor: float = 1.0) -> None:
        """Delay aleatorio para simular comportamiento humano."""
        delay = random.uniform(
            self._config.delay_min * factor,
            self._config.delay_max * factor,
        )
        time.sleep(delay)

    def _human_type(self, page, selector: str, text: str) -> None:
        """Escribe texto con delay entre teclas para simular humano."""
        element = page.locator(selector)
        element.click()
        for char in text:
            element.press(char)
            time.sleep(random.uniform(0.03, 0.12))

    def _random_scroll(self, page) -> None:
        """Scroll aleatorio para parecer humano."""
        scroll_amount = random.randint(100, 400)
        page.mouse.wheel(0, scroll_amount)
        self._human_delay(factor=0.5)

    # ── Session Status BD ─────────────────────────────────────────────────────
    def _update_session_status(self, status: str, reason: str | None = None) -> None:
        """Actualiza la tabla session_status en BD."""
        try:
            from jobpilot.database.engine import get_session
            from jobpilot.database.models import SessionStatus
            from sqlalchemy import select
            from datetime import datetime, timezone

            with get_session() as session:
                existing = session.scalar(
                    select(SessionStatus).where(SessionStatus.portal == self.portal_name)
                )
                if existing:
                    existing.status = status
                    existing.reason = reason
                    existing.last_checked = datetime.now(timezone.utc)
                    if status == "active":
                        existing.last_active = datetime.now(timezone.utc)
                    existing.session_file = str(self._cookies_file)
                else:
                    session.add(SessionStatus(
                        portal=self.portal_name,
                        status=status,
                        reason=reason,
                        session_file=str(self._cookies_file),
                    ))
                logger.debug(f"Session status [{self.portal_name}] -> {status}")
        except Exception as e:
            logger.warning(f"Error actualizando session_status: {e}")
