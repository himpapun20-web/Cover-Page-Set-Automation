from __future__ import annotations

import re
from io import BytesIO
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError


MAX_WINCAN_PDF_BYTES = 30 * 1024 * 1024
MAX_WINCAN_PDF_PAGES = 500
FIELD_ALIASES = {
    "pipe_id": ("pipe id", "pipe no", "pipe number", "pipe reference", "pipe ref", "section id", "section no", "asset id", "link id"),
    "section_reference": ("section reference", "section ref"),
    "start_manhole": ("start manhole", "start mh", "start node", "upstream manhole", "upstream node", "from manhole", "from node", "us manhole"),
    "finish_manhole": ("finish manhole", "finish mh", "end manhole", "end mh", "end node", "downstream manhole", "downstream node", "to manhole", "to node", "ds manhole"),
    "function_description": ("function", "function description", "pipe function", "service type"),
    "survey_length_m": ("survey length", "pipe length", "section length", "length"),
    "pipe_size_mm": ("pipe size", "diameter", "nominal diameter", "size"),
    "pipe_material_code": ("material code", "pipe material", "material type", "material"),
    "condition_grade": ("condition grade", "overall grade", "grade"),
    "defects_summary": ("defect description", "defect summary", "defect", "observation", "defects"),
    "site_environment": ("site environment", "environmental notes", "environment"),
    "remarks": ("remarks", "remark", "notes", "comment"),
    "recommendation": ("recommendation", "recommended action", "rehabilitation"),
}
LABELS = {
    alias.casefold(): field
    for field, aliases in FIELD_ALIASES.items()
    for alias in aliases
}


def extract_wincan_pdf(payload: bytes) -> tuple[str, int]:
    if not payload.startswith(b"%PDF-"):
        raise ValueError("The uploaded file is not a valid PDF.")
    if len(payload) > MAX_WINCAN_PDF_BYTES:
        raise ValueError("The WinCan PDF exceeds the 30 MiB upload limit.")
    try:
        reader = PdfReader(BytesIO(payload), strict=True)
        if reader.is_encrypted:
            raise ValueError("The WinCan PDF is password-protected. Upload an unlocked copy.")
        if len(reader.pages) > MAX_WINCAN_PDF_PAGES:
            raise ValueError(f"The WinCan PDF exceeds the {MAX_WINCAN_PDF_PAGES}-page limit.")
        pages = [page.extract_text() or "" for page in reader.pages]
    except (PdfReadError, OSError) as exc:
        raise ValueError("The uploaded file could not be read as a PDF report.") from exc
    text = "\n".join(pages)
    if not text.strip():
        raise ValueError("No selectable text was found in the PDF. Scanned reports need OCR before import.")
    return text, len(pages)


def _labelled_value(line: str) -> tuple[str, str] | None:
    match = re.match(r"^\s*([A-Za-z][A-Za-z /_-]{1,40}?)\s*[:=]\s*(.*?)\s*$", line)
    if not match:
        return None
    label = re.sub(r"\s+", " ", match.group(1).strip().lower())
    field = LABELS.get(label)
    return (field, match.group(2).strip()) if field else None


def _clean_number(value: str) -> str | None:
    match = re.search(r"\d+(?:[.,]\d+)?", value)
    return match.group(0).replace(",", ".") if match else None


def _normalize_row(row: dict[str, Any]) -> dict[str, str | None] | None:
    pipe_id = (row.get("pipe_id") or "").strip().strip(":")
    length = _clean_number(row.get("survey_length_m") or "")
    if not pipe_id or not length:
        return None
    grade = _clean_number(row.get("condition_grade") or "")
    size = _clean_number(row.get("pipe_size_mm") or "")
    material = row.get("pipe_material_code")
    material_code = None
    if material:
        normalized_material = material.strip().upper()
        material_match = re.search(r"\b(VC|CI|DI|CO|PVC|PE)\b", normalized_material)
        material_names = {
            "VITRIFIED CLAY": "VC",
            "CAST IRON": "CI",
            "DUCTILE IRON": "DI",
            "CONCRETE": "CO",
            "POLYVINYL CHLORIDE": "PVC",
            "POLYETHYLENE": "PE",
        }
        material_code = material_match.group(1) if material_match else material_names.get(normalized_material, normalized_material)
    function_description = (row.get("function_description") or row.get("function_code") or "").strip() or None
    site_environment = (row.get("site_environment") or row.get("remarks") or "").strip() or None
    return {
        "pipe_id": pipe_id[:100],
        "section_reference": (row.get("section_reference") or pipe_id).strip()[:100],
        "start_manhole": (row.get("start_manhole") or "").strip() or None,
        "finish_manhole": (row.get("finish_manhole") or "").strip() or None,
        "function_description": function_description,
        "survey_length_m": length,
        "pipe_size_mm": size,
        "pipe_material_code": material_code,
        "condition_grade": grade,
        "defects_summary": (row.get("defects_summary") or "").strip() or None,
        "site_environment": site_environment,
        "remarks": site_environment,
        "recommendation": (row.get("recommendation") or "").strip() or None,
    }


def _parse_labelled_blocks(text: str) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    current: dict[str, str] | None = None
    for line in text.splitlines():
        labelled = _labelled_value(line)
        if not labelled:
            continue
        field, value = labelled
        if field == "pipe_id":
            if current:
                row = _normalize_row(current)
                if row:
                    rows.append(row)
            current = {"pipe_id": value}
        elif current and value:
            if field in {"defects_summary", "site_environment", "recommendation"} and current.get(field):
                current[field] = f"{current[field]} {value}"
            else:
                current[field] = value
    if current:
        row = _normalize_row(current)
        if row:
            rows.append(row)
    return rows


def _header_field(cell: str) -> str | None:
    normalized = re.sub(r"[^a-z ]", " ", cell.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    for field, aliases in FIELD_ALIASES.items():
        if any(normalized == alias or normalized.startswith(f"{alias} ") for alias in aliases):
            return field
    return None


def _parse_table_rows(text: str) -> list[dict[str, str | None]]:
    lines = text.splitlines()
    rows: list[dict[str, str | None]] = []
    for index, line in enumerate(lines):
        headers = re.split(r"\s{2,}|\t+", line.strip())
        fields = [_header_field(cell) for cell in headers]
        if "pipe_id" not in fields or "survey_length_m" not in fields:
            continue
        for candidate in lines[index + 1:]:
            cells = re.split(r"\s{2,}|\t+", candidate.strip())
            if len(cells) != len(fields):
                if rows:
                    break
                continue
            row = {field: cell for field, cell in zip(fields, cells) if field}
            normalized = _normalize_row(row)
            if normalized:
                rows.append(normalized)
    return rows


def parse_wincan_pipe_rows(text: str) -> list[dict[str, str | None]]:
    rows = _parse_labelled_blocks(text)
    if not rows:
        rows = _parse_table_rows(text)
    unique: dict[tuple[str, str], dict[str, str | None]] = {}
    for row in rows:
        key = (str(row["pipe_id"]).casefold(), str(row["section_reference"]).casefold())
        unique[key] = row
    return list(unique.values())
