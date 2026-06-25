"""
Tests para QuestionAnswerer — Motor de respuesta inteligente.
Valida clasificación de preguntas, generación de respuestas por defecto,
y validación de coherencia.
"""

from __future__ import annotations

from datetime import date

import pytest

from jobpilot.automation.question_answerer import (
    FormQuestion,
    QuestionAnswerer,
    QuestionType,
)
from jobpilot.profile.models import (
    EducationData,
    PersonalInfo,
    ProfileData,
    SkillCategory,
    SkillData,
    WorkExperienceData,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture
def sample_profile() -> ProfileData:
    """Perfil de prueba de un desarrollador junior chileno."""
    return ProfileData(
        personal_info=PersonalInfo(
            full_name="Juan Pérez López",
            email="juan.perez@example.com",
            phone="+56912345678",
            location="Santiago, Chile",
            linkedin_url="https://linkedin.com/in/juanperez",
            github_url="https://github.com/juanperez",
            summary="Desarrollador Python junior recién egresado.",
        ),
        education=[
            EducationData(
                institution="Universidad de Chile",
                degree="Ingeniería en Informática",
                field="Informática",
                start_date=date(2019, 3, 1),
                end_date=date(2024, 12, 15),
            ),
        ],
        work_experience=[
            WorkExperienceData(
                company="Startup ABC",
                role="Practicante Python",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 6, 30),
                is_current=False,
                description="Desarrollo backend con FastAPI.",
                achievements=["Implementé API REST"],
            ),
        ],
        skills=[
            SkillData(name="Python", category=SkillCategory.LANGUAGE, level="advanced"),
            SkillData(name="FastAPI", category=SkillCategory.FRAMEWORK, level="intermediate"),
            SkillData(name="PostgreSQL", category=SkillCategory.TOOL, level="intermediate"),
            SkillData(name="Docker", category=SkillCategory.TOOL, level="basic"),
            SkillData(name="Git", category=SkillCategory.TOOL, level="advanced"),
        ],
    )


# ── Tests de clasificación de tipo ────────────────────────────────────────────
class TestQuestionTypeClassification:
    """Verifica que _infer_question_type clasifica correctamente."""

    def test_visa_question(self):
        q = FormQuestion(label="¿Está autorizado para trabajar en Chile?", html_type="radio", options=["Sí", "No"])
        result = QuestionAnswerer._infer_question_type(q)
        assert result == QuestionType.VISA_WORK_PERMIT

    def test_sponsor_question(self):
        q = FormQuestion(label="Do you require visa sponsorship?", html_type="radio", options=["Yes", "No"])
        result = QuestionAnswerer._infer_question_type(q)
        assert result == QuestionType.VISA_WORK_PERMIT

    def test_salary_question(self):
        q = FormQuestion(label="¿Cuál es su pretensión salarial?", html_type="text")
        result = QuestionAnswerer._infer_question_type(q)
        assert result == QuestionType.SALARY

    def test_experience_years(self):
        q = FormQuestion(label="Años de experiencia en Python", html_type="number")
        result = QuestionAnswerer._infer_question_type(q)
        assert result == QuestionType.EXPERIENCE_YEARS

    def test_availability(self):
        q = FormQuestion(label="¿Cuándo puede empezar?", html_type="text")
        result = QuestionAnswerer._infer_question_type(q)
        assert result == QuestionType.AVAILABILITY

    def test_location(self):
        q = FormQuestion(label="¿En qué ciudad se encuentra?", html_type="text")
        result = QuestionAnswerer._infer_question_type(q)
        assert result == QuestionType.LOCATION

    def test_tech_specific(self):
        q = FormQuestion(label="¿Tiene experiencia con Kubernetes?", html_type="radio", options=["Sí", "No"])
        result = QuestionAnswerer._infer_question_type(q)
        assert result == QuestionType.TECH_SPECIFIC

    def test_yes_no_radio(self):
        q = FormQuestion(label="¿Le interesa el cargo?", html_type="radio", options=["Sí", "No"])
        result = QuestionAnswerer._infer_question_type(q)
        assert result == QuestionType.YES_NO

    def test_number_type(self):
        q = FormQuestion(label="Ingrese un número", html_type="number")
        result = QuestionAnswerer._infer_question_type(q)
        assert result == QuestionType.NUMBER

    def test_free_text(self):
        q = FormQuestion(label="Cuéntenos sobre usted", html_type="textarea")
        result = QuestionAnswerer._infer_question_type(q)
        assert result == QuestionType.FREE_TEXT


# ── Tests de respuestas por defecto ───────────────────────────────────────────
class TestDefaultAnswers:
    """Verifica que _answer_defaults genera respuestas coherentes."""

    def test_salary_default(self, sample_profile):
        questions = [
            FormQuestion(label="Pretensión salarial", html_type="text"),
        ]
        result = QuestionAnswerer._answer_defaults(questions, sample_profile)
        assert result.questions[0].answer == "Negociable"
        assert result.questions[0].answer_source == "default"

    def test_availability_not_employed(self, sample_profile):
        questions = [
            FormQuestion(label="Disponibilidad", html_type="text"),
        ]
        result = QuestionAnswerer._answer_defaults(questions, sample_profile)
        assert result.questions[0].answer == "Inmediata"

    def test_availability_employed(self, sample_profile):
        # Marcar experiencia actual
        sample_profile.work_experience[0].is_current = True
        sample_profile.work_experience[0].end_date = None
        questions = [
            FormQuestion(label="Disponibilidad para empezar", html_type="text"),
        ]
        result = QuestionAnswerer._answer_defaults(questions, sample_profile)
        assert result.questions[0].answer == "2 semanas"

    def test_location_default(self, sample_profile):
        questions = [
            FormQuestion(label="Ubicación actual", html_type="text"),
        ]
        result = QuestionAnswerer._answer_defaults(questions, sample_profile)
        assert "Santiago" in result.questions[0].answer

    def test_visa_default(self, sample_profile):
        questions = [
            FormQuestion(label="¿Tiene permiso de trabajo?", html_type="radio", options=["Sí", "No"]),
        ]
        result = QuestionAnswerer._answer_defaults(questions, sample_profile)
        assert result.questions[0].answer == "Sí"

    def test_experience_years_calculated(self, sample_profile):
        questions = [
            FormQuestion(label="Años de experiencia", html_type="number"),
        ]
        result = QuestionAnswerer._answer_defaults(questions, sample_profile)
        # 6 meses de práctica = 0 años (entero)
        assert result.questions[0].answer == "0"

    def test_select_first_option(self, sample_profile):
        questions = [
            FormQuestion(
                label="¿Cuál es su nivel de inglés?",
                html_type="select",
                options=["Básico", "Intermedio", "Avanzado"],
            ),
        ]
        result = QuestionAnswerer._answer_defaults(questions, sample_profile)
        assert result.questions[0].answer == "Básico"
        assert len(result.warnings) > 0  # Debe generar warning


# ── Tests de validación de coherencia ─────────────────────────────────────────
class TestCoherenceValidation:
    """Verifica que _validate_answers detecta incongruencias."""

    def test_inflated_experience(self, sample_profile):
        questions = [
            FormQuestion(
                label="Años de experiencia",
                html_type="number",
                question_type=QuestionType.EXPERIENCE_YEARS,
                answer="10",  # Muy inflado para 6 meses reales
                answer_source="gemini",
            ),
        ]
        warnings = QuestionAnswerer._validate_answers(questions, sample_profile)
        assert len(warnings) > 0
        assert "excede" in warnings[0].lower() or "experiencia" in warnings[0].lower()

    def test_honest_experience_no_warning(self, sample_profile):
        questions = [
            FormQuestion(
                label="Años de experiencia",
                html_type="number",
                question_type=QuestionType.EXPERIENCE_YEARS,
                answer="0",
                answer_source="gemini",
            ),
        ]
        warnings = QuestionAnswerer._validate_answers(questions, sample_profile)
        assert len(warnings) == 0

    def test_tech_affirmed_not_in_profile(self, sample_profile):
        questions = [
            FormQuestion(
                label="¿Tiene experiencia con Ruby on Rails?",
                html_type="radio",
                question_type=QuestionType.TECH_SPECIFIC,
                answer="Sí",
                answer_source="gemini",
            ),
        ]
        warnings = QuestionAnswerer._validate_answers(questions, sample_profile)
        assert len(warnings) > 0
        assert "no listada" in warnings[0].lower()

    def test_tech_affirmed_in_profile(self, sample_profile):
        questions = [
            FormQuestion(
                label="¿Tiene experiencia con Python?",
                html_type="radio",
                question_type=QuestionType.TECH_SPECIFIC,
                answer="Sí",
                answer_source="gemini",
            ),
        ]
        warnings = QuestionAnswerer._validate_answers(questions, sample_profile)
        assert len(warnings) == 0
