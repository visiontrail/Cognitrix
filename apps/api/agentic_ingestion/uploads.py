from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from threading import Lock
from typing import Any

import pandas as pd
from fastapi import UploadFile

from ..config import get_settings
from ..sqlite_support import connect as sqlite_connect
from ..workspaces import get_workspace_service
from .nonstructured_excel import inspect_workbook_structure
from .schema import initialize_sqlite_schema

ALLOWED_EXTENSIONS = {".xlsx"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
MAX_SAMPLE_ROWS_PER_SHEET = 5


class IngestionUploadError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int = 400,
        reasons: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.reasons = reasons or []

    def to_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.reasons:
            detail["reasons"] = self.reasons
        return detail


@dataclass(slots=True)
class IngestionUploadInspectionService:
    db_path: Path
    storage_root: Path
    _lock: Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._initialize_schema()

    async def create_upload_inspection(
        self,
        *,
        workspace_id: str,
        uploaded_by: str,
        files: list[UploadFile],
    ) -> dict[str, Any]:
        normalized_workspace_id = workspace_id.strip()
        normalized_uploaded_by = uploaded_by.strip()
        if not normalized_workspace_id:
            raise IngestionUploadError(
                code="WORKSPACE_ID_REQUIRED",
                message="workspace_id is required",
                status_code=422,
            )
        if not normalized_uploaded_by:
            raise IngestionUploadError(
                code="AUTH_REQUIRED",
                message="user_id is required",
                status_code=401,
            )

        if not files:
            raise IngestionUploadError(
                code="NO_FILES",
                message="At least one Excel file is required",
                status_code=422,
            )

        if len(files) != 1:
            raise IngestionUploadError(
                code="SINGLE_FILE_ONLY",
                message="Upload inspection currently supports exactly one file per request",
                reasons=[f"received={len(files)}"],
                status_code=422,
            )

        upload = files[0]
        filename = upload.filename or "uploaded.xlsx"
        extension = Path(filename).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise IngestionUploadError(
                code="UNSUPPORTED_FILE_TYPE",
                message=f"Unsupported file type: {extension or 'unknown'}",
                reasons=[f"file={filename}", f"allowed={','.join(sorted(ALLOWED_EXTENSIONS))}"],
                status_code=400,
            )

        content = await upload.read()
        size_bytes = len(content)
        if size_bytes == 0:
            raise IngestionUploadError(
                code="EMPTY_FILE",
                message=f"File is empty: {filename}",
                reasons=[f"file={filename}"],
                status_code=400,
            )
        if size_bytes > MAX_FILE_SIZE_BYTES:
            raise IngestionUploadError(
                code="FILE_TOO_LARGE",
                message=f"File exceeds size limit ({MAX_FILE_SIZE_BYTES} bytes): {filename}",
                reasons=[f"file={filename}", f"size_bytes={size_bytes}"],
                status_code=400,
            )

        upload_id = uuid.uuid4().hex
        job_id = uuid.uuid4().hex
        file_hash = hashlib.sha256(content).hexdigest()
        safe_name = _sanitize_filename(filename)
        storage_path = (
            self.storage_root / normalized_workspace_id / upload_id / safe_name
        ).resolve()
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(content)

        sheet_summary, column_summary, sample_preview = self._inspect_workbook(
            workbook_bytes=content,
            filename=filename,
        )

        with self._lock, self._connect() as conn:
            self._assert_workspace_exists(conn, workspace_id=normalized_workspace_id)
            self._ensure_user_record(conn, user_id=normalized_uploaded_by)

            conn.execute(
                """
                INSERT INTO ingestion_uploads (
                    id,
                    workspace_id,
                    uploaded_by,
                    file_name,
                    storage_path,
                    size_bytes,
                    file_hash,
                    sheet_summary,
                    column_summary,
                    sample_preview,
                    status,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'uploaded', ?)
                """,
                (
                    upload_id,
                    normalized_workspace_id,
                    normalized_uploaded_by,
                    filename,
                    str(storage_path),
                    size_bytes,
                    file_hash,
                    json.dumps(sheet_summary, ensure_ascii=False),
                    json.dumps(column_summary, ensure_ascii=False),
                    json.dumps(sample_preview, ensure_ascii=False),
                    _utc_now(),
                ),
            )
            conn.execute(
                """
                INSERT INTO ingestion_jobs (
                    id,
                    workspace_id,
                    upload_id,
                    created_by,
                    status,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, 'uploaded', ?, ?)
                """,
                (
                    job_id,
                    normalized_workspace_id,
                    upload_id,
                    normalized_uploaded_by,
                    _utc_now(),
                    _utc_now(),
                ),
            )
            conn.commit()

        return {
            "upload_id": upload_id,
            "job_id": job_id,
            "workspace_id": normalized_workspace_id,
            "status": "uploaded",
            "file_summary": {
                "file_name": filename,
                "size_bytes": size_bytes,
                "file_hash": file_hash,
                "storage_path": str(storage_path),
            },
            "sheet_summary": sheet_summary,
            "column_summary": column_summary,
            "sample_preview": sample_preview,
            "workbook_structure": sheet_summary.get("workbook_structure"),
        }

    def _inspect_workbook(
        self,
        *,
        workbook_bytes: bytes,
        filename: str,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        # TODO(remove): legacy xlsx pre-parse retained while
        # LEGACY_XLSX_PARSER_ENABLED defaults to true. Scheduled for removal once
        # the Anthropic xlsx skill bootstrap is the default code path (see
        # openspec/changes/add-agent-skills-management/design.md migration plan).
        try:
            excel = pd.ExcelFile(BytesIO(workbook_bytes), engine="openpyxl")
        except Exception as exc:  # pragma: no cover - guarded by API tests
            raise IngestionUploadError(
                code="INVALID_EXCEL_FILE",
                message=f"Unable to parse Excel file: {filename}",
                reasons=[str(exc)],
                status_code=400,
            ) from exc

        if not excel.sheet_names:
            raise IngestionUploadError(
                code="EMPTY_SHEET",
                message=f"Excel file has no usable sheet data: {filename}",
                status_code=400,
            )

        sheet_items: list[dict[str, Any]] = []
        column_items: list[dict[str, Any]] = []
        preview_items: list[dict[str, Any]] = []
        all_columns: list[str] = []

        for sheet_name in excel.sheet_names:
            try:
                frame = excel.parse(sheet_name=sheet_name, dtype=object)
            except Exception as exc:  # pragma: no cover - defensive
                raise IngestionUploadError(
                    code="INVALID_EXCEL_FILE",
                    message=f"Unable to parse Excel sheet: {sheet_name}",
                    reasons=[str(exc)],
                    status_code=400,
                ) from exc
            columns = [str(column).strip() or f"column_{index + 1}" for index, column in enumerate(frame.columns)]
            row_count = int(len(frame))

            sheet_items.append(
                {
                    "sheet_name": sheet_name,
                    "row_count": row_count,
                    "column_count": len(columns),
                }
            )
            column_items.append(
                {
                    "sheet_name": sheet_name,
                    "columns": columns,
                }
            )

            for column in columns:
                if column not in all_columns:
                    all_columns.append(column)

            preview_items.append(
                {
                    "sheet_name": sheet_name,
                    "rows": _build_sample_rows(frame.head(MAX_SAMPLE_ROWS_PER_SHEET)),
                }
            )

        has_any_usable_columns = any(item["column_count"] > 0 for item in sheet_items)
        if not has_any_usable_columns:
            raise IngestionUploadError(
                code="EMPTY_SHEET",
                message=f"Excel file has no usable sheet data: {filename}",
                status_code=400,
            )

        sheet_summary = {
            "sheet_count": len(sheet_items),
            "sheets": sheet_items,
        }
        column_summary = {
            "all_columns": all_columns,
            "by_sheet": column_items,
        }

        workbook_structure = inspect_workbook_structure(workbook_bytes=workbook_bytes)
        if workbook_structure:
            sheet_summary["workbook_structure"] = workbook_structure

        return sheet_summary, column_summary, preview_items

    def _initialize_schema(self) -> None:
        with self._connect() as conn:
            initialize_sqlite_schema(conn)

    def _connect(self) -> sqlite3.Connection:
        return sqlite_connect(self.db_path, foreign_keys=True)

    def _assert_workspace_exists(self, conn: sqlite3.Connection, *, workspace_id: str) -> None:
        row = conn.execute(
            "SELECT id FROM workspaces WHERE id = ? AND status = 'active'",
            (workspace_id,),
        ).fetchone()
        if row is None:
            raise IngestionUploadError(
                code="WORKSPACE_NOT_FOUND",
                message="Workspace not found",
                status_code=404,
            )

    def _ensure_user_record(self, conn: sqlite3.Connection, *, user_id: str) -> None:
        normalized_user = user_id.strip()
        if not normalized_user:
            raise IngestionUploadError(
                code="AUTH_REQUIRED",
                message="user_id is required",
                status_code=401,
            )

        now = _utc_now()
        safe_local_part = re.sub(r"[^a-z0-9._-]+", "-", normalized_user.lower()).strip("-._") or "user"
        fallback_email = f"{safe_local_part}@local.invalid"

        conn.execute(
            """
            INSERT INTO users (id, email, display_name, status, created_at, updated_at)
            VALUES (?, ?, ?, 'active', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                updated_at = excluded.updated_at
            """,
            (normalized_user, fallback_email, normalized_user, now, now),
        )


@lru_cache(maxsize=4)
def _cached_ingestion_upload_service(
    db_path: str,
    storage_root: str,
) -> IngestionUploadInspectionService:
    return IngestionUploadInspectionService(
        db_path=Path(db_path).resolve(),
        storage_root=Path(storage_root).resolve(),
    )


def get_ingestion_upload_service() -> IngestionUploadInspectionService:
    settings = get_settings()
    workspace_service = get_workspace_service()
    storage_root = settings.upload_dir / "agentic_ingestion" / "raw"
    return _cached_ingestion_upload_service(
        str(workspace_service.db_path),
        str(storage_root.resolve()),
    )


def clear_ingestion_upload_service_cache() -> None:
    _cached_ingestion_upload_service.cache_clear()


def _sanitize_filename(raw: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw)
    return safe_name or "uploaded.xlsx"


def _build_sample_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    sample_rows: list[dict[str, Any]] = []
    columns = [str(column).strip() or f"column_{index + 1}" for index, column in enumerate(frame.columns)]
    for row in frame.itertuples(index=False, name=None):
        values = {
            columns[index]: _to_json_safe_value(value)
            for index, value in enumerate(row)
        }
        sample_rows.append(values)
    return sample_rows


def _to_json_safe_value(value: Any) -> Any:
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    if isinstance(value, (datetime, date, time)):
        return value.isoformat()

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:  # pragma: no cover - defensive
            return str(value)

    if isinstance(value, (str, int, float, bool, dict, list)):
        return value

    return str(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
