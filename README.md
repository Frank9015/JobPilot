# JobPilot 🚀

> **IMPORTANTE: Descargo de Responsabilidad (Disclaimer)**
>
> Este es un **proyecto de carácter estrictamente personal, educativo y de simulación**. 
> Se ha desarrollado con el único fin de facilitar la gestión y postulación propia a ofertas de empleo en portales laborales de Chile (LinkedIn, Bumeran, Laborum, Indeed, SENCE). 
> **No está diseñado ni destinado para su uso comercial o masivo.** 
> El uso de herramientas de automatización puede estar sujeto a los Términos y Condiciones de cada plataforma laboral. El autor no se responsabiliza por bloqueos de cuentas, restricciones de acceso o cualquier acción tomada por los portales de empleo debido al uso de esta herramienta. Úselo bajo su propio riesgo y criterio de forma moderada.

---

**JobPilot** es una plataforma integrada de automatización y optimización de búsqueda laboral enfocada en el mercado chileno. El sistema centraliza ofertas de múltiples portales, calcula el porcentaje de compatibilidad contra el perfil del usuario mediante Inteligencia Artificial (Gemini), adapta dinámicamente el currículum del postulante basándose exclusivamente en su experiencia real y automatiza el proceso de postulación con Playwright mediante un esquema híbrido de "Human-in-the-Loop" (Intervención Humana) para resolver CAPTCHAs, preguntas complejas o autenticación multifactor (MFA).

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
│   └── automation/          # Lógica de Playwright y control Human-in-the-Loop
├── tests/                   # Pruebas unitarias e integraciones simuladas (Mocking)
├── config.yaml              # Configuración general del sistema y límites de IA
├── pyproject.toml           # Declaración de dependencias (Hatchling)
└── main.py                  # CLI principal de control
```

---

## 🚀 Instalación y Configuración

### Prerrequisitos

1.  **Python 3.13+** instalado.
2.  **PostgreSQL 17** (o compatible) en ejecución.
3.  Una clave de API de **Google Gemini** (se puede obtener gratis en Google AI Studio).

### Pasos de Instalación

1.  **Clonar el repositorio:**
    ```bash
    git clone https://github.com/tu-usuario/jobpilot.git
    cd jobpilot
    ```

2.  **Crear y activar el entorno virtual:**
    ```bash
    # En Windows (PowerShell)
    python -m venv .venv
    .venv\Scripts\Activate.ps1
    ```

3.  **Instalar dependencias del proyecto:**
    ```bash
    pip install -e .
    ```

4.  **Configurar Variables de Entorno:**
    Copia el archivo `.env.example` como `.env`:
    ```bash
    cp .env.example .env
    ```
    Edita `.env` con tus credenciales locales:
    *   `DATABASE_URL`: URI de conexión a tu PostgreSQL (ej: `postgresql://jobpilot:jobpilot@localhost:5432/jobpilot`).
    *   `GEMINI_API_KEY`: Tu clave de Gemini.
    *   `GEMINI_MOCK_MODE`: Establécelo en `true` durante el desarrollo local para simular llamadas a la IA sin consumir tu cuota.
    *   Credenciales de los portales (LinkedIn, Bumeran, etc.) para los scrapers.

5.  **Ejecutar Migraciones de Base de Datos:**
    Con PostgreSQL activo y la base de datos configurada, aplica el esquema de Alembic:
    ```bash
    alembic upgrade head
    ```

6.  **Instalar Navegadores de Playwright:**
    ```bash
    playwright install chromium
    ```

7.  **Carga del CV Maestro:**
    Coloca tu archivo de currículum maestro en PDF en la ruta:
    `data/cv_master/mi_cv.pdf`
    (Asegúrate de configurar la ruta correcta en el archivo `.env` en la variable `CV_MASTER_PATH`).

---

## 💻 Uso del CLI Principal

Para ejecutar el sistema en Windows, se recomienda habilitar la codificación UTF-8 en PowerShell para evitar problemas con emojis o caracteres especiales de la consola (`rich`):

```powershell
$env:PYTHONUTF8 = "1"
```

### Comandos Disponibles

*   **Verificar el estado del sistema (`--status`):**
    Comprueba las conexiones a la base de datos, la validez de las claves de Gemini, la presencia de archivos maestros y muestra el estado general.
    ```bash
    python main.py --status
    ```

*   **Inicializar y Procesar Perfil (`--setup`):**
    Lee el CV Maestro PDF, utiliza Gemini para extraer las secciones estructuradas (educación, experiencia, habilidades, proyectos) y lo guarda en la base de datos PostgreSQL.
    ```bash
    python main.py --setup
    ```

*   **Ejecutar Simulación con Mocks (`--mock`):**
    Corre el pipeline simulado del sistema. Inserta ofertas de empleo de prueba, calcula compatibilidad usando respuestas predefinidas (mocks) y genera un borrador de CV adaptado en PDF. Sirve para validar la base de datos y la generación de documentos sin gastar cuota de API.
    ```bash
    python main.py --mock
    ```

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

- [x] **Fase 1: Núcleo y Modelo de Datos** (Base de datos PostgreSQL, Migraciones con Alembic, Parser de CV Maestro por AI, Consola CLI, Estructura del proyecto).
- [ ] **Fase 2: Motores de Scraping e Inteligencia de Ofertas** (Scraper de LinkedIn/Bumeran, scoring semántico con Gemini, guardián de tokens, detección de duplicados).
- [ ] **Fase 3: Automatización de Llenado e Intervención Humana** (Mapeador de formularios Playwright, interceptor para CAPTCHAs/preguntas, sistema de notificaciones Telegram).
- [ ] **Fase 4: Interfaz Web y Dashboard** (FastAPI Web Panel, estadísticas de postulaciones, panel de control encendido/apagado, configurador de credenciales visual, visualización de alertas).

---

## 📄 Licencia

Este es un software libre de uso exclusivamente personal. Queda prohibida su distribución para fines comerciales o masivos sin autorización expresa.
