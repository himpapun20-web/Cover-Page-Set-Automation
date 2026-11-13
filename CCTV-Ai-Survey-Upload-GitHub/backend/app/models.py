from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
    Integer, JSON, Numeric, String, Text, Time, UniqueConstraint, Uuid, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


def timestamps() -> dict[str, Any]:
    return {
        "created_at": mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False),
        "updated_at": mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False),
    }


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (Index("ix_companies_company_name", "company_name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    registration_no: Mapped[str | None] = mapped_column(String(100))
    logo_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL", use_alter=True, name="fk_companies_logo_asset"))
    address_line_1: Mapped[str | None] = mapped_column(String(255))
    address_line_2: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    fax: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(255))
    default_report_language: Mapped[str] = mapped_column(String(20), default="en", nullable=False)
    created_at: Mapped[datetime] = timestamps()["created_at"]
    updated_at: Mapped[datetime] = timestamps()["updated_at"]
    projects: Mapped[list[Project]] = relationship(back_populates="company")
    users: Mapped[list[User]] = relationship(back_populates="company")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('ADMIN','PROJECT_MANAGER','OPERATOR','VIEWER','AI_SERVICE')", name="ck_users_role"),
        Index("ix_users_company_id", "company_id"),
        Index("ix_users_role_active", "role", "is_active"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    open_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    role: Mapped[str] = mapped_column(String(30), default="VIEWER", nullable=False)
    signature_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL", use_alter=True, name="fk_users_signature_asset"))
    eusr_certificate_no: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = timestamps()["created_at"]
    updated_at: Mapped[datetime] = timestamps()["updated_at"]
    company: Mapped[Company] = relationship(back_populates="users")


class SignupInvitation(Base):
    __tablename__ = "signup_invitations"
    __table_args__ = (
        Index("ix_signup_invitations_company_id", "company_id"),
        Index("ix_signup_invitations_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = timestamps()["created_at"]


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("project_code", name="uq_projects_project_code"),
        CheckConstraint("status IN ('DRAFT','IN_PROGRESS','COMPLETED','ON_HOLD')", name="ck_projects_status"),
        CheckConstraint("report_status IN ('NOT_GENERATED','DRAFT','GENERATED','FINALIZED')", name="ck_projects_report_status"),
        Index("ix_projects_company_id", "company_id"),
        Index("ix_projects_status", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    project_code: Mapped[str] = mapped_column(String(100), nullable=False)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    project_description: Mapped[str | None] = mapped_column(Text)
    client_name: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    report_date: Mapped[date | None] = mapped_column(Date)
    survey_start_date: Mapped[date | None] = mapped_column(Date)
    survey_end_date: Mapped[date | None] = mapped_column(Date)
    tv_reference_no: Mapped[str | None] = mapped_column(String(100))
    client_job_reference: Mapped[str | None] = mapped_column(String(100))
    contractor_job_reference: Mapped[str | None] = mapped_column(String(100))
    contractor_name: Mapped[str | None] = mapped_column(String(255))
    project_manager_name: Mapped[str | None] = mapped_column(String(255))
    project_manager_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    eusr_certificate_no: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", nullable=False)
    report_status: Mapped[str] = mapped_column(String(30), default="NOT_GENERATED", nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = timestamps()["created_at"]
    updated_at: Mapped[datetime] = timestamps()["updated_at"]
    company: Mapped[Company] = relationship(back_populates="projects")
    pipe_sections: Mapped[list[PipeSection]] = relationship(back_populates="project", cascade="all, delete-orphan")


class PipeSection(Base):
    __tablename__ = "pipe_sections"
    __table_args__ = (
        UniqueConstraint("project_id", "pipe_id", "section_reference", name="uq_pipe_sections_project_pipe_ref"),
        CheckConstraint("survey_status IN ('NOT_SURVEYED','IN_PROGRESS','COMPLETED','PARTIAL','ABANDONED')", name="ck_pipe_sections_survey_status"),
        CheckConstraint("survey_length_m IS NULL OR survey_length_m >= 0", name="ck_pipe_sections_length_nonnegative"),
        Index("ix_pipe_sections_project_id", "project_id"),
        Index("ix_pipe_sections_survey_status", "survey_status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    pipe_id: Mapped[str] = mapped_column(String(100), nullable=False)
    section_reference: Mapped[str] = mapped_column(String(100), nullable=False)
    start_manhole: Mapped[str | None] = mapped_column(String(100))
    finish_manhole: Mapped[str | None] = mapped_column(String(100))
    function_code: Mapped[str | None] = mapped_column(String(20))
    function_description: Mapped[str | None] = mapped_column(String(100))
    survey_length_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    pipe_size_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    pipe_shape: Mapped[str | None] = mapped_column(String(100))
    pipe_material_code: Mapped[str | None] = mapped_column(String(50))
    pipe_material_description: Mapped[str | None] = mapped_column(String(255))
    survey_status: Mapped[str] = mapped_column(String(30), default="NOT_SURVEYED", nullable=False)
    survey_abandoned_reason: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)
    defects_summary: Mapped[str | None] = mapped_column(Text)
    site_environment: Mapped[str | None] = mapped_column(Text)
    wincan_report_imported: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    condition_grade: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    recommendation: Mapped[str | None] = mapped_column(Text)
    start_level_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    finish_level_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    geometry_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = timestamps()["created_at"]
    updated_at: Mapped[datetime] = timestamps()["updated_at"]
    project: Mapped[Project] = relationship(back_populates="pipe_sections")
    inspections: Mapped[list[Inspection]] = relationship(back_populates="pipe_section", cascade="all, delete-orphan")


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint("file_type IN ('LOGO','SIGNATURE','VIDEO','PHOTO','SITE_PLAN','SPREADSHEET','PDF','OTHER')", name="ck_assets_file_type"),
        Index("ix_assets_company_id", "company_id"),
        Index("ix_assets_project_id", "project_id"),
        Index("ix_assets_file_type", "file_type"),
        Index("ix_assets_sha256_hash", "sha256_hash"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"))
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(Text)
    file_url: Mapped[str | None] = mapped_column(Text)
    file_type: Mapped[str] = mapped_column(String(20), default="OTHER", nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256_hash: Mapped[str | None] = mapped_column(String(64))
    width_px: Mapped[int | None] = mapped_column(Integer)
    height_px: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = timestamps()["created_at"]
    updated_at: Mapped[datetime] = timestamps()["updated_at"]


class Inspection(Base):
    __tablename__ = "inspections"
    __table_args__ = (
        CheckConstraint("inspection_direction IN ('FORWARD','REVERSE','UPSTREAM','DOWNSTREAM')", name="ck_inspections_direction"),
        CheckConstraint("inspection_status IN ('SCHEDULED','IN_PROGRESS','COMPLETED','PARTIAL','ABANDONED','FAILED')", name="ck_inspections_status"),
        Index("ix_inspections_pipe_section_id", "pipe_section_id"),
        Index("ix_inspections_video_asset_id", "video_asset_id"),
        Index("ix_inspections_status", "inspection_status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    pipe_section_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("pipe_sections.id", ondelete="CASCADE"), nullable=False)
    video_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL"))
    inspection_number: Mapped[int] = mapped_column(Integer, nullable=False)
    inspection_date: Mapped[date | None] = mapped_column(Date)
    inspection_time: Mapped[time | None] = mapped_column(Time)
    inspection_direction: Mapped[str] = mapped_column(String(20), default="DOWNSTREAM", nullable=False)
    operator_name: Mapped[str | None] = mapped_column(String(255))
    vehicle: Mapped[str | None] = mapped_column(String(100))
    camera: Mapped[str | None] = mapped_column(String(100))
    preset_length_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    weather: Mapped[str | None] = mapped_column(String(100))
    pre_cleaned: Mapped[str | None] = mapped_column(String(100))
    legal_status: Mapped[str | None] = mapped_column(String(100))
    upstream_pipe_depth_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    downstream_pipe_depth_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    inspection_status: Mapped[str] = mapped_column(String(30), default="SCHEDULED", nullable=False)
    created_at: Mapped[datetime] = timestamps()["created_at"]
    updated_at: Mapped[datetime] = timestamps()["updated_at"]
    pipe_section: Mapped[PipeSection] = relationship(back_populates="inspections")


class InspectionEvent(Base):
    __tablename__ = "inspection_events"
    __table_args__ = (
        CheckConstraint("event_type IN ('DEFECT','START_NODE','WATER_LEVEL','GENERAL_PHOTO','FINISH_NODE','SITE_PHOTO')", name="ck_inspection_events_type"),
        CheckConstraint("timestamp_seconds >= 0", name="ck_inspection_events_timestamp_nonnegative"),
        CheckConstraint("distance_m >= 0", name="ck_inspection_events_distance_nonnegative"),
        Index("ix_inspection_events_inspection_distance", "inspection_id", "distance_m"),
        Index("ix_inspection_events_video_asset_id", "video_asset_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    inspection_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False)
    video_asset_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    photo_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL"))
    event_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), default="DEFECT", nullable=False)
    timestamp_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    distance_m: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    mscc_code: Mapped[str | None] = mapped_column(String(50))
    clock_position: Mapped[str | None] = mapped_column(String(30))
    observation: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = timestamps()["created_at"]
    updated_at: Mapped[datetime] = timestamps()["updated_at"]


class ReportTemplate(Base):
    __tablename__ = "report_templates"
    __table_args__ = (Index("ix_report_templates_company_active", "company_id", "is_active"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    template_name: Mapped[str] = mapped_column(String(255), nullable=False)
    template_version: Mapped[str] = mapped_column(String(50), default="1.0", nullable=False)
    language: Mapped[str] = mapped_column(String(20), default="en", nullable=False)
    page_size: Mapped[str] = mapped_column(String(20), default="A4", nullable=False)
    cover_layout_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    header_config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    footer_config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = timestamps()["created_at"]
    updated_at: Mapped[datetime] = timestamps()["updated_at"]
    sections: Mapped[list[FixedReportContent]] = relationship(back_populates="template", cascade="all, delete-orphan", order_by="FixedReportContent.display_order")


class FixedReportContent(Base):
    __tablename__ = "fixed_report_contents"
    __table_args__ = (
        UniqueConstraint("template_id", "section_code", "version", name="uq_fixed_report_contents_version"),
        Index("ix_fixed_report_contents_template_order", "template_id", "display_order"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    template_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("report_templates.id", ondelete="CASCADE"), nullable=False)
    section_code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_template: Mapped[str] = mapped_column(Text, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = timestamps()["created_at"]
    updated_at: Mapped[datetime] = timestamps()["updated_at"]
    template: Mapped[ReportTemplate] = relationship(back_populates="sections")
