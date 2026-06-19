# Usar la imagen base oficial de Python 3.11 (o 3.10)
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Establecer variables de entorno
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    APP_HOME=/app

# Establecer el directorio de trabajo
WORKDIR $APP_HOME

# Instalar dependencias del sistema y herramientas necesarias
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar configuracion de dependencias y código fuente
COPY pyproject.toml .
COPY README.md .
COPY src/ ./src/

# Instalar las dependencias de Python del proyecto (y apscheduler extra)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . apscheduler

# Instalar navegadores de Playwright explícitamente (por seguridad)
RUN playwright install chromium

COPY main.py .
COPY .env .
COPY config.yaml .

# Exponer el puerto del Dashboard (FastAPI)
EXPOSE 8000

# Punto de entrada predeterminado (puede sobreescribirse en docker-compose)
CMD ["python", "main.py", "--daemon"]
