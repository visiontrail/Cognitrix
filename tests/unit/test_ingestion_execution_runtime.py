from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from apps.api.agentic_ingestion.models import DiffPreview, IngestionExecutionAgentOutput, IngestionProposalPayload
from apps.api.agentic_ingestion.runtime import IngestionPlanningError, SQLWriteValidator, WriteIngestionAgentRuntime


def _proposal_payload() -> IngestionProposalPayload:
    return IngestionProposalPayload(
        business_type="roster",
        confidence=0.9,
        recommended_action="update_existing",
        candidate_actions=["update_existing", "new_table", "time_partitioned_new_table", "cancel"],
        target_table="employee_roster",
        time_grain="none",
        match_columns=["employee_id"],
        column_mapping={
            "Employee ID": "employee_id",
            "Name": "employee_name",
            "Department": "department",
        },
        diff_preview=DiffPreview(
            predicted_insert_count=10,
            predicted_update_count=30,
            predicted_conflict_count=2,
        ),
        risks=["2 potential conflicts were detected in dry preview."],
        sql_draft="",
    )


def test_sql_write_validator_accepts_bound_merge_statement() -> None:
    validator = SQLWriteValidator(
        target_table="employee_roster",
        staging_table="staging_123456789abc",
        action_mode="update_existing",
    )
    sql = """
    MERGE INTO employee_roster AS t
    USING staging_123456789abc AS s
    ON t.employee_id = s.employee_id
    WHEN MATCHED THEN UPDATE SET employee_name = s.employee_name
    WHEN NOT MATCHED THEN INSERT (employee_id, employee_name) VALUES (s.employee_id, s.employee_name)
    """

    normalized = validator.validate(sql)
    assert "MERGE INTO employee_roster" in normalized


def test_sql_write_validator_rejects_multi_statement_payload() -> None:
    validator = SQLWriteValidator(
        target_table="employee_roster",
        staging_table="staging_123456789abc",
        action_mode="new_table",
    )

    with pytest.raises(IngestionPlanningError) as exc_info:
        validator.validate("CREATE TABLE employee_roster AS SELECT * FROM staging_123456789abc; SELECT 1")

    assert exc_info.value.code == "WRITE_SQL_MULTI_STATEMENT_NOT_ALLOWED"


def test_sql_write_validator_rejects_target_table_mismatch() -> None:
    validator = SQLWriteValidator(
        target_table="employee_roster",
        staging_table="staging_123456789abc",
        action_mode="new_table",
    )

    with pytest.raises(IngestionPlanningError) as exc_info:
        validator.validate("CREATE TABLE another_table AS SELECT * FROM staging_123456789abc")

    assert exc_info.value.code == "WRITE_SQL_TARGET_MISMATCH"


def test_build_dry_run_summary_exposes_prediction_and_warnings() -> None:
    runtime = WriteIngestionAgentRuntime()
    proposal = _proposal_payload()
    summary = runtime._build_dry_run_summary(  # noqa: SLF001
        proposal_payload=proposal,
        approved_action="update_existing",
        target_table="employee_roster",
        time_grain="none",
    )

    assert summary["predicted_insert_count"] == 10
    assert summary["predicted_update_count"] == 30
    assert summary["predicted_conflict_count"] == 2
    assert summary["predicted_affected_rows"] == 40
    assert summary["target_table"] == "employee_roster"


def test_build_validated_sql_casts_timestamp_columns_for_merge() -> None:
    runtime = WriteIngestionAgentRuntime()
    proposal = IngestionProposalPayload(
        business_type="roster",
        confidence=0.9,
        recommended_action="update_existing",
        candidate_actions=["update_existing", "new_table", "time_partitioned_new_table", "cancel"],
        target_table="employee_roster",
        time_grain="none",
        match_columns=["employee_id"],
        column_mapping={
            "Employee ID": "employee_id",
            "Snapshot At": "snapshot_at",
        },
        diff_preview=DiffPreview(
            predicted_insert_count=1,
            predicted_update_count=1,
            predicted_conflict_count=0,
        ),
        risks=[],
        sql_draft="",
    )

    sql = runtime._build_validated_sql(  # noqa: SLF001
        approved_action="update_existing",
        target_table="employee_roster",
        staging_table="staging_123456789abc",
        proposal_payload=proposal,
        target_column_types={
            "employee_id": "VARCHAR",
            "snapshot_at": "TIMESTAMP",
        },
    )

    assert "MERGE INTO employee_roster" in sql
    assert "snapshot_at = COALESCE(" in sql
    assert "TRY_CAST(NULLIF(TRIM(CAST(s.snapshot_at AS VARCHAR)), '') AS TIMESTAMP)" in sql
    assert "TRY_CAST(s.snapshot_at AS TIMESTAMP)" not in sql


def test_prepare_dataframe_for_staging_serializes_mixed_temporal_values() -> None:
    runtime = WriteIngestionAgentRuntime()
    dataframe = pd.DataFrame(
        {
            "employee_id": ["E-001", "E-002", "E-003"],
            "snapshot_at": [datetime(2024, 1, 2, 3, 4, 5), 45292, None],
        },
        dtype=object,
    )

    prepared = runtime._prepare_dataframe_for_staging(dataframe)  # noqa: SLF001

    assert prepared["snapshot_at"].tolist() == ["2024-01-02 03:04:05", "45292", None]


def test_build_column_metadata_uses_non_english_source_headers() -> None:
    class FakeSession:
        proposal_payload = IngestionProposalPayload(
            business_type="roster",
            confidence=0.9,
            recommended_action="new_table",
            candidate_actions=["new_table", "cancel"],
            target_table="employee_roster",
            time_grain="none",
            match_columns=[],
            column_mapping={},
            diff_preview=DiffPreview(
                predicted_insert_count=1,
                predicted_update_count=0,
                predicted_conflict_count=0,
            ),
            risks=[],
            sql_draft="",
        )
        raw_header_mapping = {"姓名": "c_1", "部门": "c_2"}

    metadata = WriteIngestionAgentRuntime._build_column_metadata_for_receipt(  # noqa: SLF001
        session=FakeSession(),  # type: ignore[arg-type]
        target_schema={
            "columns": [
                {"name": "c_1", "type": "VARCHAR"},
                {"name": "c_2", "type": "VARCHAR"},
            ]
        },
    )

    assert metadata[0]["name"] == "c_1"
    assert metadata[0]["original_name"] == "姓名"
    assert metadata[0]["description"] == "姓名"


def test_execution_output_uses_canonical_tool_receipt_metadata() -> None:
    output = IngestionExecutionAgentOutput(
        status="executed",
        approved_action="new_table",
        target_table="employee_roster",
        executed_sql="",
        receipt={
            "success": True,
            "target_table": "employee_roster",
        },
    )
    session = SimpleNamespace(
        executed_sql="CREATE TABLE employee_roster AS SELECT c_1 FROM staging_abc AS s",
        write_receipt={
            "success": True,
            "target_table": "employee_roster",
            "executed_sql": "CREATE TABLE employee_roster AS SELECT c_1 FROM staging_abc AS s",
            "column_metadata": [
                {
                    "name": "c_1",
                    "type": "VARCHAR",
                    "original_name": "姓名",
                    "description": "姓名",
                    "ordinal_position": 0,
                }
            ],
        },
    )

    WriteIngestionAgentRuntime._attach_canonical_write_receipt(  # noqa: SLF001
        output=output,
        session=session,  # type: ignore[arg-type]
    )

    assert output.executed_sql.startswith("CREATE TABLE employee_roster")
    assert output.receipt["column_metadata"][0]["original_name"] == "姓名"
