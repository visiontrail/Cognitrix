from __future__ import annotations

from apps.api.agentic_ingestion.routing import select_agent_route


def test_route_prefers_write_when_files_present() -> None:
    decision = select_agent_route(message=None, has_files=True, ingestion_job_status=None)
    assert decision.route == "write_ingestion"
    assert decision.reason == "request_has_attachments"


def test_route_prefers_write_for_active_ingestion_status() -> None:
    decision = select_agent_route(
        message="普通分析问题",
        has_files=False,
        ingestion_job_status="awaiting_user_approval",
    )
    assert decision.route == "write_ingestion"
    assert decision.reason == "ingestion_lifecycle_active"


def test_route_falls_back_to_query_for_write_intent_text_only() -> None:
    """Free-form text intent no longer forces the write-ingestion route.

    Without a file attachment or an active ingestion job, even a clearly
    write-flavored message routes to `query`. The query agent is responsible
    for recognising the intent and guiding the user to the upload affordance.
    """
    decision = select_agent_route(
        message="请帮我导入这个月项目进度",
        has_files=False,
        ingestion_job_status=None,
    )
    assert decision.route == "query"
    assert decision.reason == "default_query_route"


def test_route_falls_back_to_query() -> None:
    decision = select_agent_route(
        message="按部门统计本季度 headcount 变化",
        has_files=False,
        ingestion_job_status=None,
    )
    assert decision.route == "query"
    assert decision.reason == "default_query_route"
