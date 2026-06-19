"""
JobPilot — Cross-Portal Deduplicator
Detecta si una oferta entrante ya existe en la base de datos,
posiblemente extraída desde otro portal.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobpilot.core.logger import get_logger
from jobpilot.database.models import JobOffer

logger = get_logger("scraper.deduplicator")


class CrossPortalDeduplicator:
    """
    Gestiona la lógica de deduplicación cross-portal.

    Estrategia:
    1. Normalización de strings (limpieza de acentos, símbolos, stop words).
    2. Búsqueda por external_id (exact match).
    3. Búsqueda por empresa + título (fuzzy match > 90%).
    """

    def __init__(self, session: Session, threshold: float = 0.90) -> None:
        self._session = session
        self._threshold = threshold
        
        # Cargar el caché de las ofertas recientes (últimos 30 días)
        # para hacer matching en memoria en vez de castigar la BD en cada iteración.
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        
        # Guardamos: [(id, portal, norm_company, norm_title, external_id)]
        self._recent_offers: list[dict] = []
        
        query = select(
            JobOffer.id,
            JobOffer.portal,
            JobOffer.company,
            JobOffer.title,
            JobOffer.external_id
        ).where(JobOffer.scraped_at >= thirty_days_ago)
        
        for row in self._session.execute(query):
            self._recent_offers.append({
                "id": row.id,
                "portal": row.portal,
                "company": self.normalize_text(row.company or ""),
                "title": self.normalize_text(row.title),
                "external_id": row.external_id,
            })
            
        logger.debug(f"Deduplicator cache cargado con {len(self._recent_offers)} ofertas recientes.")

    @staticmethod
    def normalize_text(text: str) -> str:
        """
        Normaliza un texto: minúsculas, sin acentos, sin símbolos,
        sin stop-words laborales comunes que ensucian la similitud.
        """
        if not text:
            return ""
            
        # 1. Minúsculas
        text = text.lower().strip()
        
        # 2. Quitar acentos
        text = "".join(
            c for c in unicodedata.normalize("NFD", text)
            if unicodedata.category(c) != "Mn"
        )
        
        # 3. Reemplazar símbolos por espacios (excepto letras y números)
        text = re.sub(r"[^a-z0-9]", " ", text)
        
        # 4. Remover espacios extra
        text = " ".join(text.split())
        
        # 5. Stop-words laborales
        stop_words = {
            "urgente", "se busca", "buscamos", "contratacion", "inmediata",
            "importante", "empresa", "santiago", "chile", "remoto", "hibrido",
            "junior", "senior", "semi", "ssr", "jr", "sr", "plazo", "fijo",
            "indefinido", "lunes", "viernes", "oferta", "laboral"
        }
        
        words = [w for w in text.split() if w not in stop_words]
        return " ".join(words)

    def is_duplicate(
        self, 
        portal: str, 
        external_id: str | None, 
        title: str, 
        company: str | None
    ) -> bool:
        """
        Verifica si la oferta ya existe.
        Retorna True si es un duplicado, False si es nueva.
        """
        # 1. Exact Match por portal y external_id (mismo portal)
        if external_id:
            for offer in self._recent_offers:
                if offer["portal"] == portal and offer["external_id"] == external_id:
                    return True

        # 2. Preparar campos para Fuzzy Matching cross-portal
        norm_inc_company = self.normalize_text(company or "")
        norm_inc_title = self.normalize_text(title)
        
        if not norm_inc_company or not norm_inc_title:
            # Si no hay empresa o el título quedó vacío, no podemos hacer fuzzy match seguro
            return False

        # 3. Fuzzy Match
        for offer in self._recent_offers:
            # Si el titulo difiere mucho, saltamos rapido
            ratio_title = SequenceMatcher(None, norm_inc_title, offer["title"]).ratio()
            if ratio_title < self._threshold:
                continue
                
            # Calcular similitud de empresa (puede ser substring o > 80% similitud)
            ratio_company = SequenceMatcher(None, norm_inc_company, offer["company"]).ratio()
            company_match = (
                ratio_company >= 0.80 or 
                norm_inc_company in offer["company"] or 
                offer["company"] in norm_inc_company
            )
            
            if company_match:
                logger.info(
                    f"Duplicado cross-portal detectado: "
                    f"'{title}' ({portal}) == '{offer['title']}' ({offer['portal']}) "
                    f"[similitud titulo: {ratio_title:.2f}, empresa: {ratio_company:.2f}]"
                )
                return True
                
        return False

    def add_to_cache(self, portal: str, external_id: str | None, title: str, company: str | None) -> None:
        """
        Agrega una nueva oferta al caché para futuras comparaciones en el mismo ciclo.
        """
        self._recent_offers.append({
            "id": None,  # No lo necesitamos para dedup
            "portal": portal,
            "company": self.normalize_text(company or ""),
            "title": self.normalize_text(title),
            "external_id": external_id,
        })
