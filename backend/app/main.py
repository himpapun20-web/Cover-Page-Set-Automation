from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, File, HTTPException, Query, Response, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import current_user, require_roles, router as auth_router
from .database import get_db
from .models import Asset, Company, PipeSection, Project, User
from .reports import render_report_html, render_report_pdf
from .schemas import INPUT_SCHEMAS, WinCanReportInput
from .survey_api import router as survey_router
from .wincan_report import extract_wincan_pdf, parse_wincan_pipe_rows

app = FastAPI(title="CCTV Survey Report Automation API", version="0.1.0", description="CCTV survey records, Dashboard and project-specific report generation API")
app.include_router(auth_router)
app.include_router(survey_router)

MODEL_MAP = {"companies": Company, "users": User, "projects": Project, "pipe-sections": PipeSection, "assets": Asset}
READ_ROLES = ("ADMIN", "PROJECT_MANAGER", "OPERATOR", "VIEWER")
WRITE_ROLES = {
    "companies": ("ADMIN",), "users": ("ADMIN",),
    "projects": ("ADMIN", "PROJECT_MANAGER"),
    "pipe-sections": ("ADMIN", "PROJECT_MANAGER", "OPERATOR"),
    "assets": ("ADMIN", "PROJECT_MANAGER", "OPERATOR"),
}


def serialize(instance: Any) -> dict[str, Any]:
    return jsonable_encoder({
        column.name: getattr(instance, column.name)
        for column in instance.__table__.columns
        if column.name != "password_hash"
    })


def make_router(path: str, model: Any) -> None:
    schema = INPUT_SCHEMAS[path]
    base_path = f"/api/{path}"

    def list_items(db: Session = Depends(get_db), _user: User = Depends(require_roles(*READ_ROLES)), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
        rows = db.scalars(select(model).order_by(model.created_at.desc()).limit(limit).offset(offset)).all()
        return {"items": [serialize(row) for row in rows], "limit": limit, "offset": offset}

    def get_item(item_id: UUID, db: Session = Depends(get_db), _user: User = Depends(require_roles(*READ_ROLES))):
        item = db.get(model, item_id)
        if not item:
            raise HTTPException(404, "The requested record was not found.")
        return serialize(item)

    def create_item(payload: dict[str, Any], db: Session = Depends(get_db), user: User = Depends(require_roles(*WRITE_ROLES[path]))):
        try:
            values = schema.model_validate(payload).model_dump()
        except ValidationError as exc:
            raise HTTPException(422, detail=exc.errors(include_url=False)) from exc
        if model is Project:
            values["created_by"] = user.id
        if model is Asset:
            values["uploaded_by"] = user.id
        item = model(**values)
        db.add(item)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "The record violates a unique, foreign-key or database constraint.") from exc
        db.refresh(item)
        return serialize(item)

    def update_item(item_id: UUID, payload: dict[str, Any], db: Session = Depends(get_db), _user: User = Depends(require_roles(*WRITE_ROLES[path]))):
        item = db.get(model, item_id)
        if not item:
            raise HTTPException(404, "The requested record was not found.")
        try:
            current_values = {name: getattr(item, name) for name in schema.model_fields}
            validated = schema.model_validate(current_values | payload).model_dump()
        except ValidationError as exc:
            raise HTTPException(422, detail=exc.errors(include_url=False)) from exc
        for key in payload:
            setattr(item, key, validated[key])
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "The update violates a unique, foreign-key or database constraint.") from exc
        db.refresh(item)
        return serialize(item)

    def delete_item(item_id: UUID, db: Session = Depends(get_db), _user: User = Depends(require_roles(*WRITE_ROLES[path]))):
        item = db.get(model, item_id)
        if not item:
            raise HTTPException(404, "The requested record was not found.")
        db.delete(item)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "This record is still referenced by related records and cannot be deleted.") from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    endpoints = (
        (list_items, "GET", "", [200]), (get_item, "GET", "/{item_id}", [200, 404]),
        (create_item, "POST", "", [201, 409, 422]), (update_item, "PATCH", "/{item_id}", [200, 404, 409, 422]),
        (delete_item, "DELETE", "/{item_id}", [204, 404, 409]),
    )
    for endpoint, method, suffix, codes in endpoints:
        endpoint.__name__ = f"{path.replace('-', '_')}_{method.lower()}_{'item' if suffix else 'list_or_create'}"
        app.add_api_route(base_path + suffix, endpoint, methods=[method], status_code=201 if method == "POST" else 200, responses={code: {"description": "API response"} for code in codes if code not in (200, 201)})


for resource, resource_model in MODEL_MAP.items():
    make_router(resource, resource_model)


@app.post("/api/projects/{project_id}/wincan-report/preview")
def preview_wincan_report(project_id: UUID, file: UploadFile = File(...), db: Session = Depends(get_db), _user: User = Depends(require_roles(*READ_ROLES))):
    if not db.get(Project, project_id):
        raise HTTPException(404, "The requested project was not found.")
    if Path(file.filename or "").suffix.lower() != ".pdf":
        raise HTTPException(415, "Upload a WinCan VX report in PDF format.")
    payload = file.file.read(30 * 1024 * 1024 + 1)
    try:
        text, page_count = extract_wincan_pdf(payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "page_count": page_count,
        "rows": parse_wincan_pipe_rows(text),
        "text_preview": text[:6000],
    }


@app.post("/api/projects/{project_id}/wincan-report")
def apply_wincan_report(project_id: UUID, payload: WinCanReportInput, db: Session = Depends(get_db), _user: User = Depends(require_roles("ADMIN", "PROJECT_MANAGER", "OPERATOR"))):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "The requested project was not found.")
    seen: set[tuple[str, str]] = set()
    for row in payload.rows:
        key = (row.pipe_id.casefold(), (row.section_reference or row.pipe_id).casefold())
        if key in seen:
            raise HTTPException(422, f"The WinCan report contains duplicate pipe sections: {row.pipe_id}.")
        seen.add(key)

    created = 0
    updated = 0
    try:
        for row in payload.rows:
            section_reference = row.section_reference or row.pipe_id
            pipe = db.scalar(select(PipeSection).where(
                PipeSection.project_id == project.id,
                PipeSection.pipe_id == row.pipe_id,
                PipeSection.section_reference == section_reference,
            ))
            if pipe is None:
                pipe = PipeSection(
                    project_id=project.id,
                    pipe_id=row.pipe_id,
                    section_reference=section_reference,
                    survey_status="COMPLETED",
                )
                db.add(pipe)
                created += 1
            else:
                updated += 1
            pipe.start_manhole = row.start_manhole
            pipe.finish_manhole = row.finish_manhole
            pipe.function_code = row.function_code or pipe.function_code
            pipe.function_description = row.function_description or pipe.function_description
            pipe.survey_length_m = row.survey_length_m
            pipe.pipe_size_mm = row.pipe_size_mm
            pipe.pipe_material_code = row.pipe_material_code
            pipe.condition_grade = row.condition_grade
            pipe.defects_summary = row.defects_summary
            pipe.site_environment = row.site_environment or row.remarks or pipe.site_environment
            pipe.recommendation = row.recommendation
            pipe.wincan_report_imported = True
            pipe.survey_status = "COMPLETED"
        project.report_status = "DRAFT"
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "The WinCan pipe data could not be saved because it conflicts with existing project data.") from exc
    return {"count": len(payload.rows), "created": created, "updated": updated}


@app.get("/api/projects/{project_id}/report-data")
def project_report_data(project_id: UUID, db: Session = Depends(get_db), _user: User = Depends(require_roles(*READ_ROLES))):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "The requested project was not found.")
    pipe_ids = db.scalars(select(PipeSection.id).where(PipeSection.project_id == project_id, PipeSection.wincan_report_imported.is_(True))).all()
    return {"project": serialize(project), "company_name": project.company.company_name, "pipe_section_count": len(pipe_ids)}


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db), _user: User = Depends(require_roles(*READ_ROLES))):
    projects = db.scalars(select(Project).order_by(Project.updated_at.desc())).all()
    project_rows = []
    for project in projects:
        section_count = db.scalar(select(func.count(PipeSection.id)).where(PipeSection.project_id == project.id, PipeSection.wincan_report_imported.is_(True))) or 0
        project_rows.append({"id": str(project.id), "project_code": project.project_code, "project_name": project.project_name, "client_name": project.client_name, "location": project.location, "status": project.status, "report_status": project.report_status, "pipe_section_count": section_count, "report_date": project.report_date})
    pipes_by_status = {key: value for key, value in db.execute(select(PipeSection.survey_status, func.count()).where(PipeSection.wincan_report_imported.is_(True)).group_by(PipeSection.survey_status)).all()}
    return {"totals": {"projects": len(project_rows), "pipe_sections": sum(pipes_by_status.values())}, "pipe_sections_by_status": pipes_by_status, "projects": project_rows}


@app.get("/api/projects/{project_id}/report.html", response_class=HTMLResponse)
def project_report_html(project_id: UUID, db: Session = Depends(get_db), _user: User = Depends(require_roles(*READ_ROLES))):
    try:
        html = render_report_html(db, str(project_id))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return HTMLResponse(html, headers={"Content-Disposition": "inline; filename=cctv-survey-report.html"})


@app.get("/api/projects/{project_id}/report.pdf")
def project_report_pdf(project_id: UUID, db: Session = Depends(get_db), _user: User = Depends(require_roles("ADMIN", "PROJECT_MANAGER"))):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "The requested project was not found.")
    try:
        data = render_report_pdf(db, str(project_id))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    project.report_status = "GENERATED"
    db.commit()
    safe_code = "".join(char for char in project.project_code if char.isalnum() or char in "-_.")[:100] or str(project.id)
    return StreamingResponse(BytesIO(data), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="cctv-survey-{safe_code}.pdf"'})


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "cctv-survey-api", "version": "0.1.0"}


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


DIST_DIR = Path(__file__).resolve().parents[2] / "dist"


@app.get("/{frontend_path:path}", include_in_schema=False)
def serve_frontend(frontend_path: str):
    if frontend_path == "api" or frontend_path.startswith("api/"):
        raise HTTPException(404, "The requested API endpoint was not found.")
    index = DIST_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(404, "The frontend build is not available.")
    requested = (DIST_DIR / frontend_path).resolve()
    if DIST_DIR.resolve() not in requested.parents and requested != DIST_DIR.resolve():
        raise HTTPException(404, "The requested file was not found.")
    if requested.is_file():
        return FileResponse(requested)
    if Path(frontend_path).suffix:
        raise HTTPException(404, "The requested file was not found.")
    return FileResponse(index)
