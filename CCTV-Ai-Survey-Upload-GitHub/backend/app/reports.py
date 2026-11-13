from __future__ import annotations

import base64
from datetime import date
from decimal import Decimal
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
from typing import Any
from uuid import UUID

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

try:
    from weasyprint import HTML
except Exception:  # pragma: no cover - depends on native C libraries at runtime
    HTML = None

from .models import Asset, Company, FixedReportContent, PipeSection, Project, ReportTemplate
from .storage import LocalAssetStorage, storage_key_exists

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html", "xml"]))
MATERIAL_TYPES = {"VC": "Vitrified clay", "CI": "Cast iron", "DI": "Ductile iron", "CO": "Concrete", "PVC": "Polyvinyl chloride", "PE": "Polyethylene"}
MECHANICAL_CLEANING_TERMS = ("settled deposit", "attached deposit", "corrosion product")
CIPP_TERMS = ("crack", "fracture", "broken", "joint")


def value(value: Any, fallback: str = "Not provided") -> str:
    if value is None or value == "":
        return fallback
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return str(value)


def _derived_recommendation(defects: str | None) -> str | None:
    text = (defects or "").casefold()
    recommendations = []
    if any(term in text for term in MECHANICAL_CLEANING_TERMS):
        recommendations.append("Mechanical cleaning to remove settled deposits and corrosion products.")
    if any(term in text for term in CIPP_TERMS):
        recommendations.append("CIPP rehabilitation due to cracks and joint displacement.")
    return " ".join(recommendations) or None


def _data_uri(asset: Asset | None) -> str | None:
    if not asset or not asset.storage_key or not storage_key_exists(asset.storage_key):
        return None
    try:
        with LocalAssetStorage().open(asset.storage_key) as stream:
            payload = stream.read()
    except (OSError, ValueError):
        return None
    mime = asset.mime_type or "image/png"
    return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"


def _company_logo_data_uri() -> str:
    payload = (TEMPLATE_DIR / "company-logo.png").read_bytes()
    return f"data:image/png;base64,{base64.b64encode(payload).decode('ascii')}"


def _cover_background_data_uri() -> str:
    payload = (TEMPLATE_DIR / "report-cover-background.png").read_bytes()
    return f"data:image/png;base64,{base64.b64encode(payload).decode('ascii')}"


def report_context(db: Session, project_id: str) -> dict[str, Any]:
    query = select(Project).options(
        joinedload(Project.company),
        joinedload(Project.pipe_sections),
    ).where(Project.id == UUID(project_id))
    project = db.execute(query).unique().scalar_one_or_none()
    if not project:
        raise LookupError("Project not found.")

    template_query = select(ReportTemplate).options(joinedload(ReportTemplate.sections)).where(
        ReportTemplate.company_id == project.company_id,
        ReportTemplate.is_active.is_(True),
    ).order_by(ReportTemplate.is_default.desc())
    template = db.execute(template_query).unique().scalars().first()
    company: Company = project.company
    fixed_sections: dict[str, dict[str, str]] = {}
    if template:
        template_vars = {
            "client_name": project.client_name or "Not provided", "location": project.location or "Not provided",
            "report_date": value(project.report_date), "tv_reference_no": project.tv_reference_no or "Not provided",
            "project_name": project.project_name, "project_code": project.project_code,
            "project_description": project.project_description or "Not provided", "company_name": company.company_name,
            "project_manager_name": project.project_manager_name or "Not assigned",
            "eusr_certificate_no": project.eusr_certificate_no or "Not provided",
            "survey_start_date": value(project.survey_start_date), "survey_end_date": value(project.survey_end_date),
            "contractor_name": project.contractor_name or "Not provided",
            "client_job_reference": project.client_job_reference or "Not provided",
            "contractor_job_reference": project.contractor_job_reference or "Not provided",
        }
        for fixed in template.sections:
            fixed_sections[fixed.section_code] = {
                "title": fixed.title,
                "content": env.from_string(fixed.content_template).render(**template_vars),
            }

    pipe_rows: list[dict[str, Any]] = []
    report_pipes = [pipe for pipe in project.pipe_sections if pipe.wincan_report_imported]
    for pipe in sorted(report_pipes, key=lambda item: (item.pipe_id, item.section_reference)):
        pipe_rows.append({
            "pipe_id": pipe.pipe_id,
            "section_reference": pipe.section_reference,
            "upstream_manhole": pipe.start_manhole or "Not provided",
            "downstream_manhole": pipe.finish_manhole or "Not provided",
            "function": pipe.function_description or pipe.function_code or "Not provided",
            "length": value(pipe.survey_length_m),
            "size": value(pipe.pipe_size_mm),
            "material_code": pipe.pipe_material_code or "Not provided",
            "material": pipe.pipe_material_description or MATERIAL_TYPES.get((pipe.pipe_material_code or "").upper(), pipe.pipe_material_code or "Not provided"),
            "grade": value(pipe.condition_grade, "Not assessed"),
            "recommendation": pipe.recommendation or _derived_recommendation(pipe.defects_summary) or "Not provided",
            "defects": pipe.defects_summary or "Not provided",
            "remarks": pipe.site_environment or "Not provided",
            "site_environment": pipe.site_environment or "Not provided",
        })

    site_plans = db.scalars(select(Asset).where(Asset.project_id == project.id, Asset.file_type == "SITE_PLAN").order_by(Asset.created_at)).all()
    site_plan_images = []
    for asset in site_plans:
        image_uri = _data_uri(asset) if asset.mime_type and asset.mime_type.startswith("image/") else None
        if image_uri:
            site_plan_images.append({"file_name": asset.file_name, "data_uri": image_uri})
    total_length = sum(float(pipe.survey_length_m or 0) for pipe in report_pipes)
    recommendation_groups = []
    for label, terms, default_recommendation in (
        ("Mechanical Cleaning", MECHANICAL_CLEANING_TERMS, "Mechanical cleaning to remove settled deposits and corrosion products."),
        ("CIPP Rehabilitation", CIPP_TERMS, "CIPP rehabilitation due to cracks and joint displacement."),
    ):
        matching = [
            row for row in pipe_rows
            if any(term in f"{row['defects']} {row['recommendation']}".casefold() for term in terms)
        ]
        if matching:
            recommendation_groups.append({
                "title": label,
                "pipe_ids": ", ".join(row["pipe_id"] for row in matching),
                "pipe_count": len(matching),
                "recommendation": next((row["recommendation"] for row in matching if row["recommendation"] != "Not provided"), default_recommendation),
            })
    defect_summaries = list(dict.fromkeys(
        row["defects"] for row in pipe_rows if row["defects"] != "Not provided"
    ))
    defect_summary = "; ".join(defect_summaries) if defect_summaries else "No defects were identified in the imported WinCan report."
    toc = [
        {"code": "cover", "title": "Cover Page"},
        {"code": "eusr-certificate", "title": "EUSR Certificate"},
        {"code": "contents", "title": "Contents"},
        {"code": "introduction", "title": "1) Introduction"},
        {"code": "method-statement", "title": "2) Method Statement"},
        {"code": "summary", "title": "3) Summary of Pipelines Condition & Site Environment"},
        {"code": "recommendations", "title": "4) Summary of Defective Drainage Recommendation"},
        {"code": "conclusion", "title": "5) Conclusion"},
        {"code": "appendices", "title": "Appendices"},
    ]
    return {
        "project": project,
        "company": company,
        "company_logo_data_uri": _company_logo_data_uri(),
        "cover_background_data_uri": _cover_background_data_uri(),
        "fixed_sections": fixed_sections,
        "pipe_rows": pipe_rows,
        "site_plan_images": site_plan_images,
        "pipe_count": len(pipe_rows),
        "recommendation_groups": recommendation_groups,
        "defect_summary": defect_summary,
        "total_length": f"{total_length:.2f}",
        "generated_on": date.today().strftime("%d/%m/%Y"),
        "toc": toc,
        "header": (template.header_config_json if template else {}) or {},
        "footer": (template.footer_config_json if template else {}) or {},
    }


def render_report_html(db: Session, project_id: str) -> str:
    return env.get_template("cctv_cover_report.html").render(**report_context(db, project_id))


def _find_pdf_browser() -> str | None:
    configured = os.getenv("CCTV_PDF_BROWSER")
    if configured:
        return configured if Path(configured).is_file() else None

    for executable in ("msedge", "chrome", "chromium", "chromium-browser", "google-chrome"):
        browser = shutil.which(executable)
        if browser:
            return browser

    if os.name == "nt":
        roots = (os.getenv("PROGRAMFILES(X86)"), os.getenv("PROGRAMFILES"), os.getenv("LOCALAPPDATA"))
        suffixes = (
            Path("Microsoft/Edge/Application/msedge.exe"),
            Path("Google/Chrome/Application/chrome.exe"),
            Path("Microsoft/Edge SxS/Application/msedge.exe"),
        )
        for root in roots:
            if root:
                for suffix in suffixes:
                    candidate = Path(root) / suffix
                    if candidate.is_file():
                        return str(candidate)
    elif os.name == "darwin":
        for candidate in (
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ):
            if candidate.is_file():
                return str(candidate)
    return None


def _render_pdf_with_browser(html: str) -> bytes:
    browser = _find_pdf_browser()
    if browser is None:
        raise RuntimeError(
            "PDF export requires WeasyPrint's native libraries or a Chromium-based browser. "
            "Install Microsoft Edge or Chrome, or set CCTV_PDF_BROWSER to its executable path."
        )

    with tempfile.TemporaryDirectory(prefix="cctv-report-pdf-") as directory:
        temp_dir = Path(directory)
        html_path = temp_dir / "report.html"
        pdf_path = temp_dir / "report.pdf"
        html_path.write_text(html, encoding="utf-8")
        command = [
            browser,
            "--headless",
            "--disable-gpu",
            "--disable-extensions",
            "--no-pdf-header-footer",
            f"--user-data-dir={temp_dir / 'browser-profile'}",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("The PDF renderer timed out while generating the report.") from exc
        except OSError as exc:
            raise RuntimeError(f"The PDF browser could not be started: {exc}") from exc

        if completed.returncode != 0 or not pdf_path.is_file():
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"The PDF browser failed to generate the report. {detail}".strip())
        result = pdf_path.read_bytes()
        if not result.startswith(b"%PDF-"):
            raise RuntimeError("The PDF browser returned an invalid document.")
        return result


def render_report_pdf(db: Session, project_id: str, output_path: str | Path | None = None) -> bytes:
    html = render_report_html(db, project_id)
    if HTML is None:
        result = _render_pdf_with_browser(html)
    else:
        result = HTML(string=html, base_url=str(TEMPLATE_DIR)).write_pdf()
        if result is None:
            raise RuntimeError("The PDF renderer did not return a PDF document.")
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(result)
    return result
