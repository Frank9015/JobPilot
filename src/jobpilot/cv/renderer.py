"""
JobPilot — CV Renderer
Renderiza el CV adaptado a PDF usando Jinja2 (HTML) + Playwright (PDF).
Reemplaza WeasyPrint que no funciona en Windows sin GTK nativo.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from jobpilot.core.config import get_config
from jobpilot.core.logger import get_logger
from jobpilot.cv.generator import AdaptedCV
from jobpilot.profile.models import ProfileData, SkillCategory

logger = get_logger("cv.renderer")

TEMPLATES_DIR = Path(__file__).parent / "templates"


class CVRenderer:
    """
    Renderiza un CV adaptado a PDF profesional.

    Pipeline: ProfileData + AdaptedCV → Jinja2 HTML → Playwright PDF

    Uso:
        renderer = CVRenderer()
        pdf_path = renderer.render(profile, adapted_cv, "output.pdf")
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=False,
        )

    def render(
        self,
        profile: ProfileData,
        adapted_cv: AdaptedCV,
        output_path: Path | str,
    ) -> Path:
        """
        Genera un PDF del CV adaptado.
        Retorna la ruta del archivo PDF generado.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 1. Renderizar HTML con Jinja2
        html_content = self._render_html(profile, adapted_cv)

        # 2. Convertir HTML a PDF con Playwright
        self._html_to_pdf(html_content, output_path)

        file_size_kb = output_path.stat().st_size / 1024
        logger.info(f"CV PDF generado: {output_path} ({file_size_kb:.1f} KB)")
        return output_path

    def _render_html(self, profile: ProfileData, adapted_cv: AdaptedCV) -> str:
        """Renderiza el template HTML con los datos del perfil y adaptaciones."""
        template = self._env.get_template("cv_template.html")

        # Filtrar skills: solo tecnicos para el CV (soft skills aparte o excluidos)
        tech_skills = [s for s in profile.skills if s.category != SkillCategory.SOFT]

        # Determinar resumen a usar
        summary = adapted_cv.adapted_summary or profile.personal_info.summary or ""

        # Secciones con fallback sensato
        sections_order = adapted_cv.sections_order
        if not sections_order:
            if profile.work_experience:
                sections_order = ["experience", "skills", "projects", "education"]
            else:
                sections_order = ["skills", "projects", "education"]

        html = template.render(
            personal_info=profile.personal_info,
            summary=summary,
            sections_order=sections_order,
            skills=tech_skills,
            highlighted_skills=adapted_cv.highlighted_skills,
            work_experience=profile.work_experience,
            education=profile.education,
            projects=profile.projects,
            highlighted_projects=adapted_cv.highlighted_projects,
            reformulated_descriptions=adapted_cv.reformulated_descriptions,
        )
        return html

    def _html_to_pdf(self, html_content: str, output_path: Path) -> None:
        """Convierte HTML renderizado a PDF usando Playwright Chromium."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.set_content(html_content, wait_until="networkidle")

            page.pdf(
                path=str(output_path),
                format="Letter",
                margin={
                    "top": "15mm",
                    "bottom": "15mm",
                    "left": "15mm",
                    "right": "15mm",
                },
                print_background=True,
            )

            browser.close()

    def render_preview_html(
        self,
        profile: ProfileData,
        adapted_cv: AdaptedCV,
        output_path: Path | str,
    ) -> Path:
        """Genera solo el HTML para preview sin PDF (mas rapido)."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        html = self._render_html(profile, adapted_cv)
        output_path.write_text(html, encoding="utf-8")
        logger.info(f"CV HTML preview: {output_path}")
        return output_path
