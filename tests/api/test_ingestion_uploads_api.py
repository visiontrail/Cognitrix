from __future__ import annotations

import sqlite3
from io import BytesIO
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from apps.api.agentic_ingestion.uploads import clear_ingestion_upload_service_cache
from apps.api.audit import clear_audit_logger_cache
from apps.api.auth import clear_auth_cache
from apps.api.chat import clear_chat_stream_service_cache
from apps.api.config import get_settings
from apps.api.datasets import clear_dataset_service_cache
from apps.api.main import app
from apps.api.semantic import clear_semantic_cache
from apps.api.table_catalog import clear_table_catalog_service_cache
from apps.api.tool_calling import clear_tool_calling_service_cache
from apps.api.views import clear_view_storage_service_cache
from apps.api.workspaces import clear_workspace_service_cache
from tests.auth_utils import auth_headers, expect_error_code


def _set_minimal_env(monkeypatch, tmp_path: Path, *, ingestion_enabled: bool) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'workspace-state.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AI_API_KEY", "test-ai-key")
    monkeypatch.setenv("AI_MODEL", "deepseek-chat")
    monkeypatch.setenv("AI_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AGENTIC_INGESTION_ENABLED", "true" if ingestion_enabled else "false")
    get_settings.cache_clear()
    clear_auth_cache()
    clear_audit_logger_cache()
    clear_chat_stream_service_cache()
    clear_dataset_service_cache()
    clear_semantic_cache()
    clear_tool_calling_service_cache()
    clear_view_storage_service_cache()
    clear_workspace_service_cache()
    clear_table_catalog_service_cache()
    clear_ingestion_upload_service_cache()


def _excel_bytes() -> bytes:
    roster = pd.DataFrame(
        [
            {"Employee ID": "E-001", "Name": "Alice", "Department": "HR"},
            {"Employee ID": "E-002", "Name": "Bob", "Department": "PM"},
        ]
    )
    summary = pd.DataFrame(
        [
            {"Metric": "Total", "Value": 2},
            {"Metric": "Active", "Value": 2},
        ]
    )

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        roster.to_excel(writer, index=False, sheet_name="Roster")
        summary.to_excel(writer, index=False, sheet_name="Summary")

    return buffer.getvalue()


def _upload_file_payload() -> list[tuple[str, tuple[str, bytes, str]]]:
    return [
        (
            "files",
            (
                "roster.xlsx",
                _excel_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        )
    ]


def _nonstructured_project_payload() -> list[tuple[str, tuple[str, bytes, str]]]:
    sample_path = (
        Path(__file__).resolve().parents[2]
        / "sample_data"
        / "project_management_nonstructure.xlsx"
    )
    return [
        (
            "files",
            (
                "project_management_nonstructure.xlsx",
                sample_path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        )
    ]


def test_ingestion_upload_creates_upload_and_job_records(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=True)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")

        workspace_response = client.post(
            "/workspaces",
            json={"name": "Ingestion Upload Workspace"},
            headers=owner_headers,
        )
        assert workspace_response.status_code == 200
        workspace_id = workspace_response.json()["workspace_id"]

        response = client.post(
            "/ingestion/uploads",
            data={"workspace_id": workspace_id},
            headers=owner_headers,
            files=_upload_file_payload(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["upload_id"]
    assert payload["job_id"]
    assert payload["workspace_id"] == workspace_id
    assert payload["status"] == "uploaded"
    assert payload["file_summary"]["file_name"] == "roster.xlsx"
    assert payload["file_summary"]["size_bytes"] > 0
    assert len(payload["file_summary"]["file_hash"]) == 64

    storage_path = Path(payload["file_summary"]["storage_path"])
    assert storage_path.exists()

    sheet_summary = payload["sheet_summary"]
    assert sheet_summary["sheet_count"] == 2
    assert {item["sheet_name"] for item in sheet_summary["sheets"]} == {"Roster", "Summary"}

    column_summary = payload["column_summary"]
    assert "Employee ID" in column_summary["all_columns"]
    assert "Metric" in column_summary["all_columns"]

    sample_preview = payload["sample_preview"]
    assert len(sample_preview) == 2
    assert sample_preview[0]["rows"]

    db_path = tmp_path / "workspace-state.db"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        upload_row = conn.execute(
            "SELECT id, workspace_id, status FROM ingestion_uploads WHERE id = ?",
            (payload["upload_id"],),
        ).fetchone()
        assert upload_row is not None
        assert str(upload_row["workspace_id"]) == workspace_id
        assert str(upload_row["status"]) == "uploaded"

        job_row = conn.execute(
            "SELECT id, upload_id, workspace_id, status FROM ingestion_jobs WHERE id = ?",
            (payload["job_id"],),
        ).fetchone()
        assert job_row is not None
        assert str(job_row["upload_id"]) == payload["upload_id"]
        assert str(job_row["workspace_id"]) == workspace_id
        assert str(job_row["status"]) == "uploaded"


def test_ingestion_upload_returns_neutral_structure_for_matrix_workbook(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=True)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        workspace_response = client.post(
            "/workspaces",
            json={"name": "Matrix Workbook Workspace"},
            headers=owner_headers,
        )
        assert workspace_response.status_code == 200
        workspace_id = workspace_response.json()["workspace_id"]

        response = client.post(
            "/ingestion/uploads",
            data={"workspace_id": workspace_id},
            headers=owner_headers,
            files=_nonstructured_project_payload(),
        )

    assert response.status_code == 200
    payload = response.json()

    # The API must NEVER ship hardcoded Chinese business labels invented by a
    # heuristic detector — the agent decides table_name / human_label from the
    # actual content.
    serialized = response.text
    assert "项目人员投入分配" not in serialized
    assert "recommended_catalog_seed" not in serialized
    assert "project_assignment_matrix" not in serialized

    workbook_structure = payload["workbook_structure"]
    assert workbook_structure is not None
    sheets = workbook_structure["sheets"]
    assert sheets, "expected at least one inspected sheet"

    primary = sheets[0]
    signals = primary["structural_signals"]
    assert signals["has_merged_cells"] is True
    assert signals["likely_layout"] == "human_readable_matrix"
    assert primary["top_rows_preview"]


def test_ingestion_upload_flags_flat_hr_roster_as_flat_table(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Regression for the hardcoded `项目人员投入分配` bug: a plain HR roster
    upload must classify as a flat_table and must not leak any project-matrix
    label into the response."""

    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=True)

    sample_path = Path(__file__).resolve().parents[2] / "sample_data" / "gs_hr_roster.xlsx"
    files = [
        (
            "files",
            (
                "gs_hr_roster.xlsx",
                sample_path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        )
    ]

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        workspace_response = client.post(
            "/workspaces",
            json={"name": "Flat Roster Workspace"},
            headers=owner_headers,
        )
        assert workspace_response.status_code == 200
        workspace_id = workspace_response.json()["workspace_id"]

        response = client.post(
            "/ingestion/uploads",
            data={"workspace_id": workspace_id},
            headers=owner_headers,
            files=files,
        )

    assert response.status_code == 200
    payload = response.json()

    serialized = response.text
    assert "项目人员投入分配" not in serialized
    assert "project_assignments" not in serialized

    workbook_structure = payload["workbook_structure"]
    assert workbook_structure is not None
    primary_sheet = workbook_structure["sheets"][0]
    assert primary_sheet["structural_signals"]["likely_layout"] == "flat_table"


def test_ingestion_upload_ignores_disabled_feature_flag(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=False)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        workspace_response = client.post(
            "/workspaces",
            json={"name": "Flag Guard Workspace"},
            headers=owner_headers,
        )
        assert workspace_response.status_code == 200
        workspace_id = workspace_response.json()["workspace_id"]

        response = client.post(
            "/ingestion/uploads",
            data={"workspace_id": workspace_id},
            headers=owner_headers,
            files=_upload_file_payload(),
        )

    assert response.status_code == 200
    assert response.json()["status"] == "uploaded"


def test_ingestion_upload_workspace_role_guards(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=True)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")
        viewer_headers = auth_headers(client, user_id="bob", project_id="north", role="hr")
        outsider_headers = auth_headers(client, user_id="charlie", project_id="north", role="hr")

        workspace_response = client.post(
            "/workspaces",
            json={"name": "Workspace Role Guard"},
            headers=owner_headers,
        )
        assert workspace_response.status_code == 200
        workspace_id = workspace_response.json()["workspace_id"]

        # Viewer membership is no longer a valid role.
        add_member_response = client.post(
            f"/workspaces/{workspace_id}/members",
            headers=owner_headers,
            json={"user_id": "bob", "role": "viewer", "display_name": "Bob Viewer"},
        )
        assert add_member_response.status_code == 422

        # bob is not a member, so uploads are forbidden.
        viewer_upload_response = client.post(
            "/ingestion/uploads",
            data={"workspace_id": workspace_id},
            headers=viewer_headers,
            files=_upload_file_payload(),
        )
        expect_error_code(viewer_upload_response, "WORKSPACE_FORBIDDEN", status_code=403)

        outsider_upload_response = client.post(
            "/ingestion/uploads",
            data={"workspace_id": workspace_id},
            headers=outsider_headers,
            files=_upload_file_payload(),
        )
        expect_error_code(outsider_upload_response, "WORKSPACE_FORBIDDEN", status_code=403)


def test_ingestion_upload_rejects_non_excel(monkeypatch, tmp_path: Path) -> None:
    _set_minimal_env(monkeypatch, tmp_path, ingestion_enabled=True)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="alice", project_id="north", role="admin")

        workspace_response = client.post(
            "/workspaces",
            json={"name": "Ingestion File Validation"},
            headers=owner_headers,
        )
        assert workspace_response.status_code == 200
        workspace_id = workspace_response.json()["workspace_id"]

        response = client.post(
            "/ingestion/uploads",
            data={"workspace_id": workspace_id},
            headers=owner_headers,
            files=[("files", ("notes.txt", b"hello", "text/plain"))],
        )

    expect_error_code(response, "UNSUPPORTED_FILE_TYPE", status_code=400)
