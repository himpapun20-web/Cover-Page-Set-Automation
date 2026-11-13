from __future__ import annotations

from datetime import date
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import Asset, Company, FixedReportContent, Inspection, PipeSection, Project, ReportTemplate, User

SAMPLE_COMPANY = "Northstar Drainage Services (Synthetic)"
SAMPLE_EMAIL = "admin@example.test"
SAMPLE_PROJECT_CODE = "DEMO-2026-001"
SECTIONS = [
    ("statement", "Statement of Conformity", "This is to certify that qualified personnel have undertaken the coding for this Variation Order and reports are compiled in accordance with the contract specification, the MSCC (5th Edition), the SRM and certified by the undersigned."),
    ("introduction", "1) Introduction", "We have been instructed by {{ client_name }} to conduct Pipe Cleaning and CCTV Survey after the pipe cleaning at {{ location }}\n1.1 Extent of survey is defined in drawing.\n1.2 Purpose of the survey is to investigate the condition of the pipes."),
    ("method", "2) Method Statement", "2.1 Closed Circuit Television (CCTV) underground survey Unit\n\nCCTV is inspecting the internal pipeline condition of sewers and drainage\n\nThe machine run along the pipeline and the image is transmitted to the console unit and then show the monitored and recorded in the hard disk.\n\n2.2 Report Preparation\n\nThe grading and coding in the report is referred to Manual of Sewer Condition Classification 5th Edition (MSCC 5th Edition)"),
    ("summary", "3) Summary of Pipelines Condition & Site Environment", "This schedule is populated from reviewed WinCan VX report data, including pipe condition and site environment."),
    ("appendices", "Appendices", "Appendix I — WinCan VX report summary\nAppendix II — Site layout plan (if provided)"),
]
LEGACY_MARKERS = tuple(bytes.fromhex(value).decode("utf-8") for value in (
    "e69cace5a0b1e5918ae695b4e79086e5b088e6a188",  # prior synthetic introduction
    "e69cace5a0b1e5918ae794b1e5b7b2e4bf9de5ad98",  # prior synthetic method statement
    "e5b088e6a188e585b1",                            # prior synthetic summary
    "e69caae4b88ae8bc89e68896e69caae9979ce881af",  # prior synthetic appendices
    "e69cace7b3bbe7b5b1e79baee5898de4b88de69c83",  # prior synthetic method disclaimer
    "e69cace7af80e4bba5e79baee5898de5b7b2e4bf9de5ad98",
    "e5a0b1e5918ae4be9de6939ae6ada4e5b088e6a188e79baee5898d",
    "e69cace5a0b1e5918ae4be9be5b088e6a188e4babae593a1",
    "e59088e68890e6b8ace8a9a6e8b387e69699",
))
LEGACY_TITLES = {"1. Introduction", "2. Method Statement", "3. Summary of Pipelines Condition & Site Environment", "4. Appendices"}


def seed_demo_data(db: Session, admin_email: str = SAMPLE_EMAIL) -> dict[str, str]:
    project = db.scalar(select(Project).where(Project.project_code == SAMPLE_PROJECT_CODE))
    if project:
        company = db.get(Company, project.company_id)
        if company is None:
            raise RuntimeError(f"Seed project {SAMPLE_PROJECT_CODE} has no associated company")
    else:
        company = db.scalar(select(Company).where(Company.company_name == SAMPLE_COMPANY))
        if not company:
            company = Company(company_name=SAMPLE_COMPANY, registration_no="SYNTHETIC-001", address_line_1="100 Test Works Road", phone="+852 0000 0000", email="reports@example.test", default_report_language="en")
            db.add(company)
            db.flush()
    company.default_report_language = "en"

    user = db.scalar(select(User).where(User.email == admin_email))
    if not user:
        user = User(company_id=company.id, full_name="Demo Project Administrator", email=admin_email, role="ADMIN", is_active=True, eusr_certificate_no="SYNTHETIC-EUSR-0001")
        db.add(user)
        db.flush()
    if not project:
        project = Project(company_id=company.id, project_code=SAMPLE_PROJECT_CODE, project_name="Harbour View Drainage Survey (Synthetic)", project_description="Synthetic sample project for report layout and data-flow checks. Not a real site.", client_name="Example Client (Synthetic)", location="Harbour View, Test District", report_date=date(2026, 10, 15), survey_start_date=date(2026, 10, 12), survey_end_date=date(2026, 10, 13), tv_reference_no="TV-SYN-2026-001", client_job_reference="CLIENT-SYN-001", contractor_job_reference="CONTRACTOR-SYN-001", contractor_name=SAMPLE_COMPANY, project_manager_name="Sample Project Manager", eusr_certificate_no="SYNTHETIC-EUSR-0001", status="IN_PROGRESS", report_status="DRAFT", created_by=user.id)
        db.add(project)
        db.flush()

    pipe = db.scalar(select(PipeSection).where(PipeSection.project_id == project.id, PipeSection.pipe_id == "P-001", PipeSection.section_reference == "MH-A01-MH-A02"))
    if not pipe:
        pipe = PipeSection(project_id=project.id, pipe_id="P-001", section_reference="MH-A01-MH-A02", start_manhole="MH-A01", finish_manhole="MH-A02", function_code="F", function_description="Foul", survey_length_m=42.5, pipe_size_mm=225, pipe_shape="Circular", pipe_material_code="VC", pipe_material_description="Vitrified clay", survey_status="COMPLETED", remarks="Synthetic sample section; not a real site.")
        db.add(pipe)
        db.flush()
    elif pipe.remarks and not pipe.remarks.isascii():
        pipe.remarks = "Synthetic sample section; not a real site."

    asset = db.scalar(select(Asset).where(Asset.project_id == project.id, Asset.file_name == "synthetic-site-plan-metadata.pdf"))
    if not asset:
        placeholder = b"Synthetic metadata only. No site drawing is present."
        asset = Asset(company_id=company.id, project_id=project.id, file_name="synthetic-site-plan-metadata.pdf", storage_key="demo/synthetic/site-plan-metadata", file_type="SITE_PLAN", mime_type="application/pdf", file_size_bytes=len(placeholder), sha256_hash=sha256(placeholder).hexdigest(), metadata_json={"synthetic": True, "metadata_only": True, "note": "No actual drawing is included."}, uploaded_by=user.id)
        db.add(asset)
        db.flush()

    inspection = db.scalar(select(Inspection).where(Inspection.pipe_section_id == pipe.id, Inspection.inspection_number == 1))
    if not inspection:
        inspection = Inspection(pipe_section_id=pipe.id, inspection_number=1, inspection_date=date(2026, 10, 12), inspection_direction="DOWNSTREAM", preset_length_m=42.5, inspection_status="COMPLETED")
        db.add(inspection)
        db.flush()
    else:
        legacy_direction = {"FORWARD": "DOWNSTREAM", "REVERSE": "UPSTREAM"}
        inspection.inspection_direction = legacy_direction.get(inspection.inspection_direction.upper(), inspection.inspection_direction)

    template = db.scalar(select(ReportTemplate).where(ReportTemplate.company_id == company.id, ReportTemplate.template_name.in_(["CCTV Survey Standard", "CCTV Survey Standard (English)", "CCTV Survey Standard (Synthetic)"])).order_by(ReportTemplate.is_default.desc()))
    if not template:
        template = ReportTemplate(company_id=company.id, template_name="CCTV Survey Standard (English)", template_version="2.0", language="en", page_size="A4", cover_layout_json={"display_project_code": True}, header_config_json={"show_location": True, "show_tv_reference": True}, footer_config_json={"show_company": True, "show_page_number": True}, is_default=True, is_active=True)
        db.add(template)
        db.flush()
    else:
        template.language = "en"
        template.template_version = "2.0"
        template.is_active = True
        template.is_default = True

    existing = {section.section_code: section for section in db.scalars(select(FixedReportContent).where(FixedReportContent.template_id == template.id)).all()}
    for order, (code, title, content) in enumerate(SECTIONS, start=1):
        section = existing.get(code)
        if section is None:
            db.add(FixedReportContent(template_id=template.id, section_code=code, title=title, content_template=content, display_order=order, version=1, effective_from=date(2026, 1, 1), created_by=user.id))
        elif section.title in LEGACY_TITLES or any(marker in section.content_template for marker in LEGACY_MARKERS):
            section.title = title
            section.content_template = content
            section.display_order = order
    db.commit()
    return {"company_id": str(company.id), "user_id": str(user.id), "project_id": str(project.id), "pipe_section_id": str(pipe.id), "asset_id": str(asset.id), "inspection_id": str(inspection.id), "template_id": str(template.id)}


def main() -> None:
    with SessionLocal() as db:
        ids = seed_demo_data(db)
    print("Synthetic sample records are ready:", ids)


if __name__ == "__main__":
    main()
