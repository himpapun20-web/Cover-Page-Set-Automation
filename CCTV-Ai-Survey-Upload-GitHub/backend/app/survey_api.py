from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import require_roles
from .database import get_db
from .models import Asset, Project, User
from .storage import LocalAssetStorage, storage_key_exists

router = APIRouter(prefix="/api", tags=["site plan assets"])
READ_ROLES = ("ADMIN", "PROJECT_MANAGER", "OPERATOR", "VIEWER")
EDIT_ROLES = ("ADMIN", "PROJECT_MANAGER", "OPERATOR")
MAX_SITE_PLAN_BYTES = int(os.getenv("CCTV_MAX_SITE_PLAN_UPLOAD_BYTES", str(25 * 1024 * 1024)))
SITE_PLAN_MIMES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _serialize_asset(asset: Asset) -> dict[str, Any]:
    return jsonable_encoder({column.name: getattr(asset, column.name) for column in asset.__table__.columns})


def _safe_file_name(file: UploadFile) -> str:
    original = (file.filename or "").replace("\\", "/")
    safe_name = Path(original).name
    if not safe_name or safe_name in {".", ".."} or "\x00" in safe_name:
        raise HTTPException(422, "Provide a valid Site Layout Plan file name.")
    return safe_name


@router.get("/projects/{project_id}/site-plans")
def list_site_plans(project_id: UUID, db: Session = Depends(get_db), _user: User = Depends(require_roles(*READ_ROLES))):
    if not db.get(Project, project_id):
        raise HTTPException(404, "Project not found.")
    assets = db.scalars(select(Asset).where(Asset.project_id == project_id, Asset.file_type == "SITE_PLAN").order_by(Asset.created_at)).all()
    return {"items": [_serialize_asset(asset) for asset in assets if storage_key_exists(asset.storage_key)]}


@router.post("/projects/{project_id}/site-plans", status_code=201)
def upload_site_plan(project_id: UUID, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require_roles(*EDIT_ROLES))):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found.")
    safe_name = _safe_file_name(file)
    extension = Path(safe_name).suffix.lower()
    expected_mime = SITE_PLAN_MIMES.get(extension)
    content_type = (file.content_type or "").lower()
    if expected_mime is None or (content_type and content_type != expected_mime):
        raise HTTPException(415, "Upload a PNG, JPEG or WebP image for the Site Layout Plan.")
    payload = file.file.read(MAX_SITE_PLAN_BYTES + 1)
    if not payload:
        raise HTTPException(422, "The Site Layout Plan file is empty.")
    if len(payload) > MAX_SITE_PLAN_BYTES:
        raise HTTPException(413, "The Site Layout Plan image exceeds the configured 25 MiB limit.")
    try:
        with Image.open(BytesIO(payload)) as image:
            image_format = image.format
            width, height = image.size
            if width < 1 or height < 1 or width * height > 40_000_000:
                raise ValueError("The Site Layout Plan image exceeds the safe pixel limit.")
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(422, "The uploaded Site Layout Plan is not a valid supported image.") from exc
    mime_from_magic = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(image_format or "")
    if mime_from_magic != expected_mime:
        raise HTTPException(415, "The Site Layout Plan file type does not match its file name.")
    storage = LocalAssetStorage()
    stored = storage.save_bytes(safe_name, payload, str(project.id))
    asset = Asset(company_id=project.company_id, project_id=project.id, file_name=stored.file_name, storage_key=stored.storage_key, file_type="SITE_PLAN", mime_type=expected_mime, file_size_bytes=stored.file_size_bytes, sha256_hash=stored.sha256_hash, width_px=width, height_px=height, uploaded_by=user.id, metadata_json={"site_layout_plan": True})
    try:
        db.add(asset)
        project.report_status = "DRAFT"
        db.commit()
        db.refresh(asset)
    except (IntegrityError, OSError, ValueError) as exc:
        db.rollback()
        storage.delete(stored.storage_key)
        raise HTTPException(422, "The Site Layout Plan could not be saved.") from exc
    return _serialize_asset(asset)
