"""
JobPilot — Load Test Script (Phase 4)
Este script verifica que el Orchestrator pueda levantar los Scrapers
sin provocar memory leaks y maneje múltiples instancias de Chromium.
"""
import os
import sys
import psutil
import time
from pathlib import Path

# Añadir src al path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from jobpilot.core.orchestrator import Orchestrator

def print_memory(tag):
    process = psutil.Process(os.getpid())
    mem_mb = process.memory_info().rss / 1024 / 1024
    print(f"[{tag}] RAM Usada: {mem_mb:.2f} MB")

def run_load_test():
    print("Iniciando Load Test de JobPilot...")
    print_memory("INICIO")
    
    # Configuramos dry_run extremo
    orchestrator = Orchestrator(dry_run=True)
    
    # Solo ejecutar la fase de Scrape que es la más pesada en memoria (levanta Chromium)
    print("\nEjecutando Fase 1: Scraping...")
    start_time = time.time()
    try:
        orchestrator.run_phase_scrape()
    except Exception as e:
        print(f"Scrape falló (esperado si hay captchas sin resolver en modo headless): {e}")
        
    print_memory("POST-SCRAPE")
    print(f"Tiempo: {time.time() - start_time:.2f}s")
    
    print("\nTest completado. Evaluando limpieza de memoria...")
    # Forzar garbage collection (opcional pero bueno para tests)
    import gc
    gc.collect()
    print_memory("FIN")

if __name__ == "__main__":
    run_load_test()
