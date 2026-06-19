"""
Tests Unitarios para el Deduplicador Cross-Portal.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from jobpilot.scraper.deduplicator import CrossPortalDeduplicator

def test_normalize_text():
    """Prueba la limpieza y normalización de textos."""
    # Test minúsculas, tildes y símbolos
    assert CrossPortalDeduplicator.normalize_text("Ingeniero de Software Senior, (Remoto)!") == "ingeniero de software"
    assert CrossPortalDeduplicator.normalize_text("Desarrollador Backend Jr. en Chile") == "desarrollador backend en"
    assert CrossPortalDeduplicator.normalize_text("Empresa Confidencial") == "confidencial"
    
def test_deduplicator_exact_match():
    """Prueba que el match exacto por external_id detecte el duplicado."""
    mock_session = MagicMock()
    # Mockear la carga inicial de la BD para que retorne vacio y probamos con el cache
    mock_session.execute.return_value = []
    
    dedup = CrossPortalDeduplicator(mock_session)
    
    # Agregar al cache manualmente
    dedup.add_to_cache(
        portal="linkedin",
        external_id="12345",
        title="Frontend Developer",
        company="TechCorp"
    )
    
    # Mismo portal, mismo ID -> Duplicado
    assert dedup.is_duplicate("linkedin", "12345", "Frontend Dev", "TechCorp") is True
    # Mismo portal, distinto ID -> No es duplicado exacto
    assert dedup.is_duplicate("linkedin", "67890", "Backend Dev", "TechCorp") is False
    # Distinto portal, mismo ID (aunque raro, podría pasar si es el mismo ATS backend, pero es por si acaso, el fuzzy match lo atajará si los textos coinciden)
    # Actually, the logic in deduplicator checks if portal == portal AND external_id == external_id
    assert dedup.is_duplicate("bumeran", "12345", "Frontend Dev", "TechCorp") is False

def test_deduplicator_fuzzy_match():
    """Prueba el match fuzzy cruzado entre portales (ej: LinkedIn y Bumeran)."""
    mock_session = MagicMock()
    mock_session.execute.return_value = []
    
    dedup = CrossPortalDeduplicator(mock_session, threshold=0.90)
    
    dedup.add_to_cache(
        portal="linkedin",
        external_id="111",
        title="Ingeniero de Software Senior Backend",
        company="Google Chile"
    )
    
    # Oferta desde Bumeran, mismo texto casi exacto, misma empresa
    # "Ingeniero Software Senior (Backend)" normalizado se parece mucho
    is_dup = dedup.is_duplicate(
        portal="bumeran",
        external_id="bum-555",
        title="Ingeniero Software Senior (Backend)",
        company="Google Chile SA"
    )
    assert is_dup is True
    
    # Oferta similar pero de otra empresa -> No es duplicado
    is_not_dup = dedup.is_duplicate(
        portal="bumeran",
        external_id="bum-666",
        title="Ingeniero Software Senior (Backend)",
        company="Microsoft"
    )
    assert is_not_dup is False
    
    # Oferta de misma empresa pero cargo muy distinto -> No es duplicado
    is_not_dup2 = dedup.is_duplicate(
        portal="bumeran",
        external_id="bum-777",
        title="Analista de QA Automation",
        company="Google Chile"
    )
    assert is_not_dup2 is False
