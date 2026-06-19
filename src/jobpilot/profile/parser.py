"""
JobPilot — CV Parser
Extrae datos estructurados de un CV en PDF usando PyMuPDF + Gemini Pro.
En GEMINI_MOCK_MODE=true usa respuestas predefinidas sin gastar tokens.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF

from jobpilot.core.config import get_config, get_settings
from jobpilot.core.logger import get_logger
from jobpilot.core.token_guardian import GeminiModel, GeminiOperation, TokenGuardian
from jobpilot.profile.models import (
    EducationData,
    ParseResult,
    PersonalInfo,
    ProfileData,
    ProjectData,
    SkillCategory,
    SkillData,
    SkillLevel,
    WorkExperienceData,
)

logger = get_logger("profile.parser")

# Ruta a los fixtures de mock
FIXTURES_DIR = (
    Path(__file__).parent.parent.parent.parent / "tests" / "fixtures" / "gemini"
)


# ── Extracción de texto del PDF ───────────────────────────────────────────────
def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extrae texto crudo del PDF usando PyMuPDF."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF no encontrado: {pdf_path}")

    doc = fitz.open(str(pdf_path))
    pages_text = []
    for page in doc:
        pages_text.append(page.get_text("text"))
    doc.close()

    raw_text = "\n".join(pages_text).strip()
    logger.info(f"PDF extraído: {len(raw_text)} caracteres, {len(pages_text)} páginas")
    return raw_text


# ── Parseo con Gemini Pro ─────────────────────────────────────────────────────
def _build_parse_prompt(raw_text: str) -> str:
    return f"""Eres un extractor de datos de CVs. Analiza el siguiente CV y extrae ÚNICAMENTE la información que está EXPLÍCITAMENTE escrita en él.

REGLAS CRÍTICAS:
- NO inventes información que no esté en el CV
- NO asumas niveles de habilidad que no estén indicados (usa "basic" por defecto si no se especifica)
- NO agregues tecnologías que no aparezcan en el texto
- Si un campo no está presente, usa null

Extrae y devuelve ÚNICAMENTE un JSON válido con esta estructura exacta:
{{
  "personal_info": {{
    "full_name": "string",
    "email": "string o null",
    "phone": "string o null",
    "location": "string o null",
    "linkedin_url": "string o null",
    "github_url": "string o null",
    "summary": "string o null"
  }},
  "education": [{{
    "institution": "string",
    "degree": "string",
    "field": "string o null",
    "start_date": "YYYY-MM-DD o null",
    "end_date": "YYYY-MM-DD o null",
    "gpa": número o null
  }}],
  "work_experience": [{{
    "company": "string",
    "role": "string",
    "start_date": "YYYY-MM-DD o null",
    "end_date": "YYYY-MM-DD o null",
    "is_current": boolean,
    "description": "string o null",
    "achievements": ["string"]
  }}],
  "skills": [{{
    "name": "string",
    "category": "language|framework|tool|soft|other",
    "level": "basic|intermediate|advanced"
  }}],
  "projects": [{{
    "name": "string",
    "description": "string o null",
    "tech_stack": ["string"],
    "url": "string o null",
    "start_date": "YYYY-MM-DD o null",
    "end_date": "YYYY-MM-DD o null"
  }}]
}}

CV a analizar:
---
{raw_text[:6000]}
---

Responde SOLO con el JSON, sin markdown, sin explicaciones adicionales."""


def _parse_gemini_response(response_text: str) -> dict:
    """Limpia y parsea la respuesta JSON de Gemini."""
    # Remover posibles bloques markdown
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    return json.loads(text)


def _dict_to_profile(data: dict) -> ProfileData:
    """Convierte el dict de Gemini al modelo Pydantic ProfileData."""
    personal = data.get("personal_info", {})
    personal_info = PersonalInfo(
        full_name=personal.get("full_name", "Sin nombre"),
        email=personal.get("email"),
        phone=personal.get("phone"),
        location=personal.get("location"),
        linkedin_url=personal.get("linkedin_url"),
        github_url=personal.get("github_url"),
        summary=personal.get("summary"),
    )

    education = [
        EducationData(
            institution=e["institution"],
            degree=e["degree"],
            field=e.get("field"),
            start_date=_parse_date(e.get("start_date")),
            end_date=_parse_date(e.get("end_date")),
            gpa=e.get("gpa"),
        )
        for e in data.get("education", [])
    ]

    work_experience = [
        WorkExperienceData(
            company=w["company"],
            role=w["role"],
            start_date=_parse_date(w.get("start_date")),
            end_date=_parse_date(w.get("end_date")),
            is_current=w.get("is_current", False),
            description=w.get("description"),
            achievements=w.get("achievements", []),
        )
        for w in data.get("work_experience", [])
    ]

    skills = [
        SkillData(
            name=s["name"],
            category=SkillCategory(s.get("category", "other")),
            level=SkillLevel(s.get("level", "basic")),
        )
        for s in data.get("skills", [])
    ]

    projects = [
        ProjectData(
            name=p["name"],
            description=p.get("description"),
            tech_stack=p.get("tech_stack", []),
            url=p.get("url"),
            start_date=_parse_date(p.get("start_date")),
            end_date=_parse_date(p.get("end_date")),
        )
        for p in data.get("projects", [])
    ]

    return ProfileData(
        personal_info=personal_info,
        education=education,
        work_experience=work_experience,
        skills=skills,
        projects=projects,
    )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


# ── Parser principal ──────────────────────────────────────────────────────────
def parse_cv(pdf_path: Path, guardian: TokenGuardian | None = None) -> ParseResult:
    """
    Parsea un CV PDF y retorna un ProfileData estructurado.

    Si GEMINI_MOCK_MODE=true, usa el fixture en tests/fixtures/gemini/mock_parse_cv_response.json
    Si GEMINI_MOCK_MODE=false, llama a Gemini Pro (verifica cuota con el guardian).
    """
    settings = get_settings()

    # 1. Extraer texto del PDF
    try:
        raw_text = extract_text_from_pdf(pdf_path)
    except Exception as e:
        logger.error(f"Error extrayendo PDF: {e}")
        return ParseResult(success=False, error=str(e))

    # 2. Mock mode
    if settings.gemini_mock_mode:
        logger.info("[yellow]MOCK MODE[/yellow] — Usando fixture de parseo de CV")
        mock_file = FIXTURES_DIR / "mock_parse_cv_response.json"
        if not mock_file.exists():
            return ParseResult(
                success=False, error=f"Fixture no encontrado: {mock_file}"
            )
        with open(mock_file, encoding="utf-8") as f:
            mock_data = json.load(f)
        profile = _dict_to_profile(mock_data)
        return ParseResult(
            success=True, profile=profile, raw_text=raw_text, mock_mode=True
        )

    # 3. Modo real — verificar cuota
    if guardian:
        try:
            guardian.check_quota(GeminiModel.PRO, GeminiOperation.PARSE_CV)
        except Exception as e:
            return ParseResult(success=False, error=f"Cuota agotada: {e}")

    # 4. Llamar a Gemini Pro con el nuevo SDK google-genai
    try:
        from google import genai

        client = genai.Client(api_key=get_settings().gemini_api_key)
        prompt = _build_parse_prompt(raw_text)

        logger.info(
            f"Llamando a Gemini Pro para parsear CV ({len(raw_text)} chars de texto)"
        )
        response = client.models.generate_content(
            model=get_config().gemini_model_pro,
            contents=prompt,
        )

        response_text = response.text
        tokens_in = (
            response.usage_metadata.prompt_token_count if response.usage_metadata else 0
        )
        tokens_out = (
            response.usage_metadata.candidates_token_count
            if response.usage_metadata
            else 0
        )

        data = _parse_gemini_response(response_text)
        profile = _dict_to_profile(data)

        if guardian:
            guardian.record_usage(
                GeminiModel.PRO,
                GeminiOperation.PARSE_CV,
                tokens_in,
                tokens_out,
                cache_hit=False,
            )

        logger.info(
            f"CV parseado: {len(profile.skills)} skills, "
            f"{len(profile.education)} educacion, "
            f"{len(profile.projects)} proyectos"
        )
        return ParseResult(
            success=True,
            profile=profile,
            raw_text=raw_text,
            tokens_used=tokens_in + tokens_out,
        )

    except Exception as e:
        logger.error(f"Error en Gemini Pro: {e}")
        return ParseResult(success=False, raw_text=raw_text, error=str(e))
