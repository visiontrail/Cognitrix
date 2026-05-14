from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from claude_agent_sdk import ResultMessage

from apps.api.agentic_ingestion.runtime import (
    INGESTION_AGENT_SYSTEM_PROMPT,
    MIN_INGESTION_AGENT_MAX_TURNS,
    IngestionPlanningError,
    WriteIngestionAgentRuntime,
)
from apps.api.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache_after_test() -> Iterator[None]:
    yield
    get_settings.cache_clear()


def _set_runtime_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'workspace-state.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AI_API_KEY", "test-ai-key")
    monkeypatch.setenv("AI_MODEL", "deepseek-chat")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()


def test_ingestion_sdk_turn_budget_covers_full_proposal_sequence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_runtime_env(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENT_MAX_TOOL_STEPS", "6")
    get_settings.cache_clear()

    runtime = WriteIngestionAgentRuntime()
    conn = sqlite3.connect(":memory:")
    try:
        options = runtime._build_ingestion_sdk_options(  # noqa: SLF001
            conn=conn,
            job_id="job-demo",
            tool_trace=[],
        )
    finally:
        conn.close()

    assert options.max_turns == MIN_INGESTION_AGENT_MAX_TURNS
    assert options.max_turns > 6


def test_ingestion_system_prompt_keeps_approval_after_preview_and_sql() -> None:
    assert "build_diff_preview" in INGESTION_AGENT_SYSTEM_PROMPT
    assert "generate_write_sql_draft" in INGESTION_AGENT_SYSTEM_PROMPT
    assert "AskUserQuestion" not in INGESTION_AGENT_SYSTEM_PROMPT
    assert "Human approval is handled by" in INGESTION_AGENT_SYSTEM_PROMPT


def test_ingestion_sdk_error_result_is_reported_as_ai_unavailable() -> None:
    with pytest.raises(IngestionPlanningError) as exc_info:
        WriteIngestionAgentRuntime._consume_ingestion_sdk_message(  # noqa: SLF001
            message=ResultMessage(
                subtype="error_max_turns",
                duration_ms=1000,
                duration_api_ms=500,
                is_error=True,
                num_turns=6,
                session_id="session-demo",
            ),
            text_blocks=[],
        )

    assert exc_info.value.code == "INGESTION_AI_UNAVAILABLE"
    assert exc_info.value.status_code == 503
    assert "error_max_turns" in exc_info.value.message


def test_recover_agent_output_from_tool_trace_for_ask_user_question() -> None:
    runtime = WriteIngestionAgentRuntime()
    tool_trace = [
        {
            "tool_name": "describe_table_schema",
            "result": {
                "table_name": "employee_roster",
                "business_type": "roster",
                "primary_keys": ["employee_id"],
                "match_columns": ["employee_id"],
                "write_mode": "update_existing",
                "time_grain": "none",
            },
        },
        {
            "tool_name": "inspect_upload",
            "result": {
                "column_summary": {"all_columns": ["Employee ID", "Name"]},
            },
        },
        {
            "tool_name": "build_diff_preview",
            "result": {
                "predicted_insert_count": 3,
                "predicted_update_count": 2,
                "predicted_conflict_count": 0,
            },
        },
        {
            "tool_name": "generate_write_sql_draft",
            "arguments": {
                "target_table": "employee_roster",
                "action_mode": "update_existing",
                "match_columns": ["employee_id"],
            },
            "result": {"sql_draft": "MERGE INTO employee_roster ..."},
        },
        {
            "tool_name": "AskUserQuestion",
            "arguments": {
                "stage": "proposal_approval",
                "question": "Approve this ingestion action?",
                "options": ["update_existing", "time_partitioned_new_table", "new_table", "cancel"],
                "recommended_option": "update_existing",
            },
            "result": {
                "required": True,
                "status": "pending",
                "mechanism": "frontend_approval_card",
                "stage": "proposal_approval",
                "question": "Approve this ingestion action?",
                "options": ["update_existing", "time_partitioned_new_table", "new_table", "cancel"],
                "recommended_option": "update_existing",
            },
        },
    ]

    output = runtime._recover_agent_output_from_tool_trace(tool_trace=tool_trace)  # noqa: SLF001

    assert output is not None
    assert output.status == "awaiting_user_approval"
    assert output.human_approval.stage == "proposal_approval"
    assert output.proposal is not None
    assert output.proposal.recommended_action == "update_existing"


def test_recover_proposal_from_completed_tool_trace_without_structured_output() -> None:
    runtime = WriteIngestionAgentRuntime()
    tool_trace = [
        {
            "tool_name": "inspect_upload",
            "result": {
                "column_summary": {"all_columns": ["工号", "姓名"]},
            },
        },
        {
            "tool_name": "describe_table_schema",
            "result": {
                "table_name": "employee_roster",
                "business_type": "roster",
                "match_columns": ["employee_id"],
                "time_grain": "none",
            },
        },
        {
            "tool_name": "build_diff_preview",
            "result": {
                "predicted_insert_count": 0,
                "predicted_update_count": 30,
                "predicted_conflict_count": 0,
            },
        },
        {
            "tool_name": "generate_write_sql_draft",
            "arguments": {
                "target_table": "employee_roster",
                "action_mode": "update_existing",
                "match_columns": ["employee_id"],
            },
            "result": {"sql_draft": "MERGE INTO employee_roster ..."},
        },
    ]

    recovered = runtime._recover_proposal_from_tool_trace(tool_trace=tool_trace)  # noqa: SLF001

    assert recovered is not None
    assert recovered.status == "awaiting_user_approval"
    assert recovered.proposal is not None
    assert recovered.proposal.recommended_action == "update_existing"
    assert recovered.proposal.target_table == "employee_roster"
    assert recovered.proposal.diff_preview.predicted_update_count == 30
    assert recovered.human_approval.mechanism == "frontend_approval_card"


def test_normalize_raw_plan_output_injects_defaults_for_catalog_setup() -> None:
    raw: dict = {
        "status": "awaiting_catalog_setup",
        "suggested_catalog_seed": {
            "table_name": "employees",
            "human_label": "Employees",
            "business_type": "INVALID",
            "write_mode": "INVALID",
            "time_grain": "INVALID",
        },
    }
    WriteIngestionAgentRuntime._normalize_raw_plan_output(raw)  # noqa: SLF001
    seed = raw["suggested_catalog_seed"]
    assert seed["business_type"] == "other"
    assert seed["write_mode"] == "new_table"
    assert seed["time_grain"] == "none"


def test_inject_agent_guess_fills_missing_guess() -> None:
    raw: dict = {"status": "awaiting_catalog_setup"}
    tool_trace: list = []
    WriteIngestionAgentRuntime._inject_agent_guess_if_missing(raw, tool_trace=tool_trace)  # noqa: SLF001
    assert raw["agent_guess"]["business_type"] == "other"
    assert raw["agent_guess"]["confidence"] == 0.5


def test_inject_agent_guess_repairs_invalid_business_type() -> None:
    raw: dict = {"agent_guess": {"business_type": "WRONG", "confidence": 0.9}}
    WriteIngestionAgentRuntime._inject_agent_guess_if_missing(raw, tool_trace=[])  # noqa: SLF001
    assert raw["agent_guess"]["business_type"] == "other"
    assert raw["agent_guess"]["confidence"] == 0.9


def test_diff_preview_does_not_offer_update_without_physical_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_runtime_env(monkeypatch, tmp_path)
    runtime = WriteIngestionAgentRuntime()

    preview = runtime._tool_build_diff_preview(  # noqa: SLF001
        workspace_id="workspace-empty",
        upload_info={
            "upload_id": "upload-empty-target",
            "storage_path": str(tmp_path / "missing.xlsx"),
            "sheet_summary": {"sheets": [{"row_count": 30}]},
        },
        target_table="employee_roster",
        match_columns=["employee_id"],
        action_mode="update_existing",
        column_mapping={"Employee ID": "employee_id"},
    )

    assert preview["predicted_insert_count"] == 30
    assert preview["predicted_update_count"] == 0
    assert "update_existing" not in preview["candidate_actions"]
    assert preview["recommended_action"] == "new_table"


def test_diff_preview_counts_updates_from_real_target_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_runtime_env(monkeypatch, tmp_path)
    runtime = WriteIngestionAgentRuntime()
    workbook_path = tmp_path / "roster.xlsx"
    pd.DataFrame(
        [
            {"Employee ID": "E-001", "Name": "Ava"},
            {"Employee ID": "E-002", "Name": "Ben"},
            {"Employee ID": "E-003", "Name": "Cara"},
        ]
    ).to_excel(workbook_path, index=False)

    duckdb_path = runtime._workspace_duckdb_path(workspace_id="workspace-existing")  # noqa: SLF001
    duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    duck_conn = duckdb.connect(str(duckdb_path))
    try:
        duck_conn.execute("CREATE TABLE employee_roster (employee_id VARCHAR, name VARCHAR)")
        duck_conn.execute("INSERT INTO employee_roster VALUES ('E-001', 'Old Ava'), ('E-009', 'Nia')")
    finally:
        duck_conn.close()

    preview = runtime._tool_build_diff_preview(  # noqa: SLF001
        workspace_id="workspace-existing",
        upload_info={
            "upload_id": "upload-existing-target",
            "storage_path": str(workbook_path),
            "sheet_summary": {"sheets": [{"row_count": 3}]},
        },
        target_table="employee_roster",
        match_columns=["employee_id"],
        action_mode="update_existing",
        column_mapping={"Employee ID": "employee_id", "Name": "name"},
    )

    assert preview["predicted_insert_count"] == 2
    assert preview["predicted_update_count"] == 1
    assert preview["predicted_conflict_count"] == 0
    assert preview["candidate_actions"][0] == "update_existing"


def test_recover_catalog_setup_from_tool_trace_when_describe_returns_not_found() -> None:
    runtime = WriteIngestionAgentRuntime()
    tool_trace = [
        {
            "tool_name": "inspect_upload",
            "result": {
                "file_name": "employees.xlsx",
                "column_summary": {"all_columns": ["Employee ID", "Name", "Department"]},
            },
        },
        {
            "tool_name": "get_workspace_catalog",
            "result": {"entries": []},
        },
        {
            "tool_name": "describe_table_schema",
            "result": {
                "found": False,
                "table_name": "employees",
                "message": "No catalog entry exists.",
            },
        },
    ]
    recovered = runtime._recover_catalog_setup_from_tool_trace(tool_trace=tool_trace)  # noqa: SLF001

    assert recovered is not None
    assert recovered.status == "awaiting_catalog_setup"
    assert recovered.suggested_catalog_seed is not None
    assert recovered.suggested_catalog_seed.table_name == "employees"
    assert recovered.human_approval.stage == "catalog_setup"
    assert recovered.human_approval.mechanism == "catalog_setup_card"


def test_recover_catalog_setup_from_empty_catalog_without_describe() -> None:
    runtime = WriteIngestionAgentRuntime()
    tool_trace = [
        {
            "tool_name": "inspect_upload",
            "result": {
                "file_name": "hr_data.xlsx",
                "column_summary": {"all_columns": ["Name", "Role"]},
            },
        },
        {
            "tool_name": "get_workspace_catalog",
            "result": {"entries": []},
        },
    ]
    recovered = runtime._recover_catalog_setup_from_tool_trace(tool_trace=tool_trace)  # noqa: SLF001

    assert recovered is not None
    assert recovered.status == "awaiting_catalog_setup"
    assert recovered.suggested_catalog_seed is not None
    assert recovered.suggested_catalog_seed.table_name == "hr_data"


def test_recover_catalog_setup_returns_none_when_catalog_has_entries() -> None:
    runtime = WriteIngestionAgentRuntime()
    tool_trace = [
        {
            "tool_name": "get_workspace_catalog",
            "result": {"entries": [{"table_name": "employees"}]},
        },
        {
            "tool_name": "describe_table_schema",
            "result": {"found": True, "table_name": "employees"},
        },
    ]
    recovered = runtime._recover_catalog_setup_from_tool_trace(tool_trace=tool_trace)  # noqa: SLF001
    assert recovered is None


def test_recover_catalog_setup_from_tool_trace_when_awaiting_user_approval_with_no_proposal() -> None:
    """Agent returns awaiting_user_approval + proposal=null (empty-catalog first-upload case).
    The post-run recovery must synthesise an awaiting_catalog_setup output."""
    runtime = WriteIngestionAgentRuntime()
    tool_trace = [
        {
            "tool_name": "inspect_upload",
            "result": {
                "file_name": "workforce_2024.xlsx",
                "column_summary": {"all_columns": ["Employee ID", "Name", "Department"]},
            },
        },
        {
            "tool_name": "get_workspace_catalog",
            "result": {"count": 0, "entries": []},
        },
        {
            "tool_name": "list_existing_tables",
            "result": {"workspace_tables": [], "count": 0},
        },
    ]
    # Simulates the agent returning valid structured output that passes model_validate but
    # has status=awaiting_user_approval with proposal=None.
    recovered = runtime._recover_catalog_setup_from_tool_trace(tool_trace=tool_trace)  # noqa: SLF001

    assert recovered is not None
    assert recovered.status == "awaiting_catalog_setup"
    assert recovered.suggested_catalog_seed is not None
    assert recovered.suggested_catalog_seed.table_name == "workforce_2024"
    assert recovered.human_approval.stage == "catalog_setup"
    assert recovered.human_approval.mechanism == "catalog_setup_card"


def test_post_run_recovery_prefers_proposal_when_catalog_is_populated() -> None:
    """After setup/confirm the catalog is no longer empty, so _recover_catalog_setup_from_tool_trace
    returns None.  The post-run recovery must fall back to _recover_proposal_from_tool_trace
    when generate_write_sql_draft appears in the trace (second-pass / setup-confirm scenario)."""
    runtime = WriteIngestionAgentRuntime()
    tool_trace = [
        {
            "tool_name": "inspect_upload",
            "result": {
                "file_name": "hr_workforce_upload_sample.xlsx",
                "column_summary": {"all_columns": ["员工编号", "姓名", "部门"]},
            },
        },
        {
            "tool_name": "get_workspace_catalog",
            "result": {"entries": [{"table_name": "employee_roster", "business_type": "roster"}]},
        },
        {
            "tool_name": "describe_table_schema",
            "result": {
                "found": True,
                "table_name": "employee_roster",
                "business_type": "roster",
                "match_columns": ["employee_id"],
                "time_grain": "none",
            },
        },
        {
            "tool_name": "build_diff_preview",
            "result": {
                "predicted_insert_count": 0,
                "predicted_update_count": 30,
                "predicted_conflict_count": 0,
            },
        },
        {
            "tool_name": "generate_write_sql_draft",
            "arguments": {
                "target_table": "employee_roster",
                "action_mode": "update_existing",
                "match_columns": ["employee_id"],
            },
            "result": {"sql_draft": "MERGE INTO employee_roster ..."},
        },
    ]

    # _recover_catalog_setup_from_tool_trace must return None (catalog populated + table found)
    assert runtime._recover_catalog_setup_from_tool_trace(tool_trace=tool_trace) is None  # noqa: SLF001

    # _recover_proposal_from_tool_trace must succeed and produce an approval proposal
    recovered = runtime._recover_proposal_from_tool_trace(tool_trace=tool_trace)  # noqa: SLF001
    assert recovered is not None
    assert recovered.status == "awaiting_user_approval"
    assert recovered.proposal is not None
    assert recovered.proposal.recommended_action == "update_existing"
    assert recovered.proposal.target_table == "employee_roster"


def test_normalize_raw_plan_output_injects_diff_preview_for_proposal() -> None:
    raw: dict = {
        "status": "awaiting_user_approval",
        "proposal": {
            "business_type": "roster",
            "confidence": 0.8,
            "recommended_action": "update_existing",
        },
    }
    WriteIngestionAgentRuntime._normalize_raw_plan_output(raw)  # noqa: SLF001
    assert raw["proposal"]["diff_preview"] == {
        "predicted_insert_count": 0,
        "predicted_update_count": 0,
        "predicted_conflict_count": 0,
    }
