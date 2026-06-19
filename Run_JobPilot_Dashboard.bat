@echo off
title JobPilot Dashboard Launcher
chcp 65001 >nul
color 0B

echo ===================================================
echo               JobPilot Dashboard
echo ===================================================
echo.
echo Iniciando entorno virtual...
if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] No se encontro el entorno virtual en .venv
    pause
    exit /b
)
call .venv\Scripts\activate.bat

echo.
echo Lanzando servidor FastAPI...
echo El dashboard estara disponible en http://localhost:8000
echo.
echo (Presiona Ctrl+C en cualquier momento para detener el servidor)
echo ===================================================

set PYTHONUTF8=1
python main.py --dashboard

pause
