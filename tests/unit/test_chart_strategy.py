from __future__ import annotations

from apps.api.agent_canvas import AGENT_DASHBOARD_CHART_TYPES
from apps.api.chart_strategy import ChartStrategyRouter


def test_chart_strategy_defaults_to_recharts_for_simple_query() -> None:
    router = ChartStrategyRouter()
    rows = [
        {"department": "HR", "metric_value": 10},
        {"department": "PM", "metric_value": 8},
    ]

    spec = router.build_spec(
        metric="active_employee_count",
        intent="按部门看在职人数",
        rows=rows,
        group_by=["department"],
    )

    assert spec["engine"] == "recharts"
    assert spec["chart_type"] == "bar"
    assert spec["config"]["xKey"] == "department"
    assert "complexity_score" not in spec["route"]


def test_chart_strategy_respects_caller_supplied_chart_type() -> None:
    """The router no longer overrides chart_type based on row counts or keywords.

    When the caller (the agent) supplies a chart_type the router must honour it
    — engine selection follows from the chart_type, not from heuristic
    complexity scoring.
    """
    router = ChartStrategyRouter()
    rows = [{"department": f"D-{index:02d}", "metric_value": index} for index in range(1, 21)]

    spec = router.build_spec(
        metric="attrition_rate",
        intent="show trend distribution top departments",
        rows=rows,
        group_by=["department", "project"],
        chart_type="line",
    )

    assert spec["engine"] == "echarts"
    assert spec["chart_type"] == "line"
    assert "option" in spec["config"]
    option = spec["config"]["option"]
    assert option["xAxis"]["type"] == "category"
    assert len(option["series"][0]["data"]) == len(rows)


def test_chart_strategy_uses_negative_bar_default_for_negative_metrics() -> None:
    """Negative-value defaults still apply when the caller did not pick a type."""
    router = ChartStrategyRouter()
    rows = [
        {"department": "HR", "metric_value": -3},
        {"department": "PM", "metric_value": 5},
    ]

    spec = router.build_spec(
        metric="headcount_delta",
        intent="按部门看人数净变化",
        rows=rows,
        group_by=["department"],
    )

    assert spec["engine"] == "echarts"
    assert spec["chart_type"] == "negative_bar"
    option = spec["config"]["option"]
    assert option["xAxis"]["position"] == "top"
    assert option["yAxis"]["axisLabel"]["show"] is False
    assert option["series"][0]["data"][0]["label"]["position"] == "right"


def test_chart_strategy_builds_funnel_with_inside_value_labels() -> None:
    router = ChartStrategyRouter()
    rows = [
        {"stage": "Show", "metric_value": 100},
        {"stage": "Click", "metric_value": 80},
    ]

    spec = router.build_spec(
        metric="conversion",
        intent="用漏斗图显示阶段转化",
        rows=rows,
        group_by=["stage"],
        chart_type="funnel",
    )

    assert spec["engine"] == "echarts"
    assert spec["chart_type"] == "funnel"
    option = spec["config"]["option"]
    series = option["series"][0]
    assert series["type"] == "funnel"
    assert series["label"]["position"] == "inside"
    # Funnel labels carry the conversion share as well as the raw value, matching
    # the tooltip formatter ("{b}: {c} ({d}%)").
    assert series["label"]["formatter"] == "{b}\n{c} ({d}%)"
    assert series["labelLine"] == {"show": False}


def test_chart_strategy_returns_explainable_route_reason() -> None:
    router = ChartStrategyRouter()
    rows = [{"region": f"R-{index:02d}", "metric_value": index} for index in range(1, 15)]

    decision = router.route(
        intent="compare region trend",
        rows=rows,
        group_by=["region"],
    )

    assert decision.reasons
    assert any("engine=" in item for item in decision.reasons)
    assert decision.chart_type == "bar"
    assert decision.engine == "recharts"


def test_every_agent_dashboard_chart_type_builds_a_faithful_complete_option() -> None:
    """The canvas must never retain a rich chart_type while rendering bars.

    This pins the executable catalog end to end at the backend spec boundary;
    it intentionally checks visual series type rather than metadata alone.
    """
    router = ChartStrategyRouter()
    rows = [
        {"segment": "1", "series": "A", "metric_value": 10},
        {"segment": "2", "series": "A", "metric_value": 20},
        {"segment": "1", "series": "B", "metric_value": 15},
        {"segment": "2", "series": "B", "metric_value": 25},
    ]
    expected_series_type = {
        "gauge": "gauge",
        "bar": "bar",
        "negative_bar": "bar",
        "grouped_bar": "bar",
        "stacked_bar": "bar",
        "line": "line",
        "stacked_line": "line",
        "area": "line",
        "pie": "pie",
        "scatter": "scatter",
        "heatmap": "heatmap",
        "funnel": "funnel",
        "treemap": "treemap",
        "radar": "radar",
    }

    built: dict[str, dict] = {}
    for chart_type in AGENT_DASHBOARD_CHART_TYPES:
        built[chart_type] = router.build_spec(
            metric="Metric",
            intent="Intent",
            rows=rows,
            group_by=["segment", "series"],
            chart_type=chart_type,
        )

    assert set(built) == set(AGENT_DASHBOARD_CHART_TYPES)
    for chart_type, expected in expected_series_type.items():
        spec = built[chart_type]
        assert spec["chart_type"] == chart_type
        option = spec["config"]["option"]
        assert option["series"], chart_type
        assert option["series"][0]["type"] == expected, chart_type

    area_series = built["area"]["config"]["option"]["series"][0]
    assert area_series["areaStyle"]
    for chart_type in ("stacked_bar", "stacked_line"):
        assert built[chart_type]["config"]["option"]["series"][0]["stack"] == "total"

    single_option = built["single_value"]["config"]["option"]
    assert single_option["graphic"] and single_option["series"] == []
    table_option = built["table"]["config"]["option"]
    assert table_option["__table__"] is True
    assert table_option["__rows__"] == rows
