from __future__ import annotations

from types import SimpleNamespace

from apps.api.agent_runtime import AgentRequest, AgentRuntime
from apps.api.chat import ChatStreamRequest


def _request(*, chart_edit_context: dict | None = None) -> AgentRequest:
    return AgentRequest(
        conversation_id="conversation-1",
        request_id="request-1",
        user_id="user-1",
        project_id="project-1",
        workspace_id="workspace-1",
        dataset_table="employees",
        message="改成环形图并显示百分比",
        role="editor",
        department=None,
        clearance=9,
        response_locale="zh-CN",
        chart_edit_context=chart_edit_context,
    )


def test_chat_request_accepts_a_bounded_focused_chart_context() -> None:
    request = ChatStreamRequest.model_validate(
        {
            "user_id": "user-1",
            "project_id": "project-1",
            "message": "改成环形图",
            "agent_mode": True,
            "chart_edit_context": {
                "node_id": "node-chart-1",
                "zone_id": "zone-chart-1",
                "page_id": "page-1",
                "asset_id": "asset-1",
                "title": "部门人数",
                "chart_type": "bar",
                "spec": {"chartType": "bar", "title": "部门人数", "echartsOption": {}},
                "assistant_rows": [{"segment": "HR", "metric_value": 24}],
            },
        }
    )

    assert request.chart_edit_context is not None
    assert request.chart_edit_context.node_id == "node-chart-1"
    assert request.chart_edit_context.assistant_rows[0]["metric_value"] == 24


def test_runtime_system_prompt_constrains_focused_edit_to_one_replacement_chart() -> None:
    runtime = AgentRuntime.__new__(AgentRuntime)
    runtime.system_prompt = "BASE SYSTEM PROMPT"
    runtime.settings = SimpleNamespace(web_search_enabled=False)
    runtime.tool_service = SimpleNamespace(
        dataset_service=SimpleNamespace(list_tables=lambda **_kwargs: ["employees"])
    )
    context = {
        "node_id": "node-chart-1",
        "zone_id": "zone-chart-1",
        "page_id": "page-1",
        "asset_id": "asset-1",
        "title": "部门人数",
        "chart_type": "bar",
        "spec": {"chartType": "bar", "title": "部门人数", "echartsOption": {}},
        "assistant_rows": [{"segment": "HR", "metric_value": 24}],
    }

    prompt = runtime._build_system_text(  # noqa: SLF001 - prompt contract unit test
        request=_request(chart_edit_context=context),
        session=SimpleNamespace(last_result=None),
    )

    assert "Focused canvas chart edit" in prompt
    assert "exactly ONE existing canvas chart" in prompt
    assert "do not propose or generate multiple charts" in prompt
    assert '"node_id": "node-chart-1"' in prompt
    assert '"metric_value": 24' in prompt
