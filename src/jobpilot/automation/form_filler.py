"""
JobPilot — Form Filler
Utilidades para detección y llenado de campos en formularios web.
Gestiona campos estándar y preguntas adicionales de postulación.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from jobpilot.core.logger import get_logger
from jobpilot.profile.models import ProfileData

logger = get_logger("automation.form_filler")


@dataclass
class FormField:
    """Campo detectado en un formulario web."""
    label: str
    field_type: str  # text, email, tel, select, radio, checkbox, file, textarea, number
    selector: str
    value: str | None = None
    options: list[str] = field(default_factory=list)  # Para select/radio
    required: bool = False
    filled: bool = False


# ── Mapeo de preguntas estándar a campos del perfil ───────────────────────────
# Cada entrada: (patrones_regex, campo_perfil_o_respuesta_fija)
STANDARD_QUESTIONS: list[tuple[list[str], str]] = [
    # Nombre
    (["first.?name", "nombre", "primer nombre"], "profile.first_name"),
    (["last.?name", "apellido"], "profile.last_name"),
    (["full.?name", "nombre completo"], "profile.full_name"),

    # Contacto
    (["email", "correo", "e-mail"], "profile.email"),
    (["phone", "telefono", "celular", "movil", "tel[eé]fono"], "profile.phone"),

    # Ubicación
    (["city", "ciudad"], "profile.city"),
    (["country", "pa[ií]s"], "Chile"),
    (["location", "ubicaci[oó]n"], "profile.location"),

    # Experiencia
    (["years?.?of.?experience", "a[nñ]os?.?de?.?experiencia", "experience.?years"], "profile.years_of_experience"),
    (["current.?title", "cargo.?actual", "puesto.?actual"], "profile.current_title"),

    # Autorizaciones
    (["authorized?.?to?.?work", "autorizad[oa]?.?para?.?trabajar", "permiso.?de?.?trabajo"], "Si"),
    (["legal.?right", "derecho.?legal"], "Si"),
    (["require.?sponsor", "requiere.?sponsor", "visa", "necesita.?sponsor"], "No"),

    # Disponibilidad
    (["start.?date", "fecha.?inicio", "disponibilidad", "cuando.?puede", "cu[aá]ndo"], "Inmediata"),
    (["notice.?period", "periodo.?de?.?aviso", "preaviso"], "Inmediata"),
    (["willing.?to?.?relocate", "dispon[ie]ble.?para?.?mudarse", "reubicaci"], "Si"),

    # Sueldo
    (["salary", "sueldo", "remuneraci", "pretension.?salarial", "renta"], "profile.salary_expectation"),
    (["expected.?salary", "expectativa.?salarial"], "profile.salary_expectation"),

    # LinkedIn / Portfolio
    (["linkedin", "perfil.?linkedin"], "profile.linkedin_url"),
    (["github", "portfolio", "portafolio"], "profile.github_url"),
    (["website", "sitio.?web", "p[aá]gina.?web"], "profile.github_url"),
]


def detect_fields(page) -> list[FormField]:
    """
    Escanea la página actual y retorna una lista de campos del formulario.
    Detecta inputs, selects, textareas y file uploads.
    """
    fields: list[FormField] = []

    # Inputs de texto, email, tel, number
    for input_type in ["text", "email", "tel", "number", "url"]:
        inputs = page.locator(f'input[type="{input_type}"]').all()
        for inp in inputs:
            label = _get_label(page, inp)
            fields.append(FormField(
                label=label,
                field_type=input_type,
                selector=_build_selector(inp),
                required=_is_required(inp),
            ))

    # Inputs sin tipo (default=text)
    inputs_no_type = page.locator('input:not([type])').all()
    for inp in inputs_no_type:
        label = _get_label(page, inp)
        fields.append(FormField(
            label=label,
            field_type="text",
            selector=_build_selector(inp),
            required=_is_required(inp),
        ))

    # Textareas
    textareas = page.locator("textarea").all()
    for ta in textareas:
        label = _get_label(page, ta)
        fields.append(FormField(
            label=label,
            field_type="textarea",
            selector=_build_selector(ta),
            required=_is_required(ta),
        ))

    # Selects
    selects = page.locator("select").all()
    for sel in selects:
        label = _get_label(page, sel)
        options = [opt.inner_text() for opt in sel.locator("option").all()]
        fields.append(FormField(
            label=label,
            field_type="select",
            selector=_build_selector(sel),
            options=options,
            required=_is_required(sel),
        ))

    # File inputs
    file_inputs = page.locator('input[type="file"]').all()
    for fi in file_inputs:
        label = _get_label(page, fi)
        fields.append(FormField(
            label=label,
            field_type="file",
            selector=_build_selector(fi),
        ))

    # Radio buttons (agrupar por name)
    radios = page.locator('input[type="radio"]').all()
    radio_groups: dict[str, list] = {}
    for radio in radios:
        name = radio.get_attribute("name") or "unknown"
        if name not in radio_groups:
            radio_groups[name] = []
        radio_groups[name].append(radio)

    for name, group in radio_groups.items():
        label = _get_label(page, group[0])
        options = []
        for r in group:
            r_label = _get_label(page, r)
            if r_label and r_label != label:
                options.append(r_label)
        fields.append(FormField(
            label=label,
            field_type="radio",
            selector=f'input[type="radio"][name="{name}"]',
            options=options,
        ))

    logger.debug(f"Detectados {len(fields)} campos en formulario")
    return fields


def fill_field(page, field: FormField, value: str) -> bool:
    """Llena un campo individual del formulario. Retorna True si exitoso."""
    try:
        if field.field_type == "file":
            page.locator(field.selector).set_input_files(value)
            field.filled = True
            return True

        if field.field_type == "select":
            # Intentar seleccionar por valor o texto
            select = page.locator(field.selector)
            try:
                select.select_option(label=value)
            except Exception:
                try:
                    select.select_option(value=value)
                except Exception:
                    # Intentar match parcial
                    for opt in field.options:
                        if value.lower() in opt.lower():
                            select.select_option(label=opt)
                            break
            field.filled = True
            return True

        if field.field_type == "radio":
            # Buscar el radio que coincida con el valor
            radios = page.locator(field.selector).all()
            for radio in radios:
                r_label = _get_label(page, radio)
                r_value = radio.get_attribute("value") or ""
                if value.lower() in (r_label or "").lower() or value.lower() in r_value.lower():
                    radio.click()
                    field.filled = True
                    return True
            return False

        if field.field_type in ("text", "email", "tel", "number", "url", "textarea"):
            element = page.locator(field.selector)
            element.click()
            element.fill("")  # Limpiar
            element.fill(value)
            field.filled = True
            return True

        return False

    except Exception as e:
        logger.warning(f"Error llenando campo '{field.label}': {e}")
        return False


def answer_standard_question(label: str, profile: ProfileData) -> str | None:
    """
    Mapea una pregunta estándar de formulario a la respuesta del perfil.
    Retorna None si la pregunta es desconocida (requiere intervención humana).
    """
    label_lower = label.lower().strip()

    for patterns, answer_key in STANDARD_QUESTIONS:
        for pattern in patterns:
            if re.search(pattern, label_lower, re.IGNORECASE):
                return _resolve_answer(answer_key, profile)

    # Pregunta desconocida
    logger.info(f"Pregunta desconocida: '{label}' — requiere intervencion humana")
    return None


def _resolve_answer(key: str, profile: ProfileData) -> str:
    """Resuelve una clave de respuesta contra el perfil."""
    if not key.startswith("profile."):
        return key  # Respuesta fija

    field_name = key.replace("profile.", "")

    mapping = {
        "first_name": lambda: profile.personal_info.full_name.split()[0] if profile.personal_info.full_name else "",
        "last_name": lambda: " ".join(profile.personal_info.full_name.split()[1:]) if profile.personal_info.full_name else "",
        "full_name": lambda: profile.personal_info.full_name or "",
        "email": lambda: profile.personal_info.email or "",
        "phone": lambda: profile.personal_info.phone or "",
        "city": lambda: (profile.personal_info.location or "").split(",")[0].strip(),
        "location": lambda: profile.personal_info.location or "",
        "linkedin_url": lambda: profile.personal_info.linkedin_url or "",
        "github_url": lambda: profile.personal_info.github_url or "",
        "current_title": lambda: _get_current_title(profile),
        "years_of_experience": lambda: str(_calculate_years(profile)),
        "salary_expectation": lambda: "Negociable",
    }

    resolver = mapping.get(field_name)
    if resolver:
        return resolver()

    return ""


def _get_current_title(profile: ProfileData) -> str:
    """Obtiene el título actual del candidato."""
    for exp in profile.work_experience:
        if exp.is_current:
            return exp.role
    if profile.work_experience:
        return profile.work_experience[0].role
    # Sin experiencia — usar educación
    if profile.education:
        return f"Egresado de {profile.education[0].degree}"
    return ""


def _calculate_years(profile: ProfileData) -> int:
    """Calcula años totales de experiencia laboral."""
    total_days = 0
    for exp in profile.work_experience:
        if exp.start_date:
            end = exp.end_date or date.today()
            total_days += (end - exp.start_date).days

    return max(0, total_days // 365)


def _get_label(page, element) -> str:
    """Extrae el label de un elemento de formulario."""
    try:
        # 1. aria-label
        aria = element.get_attribute("aria-label")
        if aria:
            return aria.strip()

        # 2. placeholder
        placeholder = element.get_attribute("placeholder")
        if placeholder:
            return placeholder.strip()

        # 3. Label asociado por for/id
        elem_id = element.get_attribute("id")
        if elem_id:
            label_el = page.locator(f'label[for="{elem_id}"]')
            if label_el.count() > 0:
                return label_el.first.inner_text().strip()

        # 4. Label padre
        parent_label = element.locator("xpath=ancestor::label")
        if parent_label.count() > 0:
            return parent_label.first.inner_text().strip()

        # 5. name attribute como fallback
        name = element.get_attribute("name")
        if name:
            return name.replace("_", " ").replace("-", " ").strip()

    except Exception:
        pass

    return ""


def _build_selector(element) -> str:
    """Construye un selector CSS para un elemento."""
    try:
        elem_id = element.get_attribute("id")
        if elem_id:
            return f"#{elem_id}"

        name = element.get_attribute("name")
        tag = element.evaluate("el => el.tagName.toLowerCase()")
        if name:
            return f'{tag}[name="{name}"]'

        # Fallback: usar data-testid o clase
        test_id = element.get_attribute("data-testid")
        if test_id:
            return f'[data-testid="{test_id}"]'

        cls = element.get_attribute("class")
        if cls:
            first_class = cls.split()[0]
            return f"{tag}.{first_class}"

    except Exception:
        pass

    return "input"


def _is_required(element) -> bool:
    """Verifica si un campo es requerido."""
    try:
        return element.get_attribute("required") is not None or \
               element.get_attribute("aria-required") == "true"
    except Exception:
        return False
