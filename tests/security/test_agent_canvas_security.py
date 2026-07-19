from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from apps.api.agent_canvas import (
    clear_agent_canvas_run_store_cache,
    get_agent_canvas_run_store,
)
from apps.api.config import get_settings
from apps.api.datasets import get_dataset_service
from apps.api.main import app
from apps.api.tool_calling import ToolCall, ToolCallRequest, get_tool_calling_service
from apps.api.workspace_state import clear_workspace_state_store_cache
from apps.api.workspaces import clear_workspace_service_cache
from tests.agent_test_utils import set_agent_env
from tests.auth_utils import auth_headers

WORKSPACE_ID = "ws-canvas-sec"


def _set_canvas_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_CANVAS_MODE_ENABLED", "true")
    set_agent_env(monkeypatch, tmp_path)
    clear_agent_canvas_run_store_cache()
    clear_workspace_state_store_cache()
    clear_workspace_service_cache()

    from apps.api.agent_canvas_mode import clear_agent_canvas_mode_service_cache

    clear_agent_canvas_mode_service_cache()


def _place_chart(run: dict, sql: str):
    return get_tool_calling_service().invoke(
        ToolCallRequest(
            conversation_id="conv-sec",
            request_id="req-sec",
            idempotency_key=f"sec-{hash(sql)}",
            user_id="admin",
            project_id="north",
            workspace_id=WORKSPACE_ID,
            dataset_table="employees",
            role="admin",
            department="HR",
            clearance=9,
            emit_debug_blocks=False,
            tool=ToolCall(
                name="place_chart",
                arguments={
                    "title": "图",
                    "chart_type": "bar",
                    "size_preset": "half",
                    "sql": sql,
                    "_agent_run": {
                        "run_id": run["run_id"],
                        "page_id": run["page_id"],
                        "workspace_id": run["workspace_id"],
                        "conversation_id": "conv-sec",
                    },
                },
            ),
        )
    )


def test_place_chart_sql_goes_through_readonly_validation(monkeypatch, tmp_path: Path) -> None:
    """Mutating SQL inside place_chart is rejected by the same secure_query_sql
    path as execute_readonly_sql, and surfaces as an error placeholder."""
    _set_canvas_env(monkeypatch, tmp_path)
    dataframe = pd.DataFrame([{"employee_id": "E-001", "department": "HR"}])
    dataset_service = get_dataset_service(get_settings().upload_dir)
    with dataset_service.session_manager.connection(
        "admin", "north", workspace_id=WORKSPACE_ID
    ) as conn:
        conn.register("seed_df", dataframe)
        conn.execute('CREATE OR REPLACE TABLE "employees" AS SELECT * FROM seed_df')
        conn.unregister("seed_df")
    run = get_agent_canvas_run_store().create_run(
        conversation_id="conv-sec",
        workspace_id=WORKSPACE_ID,
        user_id="admin",
        canvas_format="web-design",
        status="running",
    )
    response = _place_chart(run, "DELETE FROM employees")
    assert response.status == "success"
    result = response.result or {}
    assert result["status"] == "error_placeholder"
    error_blob = json.dumps(result["error"], ensure_ascii=False)
    assert "READ_ONLY" in error_blob or "read" in error_blob.lower()

    ops = get_agent_canvas_run_store().list_ops_after(run_id=run["run_id"], after_seq=0)
    assert [op["op_type"] for op in ops] == ["error_placeholder"]


def test_agent_mode_requires_workspace_editor_role(monkeypatch, tmp_path: Path) -> None:
    """A user without editor access to the workspace is rejected before the
    outline phase, and no run record is created."""
    _set_canvas_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="owner", project_id="north", role="admin")
        created = client.post("/workspaces", json={"name": "Sec WS"}, headers=owner_headers)
        assert created.status_code == 200, created.text
        workspace_id = str(created.json()["workspace_id"])

        intruder_headers = auth_headers(client, user_id="intruder", project_id="north", role="admin")
        response = client.post(
            "/chat/stream",
            json={
                "conversation_id": "conv-rbac",
                "request_id": "req-rbac",
                "user_id": "intruder",
                "project_id": "north",
                "workspace_id": workspace_id,
                "dataset_table": "",
                "message": "生成一个销售仪表盘",
                "agent_mode": True,
                "canvas_format": "web-design",
            },
            headers=intruder_headers,
        )
        assert response.status_code == 403

        store = get_agent_canvas_run_store()
        assert store.get_latest_run(workspace_id=workspace_id, user_id="intruder") is None


def test_agent_run_endpoints_enforce_workspace_access(monkeypatch, tmp_path: Path) -> None:
    _set_canvas_env(monkeypatch, tmp_path)

    with TestClient(app) as client:
        owner_headers = auth_headers(client, user_id="owner", project_id="north", role="admin")
        created = client.post("/workspaces", json={"name": "Sec WS 2"}, headers=owner_headers)
        workspace_id = str(created.json()["workspace_id"])

        run = get_agent_canvas_run_store().create_run(
            conversation_id="conv-x",
            workspace_id=workspace_id,
            user_id="owner",
            canvas_format="web-design",
            status="running",
        )

        intruder_headers = auth_headers(client, user_id="intruder", project_id="north", role="admin")
        for method, url in (
            ("GET", f"/chat/agent-runs/{run['run_id']}/ops"),
            ("POST", f"/chat/agent-runs/{run['run_id']}/stop"),
        ):
            response = client.request(method, url, headers=intruder_headers)
            assert response.status_code == 403, f"{method} {url} -> {response.status_code}"

        response = client.get(
            "/chat/agent-runs/active",
            params={"workspace_id": workspace_id},
            headers=intruder_headers,
        )
        assert response.status_code == 403
