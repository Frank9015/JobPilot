"""
JobPilot — Core Configuration
Carga config.yaml + variables de entorno con validación Pydantic.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

import os
ROOT_DIR = Path(os.getenv("APP_HOME", Path.cwd()))


# ── Settings desde .env ───────────────────────────────────────────────────────
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Base de datos
    database_url: str = "postgresql://jobpilot:jobpilot@localhost:5432/jobpilot"

    # Gemini
    gemini_api_key: str = ""
    gemini_mock_mode: bool = True  # por defecto: modo desarrollo sin tokens reales

    # Portales — Credenciales
    linkedin_email: str = ""
    linkedin_password: str = ""
    bumeran_email: str = ""
    bumeran_password: str = ""
    laborum_email: str = ""
    laborum_password: str = ""
    indeed_email: str = ""
    indeed_password: str = ""
    sence_rut: str = ""
    sence_password: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Entorno
    environment: str = "development"
    project_root: str = ""

    @field_validator("project_root", mode="before")
    @classmethod
    def set_project_root(cls, v: str) -> str:
        return v or str(ROOT_DIR)


# ── Config desde config.yaml ──────────────────────────────────────────────────
class AppConfig:
    """Carga y expone config.yaml como atributos tipados."""

    def __init__(self, config_path: Path | None = None) -> None:
        path = config_path or ROOT_DIR / "config.yaml"
        if not path.exists():
            raise FileNotFoundError(f"config.yaml no encontrado en {path}")
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        self._raw = raw

    # ── Búsqueda ──────────────────────────────────────────────
    @property
    def search_keywords(self) -> list[str]:
        return self._raw["search"]["keywords"]

    @property
    def search_location(self) -> str:
        return self._raw["search"]["location"]

    @property
    def search_modality(self) -> str:
        return self._raw["search"]["modality"]

    @property
    def salary_min(self) -> int:
        return self._raw["search"]["salary_min"]

    @property
    def max_results_per_portal(self) -> int:
        return self._raw["search"]["max_results_per_portal"]

    # ── Scoring ───────────────────────────────────────────────
    @property
    def min_score_to_apply(self) -> float:
        return float(self._raw["scoring"]["min_score_to_apply"])

    @property
    def score_weights(self) -> dict[str, float]:
        return self._raw["scoring"]["weights"]

    # ── Automatización ────────────────────────────────────────
    @property
    def headful(self) -> bool:
        return self._raw["automation"]["headful"]

    @property
    def delay_min(self) -> float:
        return self._raw["automation"]["delay_min"]

    @property
    def delay_max(self) -> float:
        return self._raw["automation"]["delay_max"]

    @property
    def action_timeout(self) -> int:
        return self._raw["automation"]["action_timeout"]

    @property
    def max_retries(self) -> int:
        return self._raw["automation"]["max_retries"]

    # ── Gemini ────────────────────────────────────────────────
    @property
    def gemini_model_flash(self) -> str:
        return self._raw["gemini"]["model_flash"]

    @property
    def gemini_model_pro(self) -> str:
        return self._raw["gemini"]["model_pro"]

    @property
    def daily_flash_request_limit(self) -> int:
        return self._raw["gemini"]["daily_flash_request_limit"]

    @property
    def daily_pro_request_limit(self) -> int:
        return self._raw["gemini"]["daily_pro_request_limit"]

    @property
    def daily_token_limit(self) -> int:
        return self._raw["gemini"]["daily_token_limit"]

    # ── Intervención ──────────────────────────────────────────
    @property
    def intervention_timeout(self) -> int:
        return self._raw["intervention"]["timeout_seconds"]

    @property
    def intervention_poll_interval(self) -> int:
        return self._raw["intervention"]["poll_interval"]

    # ── Portales ──────────────────────────────────────────────
    @property
    def enabled_portals(self) -> list[str]:
        return [
            name
            for name, cfg in self._raw["portals"].items()
            if cfg.get("enabled", False)
        ]

    def portal_daily_limit(self, portal: str) -> int:
        return self._raw["portals"][portal]["daily_apply_limit"]

    # ── Rutas ─────────────────────────────────────────────────
    @property
    def cv_master_dir(self) -> Path:
        return ROOT_DIR / self._raw["paths"]["cv_master_dir"]

    @property
    def cv_generated_dir(self) -> Path:
        return ROOT_DIR / self._raw["paths"]["cv_generated_dir"]

    @property
    def sessions_dir(self) -> Path:
        return ROOT_DIR / self._raw["paths"]["sessions_dir"]

    @property
    def logs_dir(self) -> Path:
        return ROOT_DIR / self._raw["paths"]["logs_dir"]


# ── Singletons ────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return AppConfig()
