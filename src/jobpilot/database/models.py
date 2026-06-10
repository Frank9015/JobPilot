"""
JobPilot — SQLAlchemy ORM Models
Todas las tablas del sistema definidas con SQLAlchemy 2.0 (Mapped/mapped_column).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


# ── Base ──────────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── Perfil del candidato ──────────────────────────────────────────────────────
class CandidateProfile(Base):
    __tablename__ = "candidate_profile"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    github_url: Mapped[str | None] = mapped_column(Text)
    cv_file_path: Mapped[str | None] = mapped_column(Text)  # ruta al PDF original
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relaciones
    education: Mapped[list["Education"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    work_experience: Mapped[list["WorkExperience"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    skills: Mapped[list["Skill"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    projects: Mapped[list["Project"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    job_scores: Mapped[list["JobScore"]] = relationship(back_populates="profile")
    generated_cvs: Mapped[list["GeneratedCV"]] = relationship(back_populates="profile")


class Education(Base):
    __tablename__ = "education"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidate_profile.id", ondelete="CASCADE"))
    institution: Mapped[str] = mapped_column(Text, nullable=False)
    degree: Mapped[str] = mapped_column(Text, nullable=False)
    field: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[datetime | None] = mapped_column(Date)
    end_date: Mapped[datetime | None] = mapped_column(Date)
    gpa: Mapped[float | None] = mapped_column(Numeric(4, 2))

    profile: Mapped["CandidateProfile"] = relationship(back_populates="education")


class WorkExperience(Base):
    __tablename__ = "work_experience"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidate_profile.id", ondelete="CASCADE"))
    company: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[datetime | None] = mapped_column(Date)
    end_date: Mapped[datetime | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text)
    achievements: Mapped[list[str] | None] = mapped_column(ARRAY(Text))

    profile: Mapped["CandidateProfile"] = relationship(back_populates="work_experience")


class Skill(Base):
    __tablename__ = "skill"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidate_profile.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)   # language, framework, tool, soft
    level: Mapped[str | None] = mapped_column(Text)       # basic, intermediate, advanced

    profile: Mapped["CandidateProfile"] = relationship(back_populates="skills")


class Project(Base):
    __tablename__ = "project"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidate_profile.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    tech_stack: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    url: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[datetime | None] = mapped_column(Date)
    end_date: Mapped[datetime | None] = mapped_column(Date)

    profile: Mapped["CandidateProfile"] = relationship(back_populates="projects")


# ── Ofertas laborales ─────────────────────────────────────────────────────────
class JobOffer(Base):
    __tablename__ = "job_offer"
    __table_args__ = (UniqueConstraint("portal", "external_id", name="uq_portal_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    portal: Mapped[str] = mapped_column(Text, nullable=False)   # linkedin, bumeran, etc.
    external_id: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    company: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    modality: Mapped[str | None] = mapped_column(Text)          # remote, hybrid, onsite
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(Text, default="CLP")
    description: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[str | None] = mapped_column(Text)
    raw_html: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(Text, default="new")
    # new | scored | cv_ready | applied | rejected | error

    # Relaciones
    score: Mapped["JobScore | None"] = relationship(back_populates="job_offer", uselist=False)
    generated_cv: Mapped["GeneratedCV | None"] = relationship(back_populates="job_offer", uselist=False)
    application: Mapped["Application | None"] = relationship(back_populates="job_offer", uselist=False)


# ── Scoring ───────────────────────────────────────────────────────────────────
class JobScore(Base):
    __tablename__ = "job_score"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    job_offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_offer.id"))
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidate_profile.id"))
    total_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    skill_match: Mapped[float | None] = mapped_column(Numeric(5, 2))
    experience_match: Mapped[float | None] = mapped_column(Numeric(5, 2))
    education_match: Mapped[float | None] = mapped_column(Numeric(5, 2))
    location_match: Mapped[float | None] = mapped_column(Numeric(5, 2))
    salary_match: Mapped[float | None] = mapped_column(Numeric(5, 2))
    gemini_reasoning: Mapped[str | None] = mapped_column(Text)
    score_method: Mapped[str] = mapped_column(Text, default="gemini")  # gemini | heuristic
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job_offer: Mapped["JobOffer"] = relationship(back_populates="score")
    profile: Mapped["CandidateProfile"] = relationship(back_populates="job_scores")


# ── CV Generado ───────────────────────────────────────────────────────────────
class GeneratedCV(Base):
    __tablename__ = "generated_cv"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    job_offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_offer.id"))
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidate_profile.id"))
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    emphasis_notes: Mapped[str | None] = mapped_column(Text)
    gemini_prompt: Mapped[str | None] = mapped_column(Text)
    adaptation_method: Mapped[str] = mapped_column(Text, default="gemini")  # gemini | template_only
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job_offer: Mapped["JobOffer"] = relationship(back_populates="generated_cv")
    profile: Mapped["CandidateProfile"] = relationship(back_populates="generated_cvs")
    application: Mapped["Application | None"] = relationship(back_populates="generated_cv", uselist=False)


# ── Postulaciones ─────────────────────────────────────────────────────────────
class Application(Base):
    __tablename__ = "application"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    job_offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_offer.id"))
    generated_cv_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("generated_cv.id"))
    status: Mapped[str] = mapped_column(Text, default="pending")
    # pending | in_progress | completed | failed | needs_human
    portal_app_id: Mapped[str | None] = mapped_column(Text)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    job_offer: Mapped["JobOffer"] = relationship(back_populates="application")
    generated_cv: Mapped["GeneratedCV | None"] = relationship(back_populates="application")
    interventions: Mapped[list["HumanIntervention"]] = relationship(back_populates="application", cascade="all, delete-orphan")


# ── Audit Log ─────────────────────────────────────────────────────────────────
class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    # scrape | score | generate_cv | apply | intervention | session_check
    status: Mapped[str | None] = mapped_column(Text)
    # success | error | skipped | waiting_human
    detail: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ── Intervención Humana ───────────────────────────────────────────────────────
class HumanIntervention(Base):
    __tablename__ = "human_intervention"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)  # captcha | mfa | unknown_question | error
    question: Mapped[str | None] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    notified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notification_channel: Mapped[str | None] = mapped_column(Text)  # console | telegram

    application: Mapped["Application"] = relationship(back_populates="interventions")


# ── Estado de Sesiones ────────────────────────────────────────────────────────
class SessionStatus(Base):
    __tablename__ = "session_status"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    portal: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="expired")
    # active | suspicious | expired
    reason: Mapped[str | None] = mapped_column(Text)
    session_file: Mapped[str | None] = mapped_column(Text)
    last_checked: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_active: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ── Gemini Cache ──────────────────────────────────────────────────────────────
class GeminiCache(Base):
    __tablename__ = "gemini_cache"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    cache_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    input_hash: Mapped[str] = mapped_column(Text, nullable=False)
    output: Mapped[dict] = mapped_column(JSONB, nullable=False)
    tokens_used: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ── Gemini Usage Log ──────────────────────────────────────────────────────────
class GeminiUsageLog(Base):
    __tablename__ = "gemini_usage_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
