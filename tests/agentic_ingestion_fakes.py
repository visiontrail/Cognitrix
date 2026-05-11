from __future__ import annotations

import re
import sqlite3
from typing import Any

from apps.api.agentic_ingestion.models import (
    IngestionAgentPlanOutput,
    IngestionExecutionAgentOutput,
    IngestionProposalPayload,
)
from apps.api.agentic_ingestion.runtime import WriteIngestionAgentRuntime


def install_mock_planning_agent(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        WriteIngestionAgentRuntime,
        "_run_planning_agent_loop",
        _mock_run_planning_agent_loop,
    )


def install_mock_execution_agent(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        WriteIngestionAgentRuntime,
        "_run_execution_agent_loop",
        _mock_run_execution_agent_loop,
    )


def install_mock_ingestion_agents(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    install_mock_planning_agent(monkeypatch)
    install_mock_execution_agent(monkeypatch)


def install_failing_planning_agent(  # type: ignore[no-untyped-def]
    monkeypatch,
    *,
    code: str,
    message: str,
    status_code: int,
) -> None:
    from apps.api.agentic_ingestion.runtime import IngestionPlanningError

    failure_message = message

    def _raise(
        self: WriteIngestionAgentRuntime,
        *,
        conn: sqlite3.Connection,
        workspace_id: str,
        job_id: str,
        upload_id: str,
        requested_by: str,
        conversation_id: str | None,
        message: str | None,
    ) -> tuple[IngestionAgentPlanOutput, list[dict[str, Any]]]:
        _ = (self, conn, workspace_id, job_id, upload_id, requested_by, conversation_id, message)
        raise IngestionPlanningError(code=code, message=failure_message, status_code=status_code)

    monkeypatch.setattr(WriteIngestionAgentRuntime, "_run_planning_agent_loop", _raise)


def _mock_run_planning_agent_loop(
    self: WriteIngestionAgentRuntime,
    *,
    conn: sqlite3.Connection,
    workspace_id: str,
    job_id: str,
    upload_id: str,
    requested_by: str,
    conversation_id: str | None,
    message: str | None,
) -> tuple[IngestionAgentPlanOutput, list[dict[str, Any]]]:
    _ = (requested_by, conversation_id, message)
    tool_trace: list[dict[str, Any]] = []
    upload_info = self._run_tool(  # noqa: SLF001
        conn=conn,
        job_id=job_id,
        trace=tool_trace,
        name="inspect_upload",
        arguments={"upload_id": upload_id},
        handler=lambda: self._tool_inspect_upload(conn=conn, upload_id=upload_id),  # noqa: SLF001
    )
    catalog = self._run_tool(  # noqa: SLF001
        conn=conn,
        job_id=job_id,
        trace=tool_trace,
        name="get_workspace_catalog",
        arguments={"workspace_id": workspace_id},
        handler=lambda: self._tool_get_workspace_catalog(conn=conn, workspace_id=workspace_id),  # noqa: SLF001
    )
    self._run_tool(  # noqa: SLF001
        conn=conn,
        job_id=job_id,
        trace=tool_trace,
        name="list_existing_tables",
        arguments={"workspace_id": workspace_id},
        handler=lambda: self._tool_list_existing_tables(conn=conn, workspace_id=workspace_id),  # noqa: SLF001
    )

    agent_guess = {
        "business_type": "roster",
        "confidence": 0.91,
        "reasoning": "Mock agent selected roster from workbook structure.",
    }
    entries = list(catalog.get("entries", []))
    if not entries:
        seed = {
            "business_type": "roster",
            "table_name": "employee_roster",
            "human_label": "Employee Roster",
            "write_mode": "new_table",
            "time_grain": "none",
            "primary_keys": [],
            "match_columns": [],
            "is_active_target": True,
            "description": "Stores roster-style Excel uploads for workforce analysis.",
        }
        output = IngestionAgentPlanOutput.model_validate(
            {
                "status": "awaiting_catalog_setup",
                "agent_guess": agent_guess,
                "setup_questions": [
                    {
                        "question_id": "description",
                        "title": "这张表主要用于什么？",
                        "options": [],
                    }
                ],
                "suggested_catalog_seed": seed,
                "human_approval": {
                    "required": True,
                    "mechanism": "catalog_setup_card",
                    "stage": "catalog_setup",
                    "question": "Please confirm the catalog setup before proceeding.",
                    "options": ["confirm_catalog_setup", "cancel"],
                    "recommended_option": "confirm_catalog_setup",
                },
            }
        )
        return output, tool_trace

    target = entries[0]
    schema = self._run_tool(  # noqa: SLF001
        conn=conn,
        job_id=job_id,
        trace=tool_trace,
        name="describe_table_schema",
        arguments={"workspace_id": workspace_id, "table_name": target["table_name"]},
        handler=lambda: self._tool_describe_table_schema_by_name(  # noqa: SLF001
            conn=conn,
            workspace_id=workspace_id,
            table_name=str(target["table_name"]),
        ),
    )
    action = str(target.get("write_mode") or "update_existing")
    if action not in {"update_existing", "time_partitioned_new_table", "new_table"}:
        action = "update_existing"
    match_columns = list(target.get("match_columns") or target.get("primary_keys") or [])
    if action == "update_existing" and not match_columns:
        upload_columns = list(upload_info["column_summary"].get("all_columns", []))
        first_column = _normalize_identifier(str(upload_columns[0])) if upload_columns else ""
        if first_column:
            match_columns = [first_column]
    column_mapping = {
        str(column): _normalize_identifier(str(column))
        for column in upload_info["column_summary"].get("all_columns", [])
        if str(column).strip()
    }
    diff_preview = self._run_tool(  # noqa: SLF001
        conn=conn,
        job_id=job_id,
        trace=tool_trace,
        name="build_diff_preview",
        arguments={
            "workspace_id": workspace_id,
            "upload_id": upload_id,
            "target_table": target["table_name"],
            "match_columns": match_columns,
            "action_mode": action,
            "column_mapping": column_mapping,
        },
        handler=lambda: self._tool_build_diff_preview(  # noqa: SLF001
            conn=conn,
            workspace_id=workspace_id,
            upload_info=upload_info,
            target_table=str(target["table_name"]),
            match_columns=match_columns,
            action_mode=action,
            column_mapping=column_mapping,
        ),
    )
    sql_draft = self._run_tool(  # noqa: SLF001
        conn=conn,
        job_id=job_id,
        trace=tool_trace,
        name="generate_write_sql_draft",
        arguments={
            "workspace_id": workspace_id,
            "job_id": job_id,
            "target_table": target["table_name"],
            "action_mode": action,
            "match_columns": match_columns,
        },
        handler=lambda: self._tool_generate_write_sql_draft(  # noqa: SLF001
            workspace_id=workspace_id,
            job_id=job_id,
            target_table=str(target["table_name"]),
            action_mode=action,
            match_columns=match_columns,
        ),
    )
    proposal = IngestionProposalPayload(
        business_type=str(schema["business_type"]),
        confidence=0.91,
        recommended_action=action,
        candidate_actions=["update_existing", "time_partitioned_new_table", "new_table", "cancel"],
        target_table=str(target["table_name"]),
        time_grain=str(schema["time_grain"]),
        match_columns=match_columns,
        column_mapping=column_mapping,
        diff_preview=diff_preview,
        risks=[],
        explanation="Mock agent proposal generated through the ingestion tool surface.",
        sql_draft=str(sql_draft["sql_draft"]),
        requires_catalog_setup=False,
    )
    output = IngestionAgentPlanOutput.model_validate(
        {
            "status": "awaiting_user_approval",
            "agent_guess": agent_guess,
            "proposal": proposal.model_dump(mode="json"),
            "human_approval": {
                "required": True,
                "mechanism": "frontend_approval_card",
                "stage": "proposal_approval",
                "question": "Please review the proposed ingestion action.",
                "options": ["update_existing", "time_partitioned_new_table", "new_table", "cancel"],
                "recommended_option": action,
            },
        }
    )
    return output, tool_trace


def _mock_run_execution_agent_loop(
    self: WriteIngestionAgentRuntime,
    *,
    conn: sqlite3.Connection,
    workspace_id: str,
    job_id: str,
    proposal_id: str,
    upload_id: str,
    target_table: str,
    approved_action: str,
    dry_run_summary: dict[str, Any],
    upload_info: dict[str, Any],
    proposal_payload: IngestionProposalPayload,
) -> tuple[IngestionExecutionAgentOutput, list[dict[str, Any]]]:
    _ = upload_info
    tool_trace: list[dict[str, Any]] = []
    session = self._prepare_execution_session(  # noqa: SLF001
        workspace_id=workspace_id,
        job_id=job_id,
        proposal_id=proposal_id,
        upload_id=upload_id,
        target_table=target_table,
        approved_action=approved_action,
        dry_run_summary=dry_run_summary,
        upload_info=self._tool_inspect_upload(conn=conn, upload_id=upload_id),  # noqa: SLF001
        proposal_payload=proposal_payload,
    )
    try:
        context = self._run_tool(  # noqa: SLF001
            conn=conn,
            job_id=job_id,
            trace=tool_trace,
            name="get_execution_context",
            arguments={},
            handler=lambda: self._tool_get_execution_context(session=session),  # noqa: SLF001
        )
        staging = self._run_tool(  # noqa: SLF001
            conn=conn,
            job_id=job_id,
            trace=tool_trace,
            name="describe_staging_dataset",
            arguments={},
            handler=lambda: self._tool_describe_staging_dataset(session=session),  # noqa: SLF001
        )
        target = self._run_tool(  # noqa: SLF001
            conn=conn,
            job_id=job_id,
            trace=tool_trace,
            name="describe_target_table",
            arguments={},
            handler=lambda: self._tool_describe_target_table(conn=conn, session=session),  # noqa: SLF001
        )

        col_map_result = self._run_tool(  # noqa: SLF001
            conn=conn,
            job_id=job_id,
            trace=tool_trace,
            name="resolve_column_mapping",
            arguments={},
            handler=lambda: self._tool_resolve_column_mapping(conn=conn, session=session),  # noqa: SLF001
        )
        staging_to_target: dict[str, str] = dict(col_map_result.get("staging_to_target", {}))
        match_columns_staging: list[str] = list(col_map_result.get("match_columns_staging", []))

        target_schema = target["schema"]
        if approved_action == "update_existing" and not target["exists"]:
            ensured = self._run_tool(  # noqa: SLF001
                conn=conn,
                job_id=job_id,
                trace=tool_trace,
                name="ensure_target_table_exists",
                arguments={},
                handler=lambda: self._tool_ensure_target_table_exists(session=session),  # noqa: SLF001
            )
            target_schema = ensured["schema"]

        target_column_types = {
            str(item["name"]).strip().lower(): str(item["type"]).strip()
            for item in target_schema.get("columns", [])
            if str(item.get("name", "")).strip() and str(item.get("type", "")).strip()
        }

        staging_columns = list(staging_to_target.keys()) or [
            str(item["name"])
            for item in staging["schema"].get("columns", [])
            if str(item.get("name", "")).strip()
        ]

        if not match_columns_staging and staging_columns:
            match_columns_staging = [staging_columns[0]]

        if match_columns_staging:
            self._run_tool(  # noqa: SLF001
                conn=conn,
                job_id=job_id,
                trace=tool_trace,
                name="preview_write_diff",
                arguments={"match_columns": match_columns_staging},
                handler=lambda: self._tool_preview_write_diff(  # noqa: SLF001
                    session=session,
                    match_columns=match_columns_staging,
                ),
            )

        if approved_action == "update_existing":
            source_expr_by_staging_col = {
                staging_col: self._source_expr_for_target_type(  # noqa: SLF001
                    source_alias="s",
                    column=staging_col,
                    target_type=target_column_types.get(staging_to_target.get(staging_col, staging_col)),
                )
                for staging_col in staging_columns
            }
            effective_match = match_columns_staging or staging_columns[:1]
            update_cols = [c for c in staging_columns if c not in set(effective_match)] or list(staging_columns)
            target_cols_list = [staging_to_target.get(c, c) for c in staging_columns]
            on_clause = " AND ".join(
                f"t.{staging_to_target.get(c, c)} = {source_expr_by_staging_col[c]}"
                for c in effective_match
            )
            update_clause = ", ".join(
                f"{staging_to_target.get(c, c)} = {source_expr_by_staging_col[c]}"
                for c in update_cols
            )
            insert_cols = ", ".join(staging_to_target.get(c, c) for c in staging_columns)
            insert_vals = ", ".join(source_expr_by_staging_col[c] for c in staging_columns)
            sql = (
                f"MERGE INTO {target_table} AS t\n"
                f"USING {session.staging_table} AS s\n"
                f"ON {on_clause}\n"
                f"WHEN MATCHED THEN UPDATE SET {update_clause}\n"
                f"WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})"
            )
        else:
            select_parts = ", ".join(
                f"s.{staging_col} AS {staging_to_target.get(staging_col, staging_col)}"
                for staging_col in staging_columns
            )
            sql = (
                f"CREATE TABLE {target_table} AS\n"
                f"SELECT {select_parts} FROM {session.staging_table} AS s"
            )

        receipt = self._run_tool(  # noqa: SLF001
            conn=conn,
            job_id=job_id,
            trace=tool_trace,
            name="execute_approved_write",
            arguments={
                "sql": sql,
                "reasoning": "Mock execution agent wrote the approved ingestion data.",
            },
            handler=lambda: self._tool_execute_approved_write(  # noqa: SLF001
                session=session,
                sql=sql,
                reasoning="Mock execution agent wrote the approved ingestion data.",
            ),
        )
        output = IngestionExecutionAgentOutput.model_validate(
            {
                "status": "executed",
                "approved_action": approved_action,
                "target_table": target_table,
                "reasoning": "Mock execution agent completed the approved write through tools.",
                "executed_sql": str(receipt.get("executed_sql") or sql),
                "receipt": receipt,
                "risks": [],
            }
        )
        return output, tool_trace
    finally:
        session.duckdb_conn.close()


def _normalize_identifier(raw: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", raw.strip().lower()).strip("_")
    if not normalized:
        return ""
    if normalized[0].isdigit():
        normalized = f"c_{normalized}"
    return normalized
