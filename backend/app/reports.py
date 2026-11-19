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

from .models import Company, FixedReportContent, PipeSection, Project, ReportTemplate

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html", "xml"]))
MATERIAL_TYPES = {"VC": "Vitrified clay", "CI": "Cast iron", "DI": "Ductile iron", "CO": "Concrete", "PVC": "Polyvinyl chloride", "PE": "Polyethylene"}


def value(value: Any, fallback: str = "Not provided") -> str:
    if value is None or value == "":
        return fallback
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return str(value)


def _survey_period(start: date | None, end: date | None) -> str:
    if start and end:
        start_label = value(start)
        end_label = value(end)
        if start.year == end.year and start.month == end.month:
            month_year = start.strftime("%B %Y")
        elif start.year == end.year:
            month_year = f"{start.strftime('%B')}–{end.strftime('%B %Y')}"
        else:
            month_year = f"{start.strftime('%B %Y')}–{end.strftime('%B %Y')}"
        return f"Between {start_label} and {end_label} ({month_year})"
    if start:
        return f"Starting {value(start)} ({start.strftime('%B %Y')})"
    if end:
        return f"Ending {value(end)} ({end.strftime('%B %Y')})"
    return "During the survey period (dates not provided)"


def _unique_pipe_ids(pipes: list[PipeSection]) -> str:
    identifiers: list[str] = []
    seen: set[str] = set()
    for pipe in pipes:
        key = pipe.pipe_id.casefold()
        if key not in seen:
            identifiers.append(pipe.pipe_id)
            seen.add(key)
    return ", ".join(identifiers)


def _unique_phrases(phrases: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        cleaned = phrase.strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            unique.append(cleaned)
            seen.add(key)
    return unique


def _cleaning_reasons(defect_texts: list[str]) -> list[str]:
    text = " ".join(defect_texts).casefold()
    reasons: list[str] = []
    if "settled deposit" in text:
        reasons.append("settled deposits")
    if "attached deposit" in text or "attatched deposit" in text:
        reasons.append("attached deposits")
    if "corrosion product" in text:
        reasons.append("corrosion products")
    return reasons


def _cipp_reasons(defect_texts: list[str]) -> list[str]:
    text = " ".join(defect_texts).casefold()
    reasons: list[str] = []
    if "crack" in text:
        reasons.append("cracks")
    if "fracture" in text:
        reasons.append("fractures")
    if "broken" in text:
        reasons.append("broken sections")
    if "joint" in text:
        if "displaced joint" in text or "joint displacement" in text:
            reasons.append("joint displacement")
        else:
            reasons.append("joint defects")
    return reasons


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
    defect_texts = _unique_phrases([
        pipe.defects_summary for pipe in report_pipes if pipe.defects_summary
    ])
    cleaning_pipes = [
        pipe for pipe in report_pipes
        if pipe.defects_summary and _cleaning_reasons([pipe.defects_summary])
    ]
    cipp_pipes = [
        pipe for pipe in report_pipes
        if pipe.defects_summary and _cipp_reasons([pipe.defects_summary])
    ]
    total_length = sum(
        (pipe.survey_length_m for pipe in report_pipes if pipe.survey_length_m is not None),
        Decimal("0"),
    )
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
            "recommendation": pipe.recommendation or "Not provided",
            "defects": pipe.defects_summary or "Not provided",
            "remarks": pipe.remarks or pipe.site_environment or "Not provided",
            "site_environment": pipe.site_environment or "Not provided",
        })

    return {
        "project": project,
        "company": company,
        "company_logo_data_uri": _company_logo_data_uri(),
        "cover_background_data_uri": _cover_background_data_uri(),
        "fixed_sections": fixed_sections,
        "pipe_rows": pipe_rows,
        "pipe_count": len(pipe_rows),
        "conclusion": {
            "survey_period": _survey_period(project.survey_start_date, project.survey_end_date),
            "section_count": len(report_pipes),
            "total_length": value(total_length),
            "location": project.location or "Not provided",
            "defect_descriptions": defect_texts,
            "cleaning_count": len(cleaning_pipes),
            "cleaning_pipe_ids": _unique_pipe_ids(cleaning_pipes),
            "cleaning_reasons": _cleaning_reasons([
                pipe.defects_summary for pipe in cleaning_pipes if pipe.defects_summary
            ]),
            "cipp_count": len(cipp_pipes),
            "cipp_pipe_ids": _unique_pipe_ids(cipp_pipes),
            "cipp_reasons": _cipp_reasons([
                pipe.defects_summary for pipe in cipp_pipes if pipe.defects_summary
            ]),
        },
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
