# JobPilot 🚀

> **IMPORTANTE: Descargo de Responsabilidad (Disclaimer)**
>
> Este es un **proyecto de carácter estrictamente personal, educativo y de simulación**. 
> Se ha desarrollado con el único fin de facilitar la gestión y postulación propia a ofertas de empleo en portales laborales de Chile (LinkedIn, Bumeran, Laborum, Indeed, SENCE). 
> El uso de herramientas de automatización puede estar sujeto a los Términos y Condiciones de cada plataforma laboral. El autor no se responsabiliza por bloqueos de cuentas, restricciones de acceso o cualquier acción tomada por los portales de empleo debido al uso de esta herramienta. Úselo bajo su propio riesgo y criterio de forma moderada.

---

**JobPilot** es una plataforma integrada de automatización.

<div align="center">
  <h3>Tu Asistente Autónomo de Búsqueda Laboral</h3>
  <p>Automatiza el scraping, scoring, generación de CVs a medida y postulación en portales laborales de Chile.</p>
</div> 

JobPilot analiza ofertas basándose exclusivamente en tu experiencia real y automatiza el proceso de postulación con Playwright mediante un esquema híbrido de "Human-in-the-Loop" (Intervención Humana) para resolver CAPTCHAs, preguntas complejas o autenticación multifactor (MFA). 

> **Aviso de Estado:** El proyecto se encuentra actualmente en fase de **Desarrollo (Alpha)**. Aún quedan módulos por pulir, integraciones por estabilizar y refactorizaciones pendientes. No se recomienda su uso para misiones críticas sin supervisión constante.
---

## 🛠️ Arquitectura y Stack Tecnológico

El proyecto está diseñado bajo una arquitectura modular y robusta en Python 3.13, dividida en capas funcionales claras:

```mermaid
graph TD
    A[CV Maestro PDF] -->|Parser de Perfil| B(Gemini 2.5 Flash API)
    B -->|Perfil Estructurado JSON| C[(Base de Datos PostgreSQL)]
    
    D[Scrapers: LinkedIn, Bumeran, etc.] -->|Extracción de Ofertas| C
    C -->|Filtro & Ofertas| E[Motor de Scoring AI]
    E -->|Compatibilidad & CV Adaptado| C
    
    C -->|Datos de Postulación| F[Playwright Automation]
    F -->|Necesita Intervención| G[Human-In-The-Loop UI]
    F -->|Postulación Exitosa| H[(Registro Trazabilidad)]
    
    C <--> I[FastAPI Dashboard Web]
```

### Tecnologías Core

*   **Lenguaje:** Python 3.13
*   **Base de Datos & ORM:** PostgreSQL + SQLAlchemy (14 modelos ORM para trazabilidad total, ofertas, postulaciones y logs de IA) + Alembic (Gestión de migraciones).
*   **Automatización de Navegador:** Playwright (Python async API) para el manejo de sesiones persistentes y llenado automático de formularios.
*   **Inteligencia Artificial:** SDK oficial `google-genai` para el análisis de ofertas, cálculo de puntaje de compatibilidad y generación adaptativa de CVs (WeasyPrint + Jinja2).
*   **Control de Costos:** **Token Guardian**, un componente interno que gestiona el presupuesto de tokens, caching de prompts y evita llamadas duplicadas a la API gratuita de Gemini.
*   **Dashboard Web & API:** FastAPI + Uvicorn + WebSockets para el monitoreo en tiempo real, configuración de credenciales y carga del CV maestro.
*   **Interfaz de Consola:** `rich` para reportes limpios, coloreados y con formato avanzado en la terminal.

---

## ⚙️ Estructura del Repositorio

La estructura del código sigue el estándar de empaquetado moderno de Python:

```text
├── alembic/                 # Migraciones de la base de datos PostgreSQL
├── data/                    # Almacenamiento local (Ignorado en Git excepto estructura básica)
│   ├── cv_master/           # CV Maestro en PDF del usuario
│   ├── cv_generated/        # CVs temporales adaptados por oferta
│   └── sessions/            # Perfiles y cookies de Playwright (LinkedIn, Indeed, etc.)
├── logs/                    # Logs detallados de ejecución del sistema
├── src/jobpilot/            # Código fuente principal
│   ├── core/                # Configuraciones, logger, Token Guardian, etc.
│   ├── database/            # Conexión ORM, engine y modelos de base de datos
│   ├── profile/             # Parser de CV maestro, modelos Pydantic y lógica de perfil
│   ├── scraper/             # Scrapers específicos de portales (LinkedIn, Bumeran, Laborum, etc.)
│   ├── scoring/             # Motor de análisis semántico con Gemini y fallbacks
│   ├── automation/          # Lógica de Playwright y control Human-in-the-Loop
│   ├── cv/                  # Generador y renderizador de CVs adaptados (Playwright PDF)
│   └── dashboard/           # Dashboard Web (FastAPI + HTML/CSS/JS)
├── tests/                   # Pruebas unitarias e integraciones simuladas (Mocking)
├── config.yaml              # Configuración general del sistema y límites de IA
├── pyproject.toml           # Declaración de dependencias (Hatchling)
└── main.py                  # CLI principal de control
```

---

## ⚠️ Estado del Proyecto: En Desarrollo (Alpha)
JobPilot opera en modo distribuido (Daemon) o CLI y cuenta con soporte Docker. Sin embargo, el código aún está en fase de pulido y pruebas continuas. No apto para uso crítico sin supervisión.

## 📦 Instalación y Despliegue

La forma recomendada y más estable de ejecutar JobPilot actualmente es mediante Docker, ya que encapsula las dependencias complejas (como Playwright y PostgreSQL).

### Opción 1: Docker Compose (Recomendado)
```bash
docker-compose up -d --build
```
Esto levantará el **Dashboard Web** en el puerto `8000` y el **Orquestador** en modo Demonio (revisando ofertas cada 3 horas automáticamente).

### Opción 2: Instalación Local (Para Desarrolladores)

1. **Crear y activar un entorno virtual:**
    ```bash
    python -m venv .venv
    # En Windows: .venv\Scripts\activate
    # En Linux/macOS: source .venv/bin/activate
    ```

2. **Instalar JobPilot y sus dependencias:**
    ```bash
    pip install -e .
    ```

3. **Instalar los navegadores de Playwright:**
    ```bash
    playwright install chromium
    ```

4. **Configurar Variables de Entorno:**
    Copia el archivo `.env.example` como `.env`:
    ```bash
    cp .env.example .env
    ```
    Edita `.env` con tus credenciales locales:
    *   `DATABASE_URL`: URI de conexión a tu PostgreSQL (ej: `postgresql://jobpilot:jobpilot@localhost:5432/jobpilot`).
    *   `GEMINI_API_KEY`: Tu clave de Gemini.
    *   `GEMINI_MOCK_MODE`: Establécelo en `true` durante el desarrollo local para simular llamadas a la IA sin consumir tu cuota.

5. **Ejecutar Migraciones de Base de Datos:**
    Con PostgreSQL activo y la base de datos configurada, aplica el esquema de Alembic:
    ```bash
    alembic upgrade head
    ```

6. **Carga del CV Maestro:**
    Coloca tu archivo de currículum maestro en PDF en la ruta:
    `data/cv_master/mi_cv.pdf`
    (Asegúrate de configurar la ruta correcta en el archivo `.env` en la variable `CV_MASTER_PATH`).

---

## 💻 Uso del CLI Principal

Para ejecutar el sistema en Windows, se recomienda habilitar la codificación UTF-8 en PowerShell para evitar problemas con emojis o caracteres especiales de la consola (`rich`):

```powershell
$env:PYTHONUTF8 = "1"
```

## 🚦 Uso Básico (CLI Local)

Puedes arrancar el orquestador maestro en tu terminal:

```bash
python main.py --daemon   # Ejecución programada continua (Daemon Mode)
python main.py            # Ciclo End-to-End manual
python main.py --dashboard # Levantar panel de control UI
```

*   **Login manual en portales (`--setup`):**
    Abre un navegador visible para que hagas login manualmente en LinkedIn y otros portales. Las sesiones se guardan localmente.
    ```bash
    python main.py --setup
    ```

*   **Scraping de ofertas (`--scrape`):**
    Busca nuevas ofertas en los portales habilitados (LinkedIn, etc.) y las guarda en la base de datos.
    ```bash
    python main.py --scrape
    ```

*   **Scoring de ofertas (`--score`):**
    Evalúa las ofertas pendientes contra tu perfil usando Gemini AI (o heurísticas como fallback). Calcula compatibilidad por skills, experiencia, educación y ubicación.
    ```bash
    python main.py --score
    ```

*   **Generar CVs adaptados (`--generate-cv`):**
    Para cada oferta elegible (score >= umbral), genera un CV PDF personalizado que destaca las habilidades más relevantes sin inventar experiencia.
    ```bash
    python main.py --generate-cv
    ```

*   **Postulación automática (`--apply`):**
    Ejecuta Easy Apply en LinkedIn para ofertas elegibles. Por defecto funciona en **dry-run** (simula sin enviar).
    ```bash
    python main.py --apply              # Modo dry-run (simulación)
    python main.py --apply --no-dry     # Modo REAL (requiere confirmación)
    ```

*   **Ciclo completo:**
    Sin flags ejecuta el pipeline completo: scrape → score → generar CVs → apply (dry-run).
    ```bash
    python main.py
    python main.py --mock   # Fuerza modo mock de Gemini
    ```

---

## 🖥️ Dashboard Web

El dashboard se inicia con `python main.py --dashboard` y ofrece 4 pantallas:

| Pantalla | Descripción |
|----------|-------------|
| **📊 Dashboard** | KPIs (total ofertas, evaluadas, CVs generados, postuladas), panel de control con botones de acción, widget de uso de Gemini AI con progress bars |
| **💼 Ofertas** | Tabla interactiva con filtros por status y portal, scores detallados por skill/experiencia/educación |
| **👤 Perfil** | Datos del candidato, skills técnicos como tags, upload de CV maestro con drag & drop |
| **⚙️ Configuración** | Semáforo de sesiones por portal (🟢/🟡/🔴), estado del sistema |

El diseño es dark-mode premium con glassmorphism, tipografía Inter, micro-animaciones y auto-refresh cada 30 segundos.

**API REST** disponible en `http://localhost:8000/api/docs` (Swagger automático de FastAPI).

---

## 🔒 Privacidad y Seguridad

Este proyecto excluye automáticamente información confidencial del control de versiones (`.gitignore`):
*   El archivo de variables de entorno `.env` (donde se guardan API keys y contraseñas).
*   La carpeta `data/cv_master/` que contiene tu CV real y datos de contacto.
*   La carpeta `data/sessions/` que guarda tokens activos de sesión de los portales laborales.
*   Los archivos PDF adaptados temporales generados para cada oferta en `data/cv_generated/`.

**NUNCA** subas tus claves de API o bases de datos de sesión a un repositorio público en GitHub.

---

## 🗺️ Roadmap de Desarrollo

- [x] **Fase 1: Núcleo y Modelo de Datos** — BD PostgreSQL (15 tablas), migraciones Alembic, parser de CV con Gemini, CLI con `rich`.
- [x] **Fase 2: Scraping + Scoring** — LinkedIn scraper, motor de scoring (Gemini + heurísticas), Token Guardian, cache de prompts.
- [x] **Fase 3: CV Generator + Automatización** — Generador de CVs adaptados (Playwright PDF), LinkedIn Easy Apply con dry-run, form filler inteligente.
- [x] **Dashboard Web** — FastAPI + vanilla JS/CSS, 4 pantallas, diseño dark premium, control panel, widget Gemini.
- [ ] **Fase 4: Intervención Humana + Orquestador** — Notificaciones Telegram, consola interactiva para CAPTCHAs/preguntas, scheduler.
- [ ] **Fase 5: Multi-portal** — Scrapers y automators para Bumeran, Laborum, Indeed Chile, SENCE.
- [ ] **Fase 6: Producción** — Docker Compose, alertas, reportes, tests de carga.

---

## 📄 Licencia

Este es un software libre de uso exclusivamente personal. Queda prohibida su distribución para fines comerciales o masivos sin autorización expresa.

