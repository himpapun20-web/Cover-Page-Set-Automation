from __future__ import annotations

import re
from io import BytesIO
from typing import Any
from collections import defaultdict
from zipfile import BadZipFile

from PIL import Image, ImageOps
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
import pypdfium2 as pdfium
import pytesseract
from pypdf import PdfReader
from pypdf.errors import PdfReadError


MAX_WINCAN_PDF_BYTES = 30 * 1024 * 1024
MAX_WINCAN_PDF_PAGES = 500
MAX_WINCAN_XLSX_BYTES = 30 * 1024 * 1024
MAX_WINCAN_XLSX_SHEETS = 50
MAX_WINCAN_XLSX_ROWS_PER_SHEET = 10000
MAX_WINCAN_XLSX_IMAGES = 1000
FIELD_ALIASES = {
    "pipe_id": ("pipe id", "pipe no", "pipe number", "pipe reference", "pipe ref", "plr", "section id", "section no", "asset id", "link id"),
    "section_reference": ("section reference", "section ref"),
    "start_manhole": ("start manhole", "start mh", "start node", "upstream manhole", "upstream node", "from manhole", "from node", "us manhole"),
    "finish_manhole": ("finish manhole", "finish mh", "end manhole", "end mh", "end node", "downstream manhole", "downstream node", "to manhole", "to mh", "to node", "ds manhole"),
    "function_description": ("function", "function description", "pipe function", "service type", "use"),
    "survey_length_m": ("survey length", "pipe length", "section length", "length"),
    "pipe_size_mm": ("pipe size", "diameter", "nominal diameter", "profile", "size"),
    "pipe_material_code": ("material code", "pipe material", "material type", "material", "mat"),
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
        document = None
        try:
            document = pdfium.PdfDocument(payload)
            pages = []
            for page in document:
                image = page.render(scale=300 / 72).to_pil()
                pages.append(pytesseract.image_to_string(image, lang="eng", config="--psm 1"))
        except pytesseract.pytesseract.TesseractNotFoundError as exc:
            raise ValueError("This scanned report needs OCR. Install Tesseract OCR and try again.") from exc
        except pytesseract.TesseractError as exc:
            raise ValueError("OCR could not read the scanned WinCan report.") from exc
        except (OSError, RuntimeError) as exc:
            raise ValueError("The scanned WinCan report could not be processed with OCR.") from exc
        finally:
            if document is not None:
                document.close()
        text = "\n".join(pages)
    if not text.strip():
        raise ValueError("No readable text was found in the PDF. Check the scan quality and try again.")
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


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _normalize_row(row: dict[str, Any], allow_missing_length: bool = False) -> dict[str, str | None] | None:
    pipe_id = _text(row.get("pipe_id")).strip(":")
    length = _clean_number(_text(row.get("survey_length_m")))
    if not pipe_id or (not length and not allow_missing_length):
        return None
    grade = _clean_number(_text(row.get("condition_grade")))
    size = _clean_number(_text(row.get("pipe_size_mm")))
    material = _text(row.get("pipe_material_code"))
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
    function_description = _text(row.get("function_description") or row.get("function_code")) or None
    if function_description and function_description.casefold() in {"f", "foul"}:
        function_description = "Foul Water"
    elif function_description and function_description.casefold() in {"s", "surface"}:
        function_description = "Surface Water"
    site_environment = _text(row.get("site_environment") or row.get("remarks")) or None
    start_manhole = _text(row.get("start_manhole")) or None
    finish_manhole = _text(row.get("finish_manhole")) or None
    section_reference = _text(row.get("section_reference"))
    if not section_reference:
        section_reference = (
            f"{start_manhole} to {finish_manhole}"
            if start_manhole and finish_manhole else pipe_id
        )
    return {
        "pipe_id": pipe_id[:100],
        "section_reference": section_reference[:100],
        "start_manhole": start_manhole,
        "finish_manhole": finish_manhole,
        "function_description": function_description,
        "survey_length_m": length,
        "pipe_size_mm": size,
        "pipe_material_code": material_code,
        "condition_grade": grade,
        "defects_summary": _text(row.get("defects_summary")) or None,
        "site_environment": site_environment,
        "remarks": site_environment,
        "recommendation": _text(row.get("recommendation")) or None,
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


def _ocr_excel_image(image: Any) -> str:
    try:
        with Image.open(BytesIO(image._data())) as source:
            recognized_image = ImageOps.grayscale(source)
            scale = max(2, min(6, 240 // max(recognized_image.size)))
            if scale > 1:
                recognized_image = recognized_image.resize(
                    (recognized_image.width * scale, recognized_image.height * scale),
                    Image.Resampling.LANCZOS,
                )
            recognized_image = ImageOps.expand(recognized_image, border=12, fill=255)
            text = pytesseract.image_to_string(recognized_image, lang="eng", config="--psm 7")
            return text.strip()
    except pytesseract.pytesseract.TesseractNotFoundError as exc:
        raise ValueError("This Excel workbook stores some pipe values as images. Tesseract OCR is required to read them.") from exc
    except pytesseract.TesseractError as exc:
        raise ValueError("OCR could not read text embedded as images in the Excel workbook.") from exc
    except OSError as exc:
        raise ValueError("An embedded image in the Excel workbook could not be processed.") from exc


def parse_wincan_xlsx(payload: bytes) -> tuple[list[dict[str, str | None]], int]:
    if len(payload) > MAX_WINCAN_XLSX_BYTES:
        raise ValueError("The WinCan Excel file exceeds the 30 MiB upload limit.")
    if not payload.startswith(b"PK"):
        raise ValueError("The uploaded file is not a valid .xlsx workbook.")

    workbook = None
    try:
        workbook = load_workbook(BytesIO(payload), read_only=False, data_only=True)
        if not workbook.worksheets:
            raise ValueError("The Excel workbook does not contain any worksheets.")
        if len(workbook.worksheets) > MAX_WINCAN_XLSX_SHEETS:
            raise ValueError(f"The Excel workbook exceeds the {MAX_WINCAN_XLSX_SHEETS}-worksheet limit.")

        rows: list[dict[str, str | None]] = []
        found_pipe_table = False
        for worksheet in workbook.worksheets:
            if worksheet.max_row and worksheet.max_row > MAX_WINCAN_XLSX_ROWS_PER_SHEET:
                raise ValueError(
                    f"Worksheet '{worksheet.title}' exceeds the {MAX_WINCAN_XLSX_ROWS_PER_SHEET}-row limit."
                )
            if worksheet.max_column and worksheet.max_column > 200:
                raise ValueError(f"Worksheet '{worksheet.title}' exceeds the 200-column limit.")

            values_by_row = list(worksheet.iter_rows(values_only=True))
            headers_by_row: dict[int, dict[str, int]] = {}
            image_field_columns: dict[int, str] = {}
            for row_number, values in enumerate(values_by_row, start=1):
                fields = {
                    field: index
                    for index, value in enumerate(values)
                    if value is not None
                    for field in [_header_field(str(value))]
                    if field
                }
                if not {"pipe_id", "start_manhole", "finish_manhole"}.issubset(fields):
                    continue
                headers_by_row[row_number - 1] = fields
                for field, index in fields.items():
                    merge = next((
                        cell_range for cell_range in worksheet.merged_cells.ranges
                        if cell_range.min_row <= row_number <= cell_range.max_row
                        and cell_range.min_col <= index + 1 <= cell_range.max_col
                    ), None)
                    if merge:
                        for column in range(merge.min_col - 1, merge.max_col):
                            image_field_columns[column] = field
                    else:
                        image_field_columns[index] = field

            if len(worksheet._images) > MAX_WINCAN_XLSX_IMAGES:
                raise ValueError(f"Worksheet '{worksheet.title}' exceeds the {MAX_WINCAN_XLSX_IMAGES}-image limit.")
            images_by_row_field: dict[int, dict[str, list[Any]]] = defaultdict(lambda: defaultdict(list))
            for image in worksheet._images:
                anchor = getattr(image.anchor, "_from", None)
                if anchor is None:
                    continue
                field = image_field_columns.get(anchor.col)
                if field:
                    images_by_row_field[anchor.row][field].append(image)

            columns: dict[str, int] | None = None
            for row_index, values in enumerate(values_by_row):
                row_text = " ".join(_text(value).casefold() for value in values if value is not None)
                if any(marker in row_text for marker in ("defect summary", "observation count", "pipe levels")):
                    columns = None
                    continue
                fields = headers_by_row.get(row_index)
                if fields:
                    columns = {**(columns or {}), **fields}
                    found_pipe_table = True
                    continue
                if columns is None:
                    continue

                pipe_id = _text(values[columns["pipe_id"]]) if columns["pipe_id"] < len(values) else ""
                if not pipe_id or pipe_id.casefold() in {"total", "plr", "pipe id"}:
                    continue
                raw_row: dict[str, str] = {}
                for field, index in columns.items():
                    value = values[index] if index < len(values) else None
                    if value is None:
                        for image in images_by_row_field.get(row_index, {}).get(field, []):
                            value = _ocr_excel_image(image)
                            if value:
                                break
                    raw_row[field] = _text(value)
                normalized = _normalize_row(raw_row, allow_missing_length=True)
                if normalized is None:
                    continue
                rows.append(normalized)
                if len(rows) > 1000:
                    raise ValueError("The Excel workbook contains more than 1,000 pipe sections.")

        if not found_pipe_table:
            raise ValueError(
                "No pipe-summary table was found. Include columns for PLR/pipe ID, upstream node, downstream node, and length."
            )
        if not rows:
            raise ValueError("No pipe sections were found in the Excel workbook.")

        unique: dict[tuple[str, str], dict[str, str | None]] = {}
        occurrence_counts: dict[tuple[str, str], int] = {}
        for row in rows:
            key = (str(row["pipe_id"]).casefold(), str(row["section_reference"]).casefold())
            occurrence_counts[key] = occurrence_counts.get(key, 0) + 1
            if occurrence_counts[key] > 1:
                row["section_reference"] = f"{row['section_reference']} #{occurrence_counts[key]}"[:100]
            unique[(key[0], row["section_reference"].casefold())] = row
        return list(unique.values()), len(workbook.worksheets)
    except (BadZipFile, InvalidFileException, KeyError, OSError) as exc:
        raise ValueError("The uploaded file could not be read as a valid .xlsx workbook.") from exc
    finally:
        if workbook is not None:
            workbook.close()


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
