"""
JobPilot — Dashboard FastAPI App
Servidor web para el dashboard visual del sistema.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from jobpilot.dashboard.routers import jobs, profile, control, gemini, sessions

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="JobPilot Dashboard",
    version="0.3.0",
    docs_url="/api/docs",
    redoc_url=None,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(jobs.router, prefix="/api/jobs", tags=["Jobs"])
app.include_router(profile.router, prefix="/api/profile", tags=["Profile"])
app.include_router(control.router, prefix="/api/control", tags=["Control"])
app.include_router(gemini.router, prefix="/api/gemini", tags=["Gemini"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["Sessions"])

# Static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(str(STATIC_DIR / "index.html"))
