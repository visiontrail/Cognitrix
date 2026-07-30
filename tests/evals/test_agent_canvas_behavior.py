from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.api.agent_canvas import SIZE_PRESETS
from apps.api.agent_canvas_mode import _normalize_outline, _parse_agent_canvas_json
from apps.api.agent_prompting import (
    build_agent_canvas_execution_prompt,
    build_agent_canvas_outline_prompt,
)

# ---------------------------------------------------------------------------
# Prompt-contract evals. The DeepSeek gateway follows explicit, numbered,
# example-driven instructions far more reliably than abstract guidance; these
# assertions pin the prompt properties the run protocol depends on, so a prompt
# refactor cannot silently drop the parts that keep the model on-protocol.
# ---------------------------------------------------------------------------


def test_outline_prompt_pins_the_contract() -> None:
    prompt = build_agent_canvas_outline_prompt(max_charts=12)

    # Machine-parsed output contract: exact JSON fencing + a concrete example.
    assert "```json" in prompt
    assert '"sections"' in prompt
    assert '"size_preset"' in prompt
    # The chart budget is stated as a hard numeric limit.
    assert "AT MOST 12 chart items" in prompt
    # Size-preset semantics are spelled out for every enum value.
    for preset in SIZE_PRESETS:
        assert f"`{preset}`" in prompt
    # Geometry is explicitly out of scope (the layout engine owns it).
    assert "NEVER include coordinates" in prompt
    # Grounding: outline items must come from inspected data.
    assert "list_tables" in prompt and "describe_table" in prompt


def test_execution_prompt_pins_the_run_protocol() -> None:
    outline_json = json.dumps({"title": "T", "sections": []}, ensure_ascii=False)
    prompt = build_agent_canvas_execution_prompt(outline_json=outline_json, max_charts=8)

    # The approved outline is embedded verbatim.
    assert outline_json in prompt
    # Protocol order: sections → items → finish, as numbered steps.
    assert "add_section" in prompt
    assert "place_chart" in prompt
    assert "finish_dashboard" in prompt
    assert "`finish_dashboard` is REQUIRED" in prompt
    # SQL aliasing contract that ChartStrategyRouter's spec builder relies on.
    assert "AS segment" in prompt and "AS metric_value" in prompt
    # Uploaded temporal columns are commonly strings; the prompt must pin the
    # cast needed before DuckDB temporal functions.
    assert "TRY_CAST(entry_date AS TIMESTAMP)" in prompt
    # Failure isolation: retry at most once, never abandon the run.
    assert "AT MOST once" in prompt
    assert "automatically replaces the error placeholder" in prompt
    assert "Never abandon the run" in prompt
    # Budgets and geometry rules restated at execution time.
    assert "more than 8 charts" in prompt
    assert "NEVER pass coordinates" in prompt


# ---------------------------------------------------------------------------
# Outline-normalization evals: what a drifting model actually emits must be
# normalized into a valid outline (or rejected), never crash the run.
# ---------------------------------------------------------------------------


def test_canvas_json_parser_accepts_live_outline_result_format() -> None:
    raw = {
        "title": "员工概览",
        "sections": [
            {
                "title": "概览",
                "items": [{"kind": "chart", "title": "总人数", "chart_type": "single_value"}],
            }
        ],
    }
    content = f"大纲如下：\n```json\n{json.dumps(raw, ensure_ascii=False)}\n```"

    assert _parse_agent_canvas_json(content) == raw


def test_outline_normalization_repairs_model_drift() -> None:
    raw = {
        "title": "  销售概览  ",
        "sections": [
            {
                # Missing keys and a bogus size preset.
                "title": "概览",
                "items": [
                    {"kind": "chart", "title": "总人数", "chart_type": "single_value", "size_preset": "huge"},
                    {"kind": "chart", "title": "部门人数", "chart_type": "bar"},
                    {"kind": "text", "content": "说明", "style": "loud"},
                    {"kind": "chart", "title": ""},  # dropped: no title
                    "not-a-dict",  # dropped: wrong shape
                ],
            },
            {"title": "空节", "items": []},  # dropped: nothing usable
        ],
    }
    outline = _normalize_outline(raw, max_charts=12)

    assert outline["title"] == "销售概览"
    assert outline["chart_count"] == 2
    assert len(outline["sections"]) == 1
    items = outline["sections"][0]["items"]
    kinds = [item["kind"] for item in items]
    assert kinds == ["chart", "chart", "text"]
    # single_value gets the kpi preset when the model's preset is invalid.
    assert items[0]["size_preset"] == "kpi"
    assert items[1]["size_preset"] == "half"
    assert items[2]["style"] == "body"
    # Keys are assigned and unique even when the model omitted them.
    keys = [item["key"] for item in items]
    assert len(set(keys)) == len(keys)


def test_outline_normalization_caps_chart_count() -> None:
    raw = {
        "title": "T",
        "sections": [
            {
                "title": "S",
                "items": [
                    {"kind": "chart", "title": f"chart-{index}", "chart_type": "bar"}
                    for index in range(10)
                ],
            }
        ],
    }
    outline = _normalize_outline(raw, max_charts=3)
    assert outline["chart_count"] == 3
    assert outline["truncated"] is True


@pytest.mark.parametrize(
    "raw",
    [
        {"title": "T"},
        {"title": "T", "sections": []},
        {"title": "T", "sections": [{"title": "S", "items": [{"kind": "text", "content": "只有文字"}]}]},
    ],
)
def test_outline_normalization_rejects_unusable_outlines(raw: dict) -> None:
    with pytest.raises(ValueError):
        _normalize_outline(raw, max_charts=12)


# ---------------------------------------------------------------------------
# Run-protocol adherence: a model that stops without finish_dashboard must be
# watchdog-finalized as partial — no run may stay `running` forever.
# ---------------------------------------------------------------------------


def test_watchdog_finalizes_run_when_finish_never_arrives(monkeypatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from apps.api.main import app
    from tests.integration.test_agent_canvas_mode import (
        _agent_mode_body,
        _create_workspace,
        _install_scripted_canvas_client,
        _outline_script,
        _seed_workspace_dataset,
        _set_canvas_env,
    )
    from tests.agent_test_utils import read_sse_events
    from tests.auth_utils import auth_headers

    _set_canvas_env(monkeypatch, tmp_path)

    async def drifting_execution(invoke) -> None:  # type: ignore[no-untyped-def]
        section = await invoke("add_section", {"title": "概览"})
        await invoke(
            "place_chart",
            {
                "section_id": section["section_id"],
                "title": "总人数",
                "chart_type": "single_value",
                "size_preset": "kpi",
                "sql": "SELECT 'total' AS segment, COUNT(*) AS metric_value FROM employees",
            },
        )
        # Protocol violation: the model ends its turn without finish_dashboard.
        return None

    with TestClient(app) as client:
        headers = auth_headers(client, user_id="admin", project_id="north", role="admin")
        workspace_id = _create_workspace(client, headers, name="Watchdog WS")
        _seed_workspace_dataset(workspace_id)
        _install_scripted_canvas_client([_outline_script, drifting_execution])

        with client.stream(
            "POST",
            "/chat/stream",
            json=_agent_mode_body(workspace_id, auto_approve=True),
            headers=headers,
        ) as response:
            events, _ = read_sse_events(response)

    final_payload = events[-1]["data"]
    assert final_payload["status"] == "partial"
    assert final_payload["code"] == "AGENT_CANVAS_FINISH_MISSING"
    assert final_payload["placed_count"] == 1
