from __future__ import annotations

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
    assert spec["route"]["complexity_score"] < router.COMPLEXITY_THRESHOLD


def test_chart_strategy_switches_to_echarts_for_complex_query() -> None:
    router = ChartStrategyRouter()
    rows = [{"department": f"D-{index:02d}", "metric_value": index} for index in range(1, 21)]

    spec = router.build_spec(
        metric="attrition_rate",
        intent="show trend distribution top departments",
        rows=rows,
        group_by=["department", "project"],
    )

    assert spec["engine"] == "echarts"
    assert spec["chart_type"] in {"line", "bar"}
    assert "option" in spec["config"]
    option = spec["config"]["option"]
    assert option["xAxis"]["type"] == "category"
    assert len(option["series"][0]["data"]) == len(rows)


def test_chart_strategy_uses_negative_bar_for_negative_metrics() -> None:
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


def test_chart_strategy_returns_explainable_route_reason() -> None:
    router = ChartStrategyRouter()
    rows = [{"region": f"R-{index:02d}", "metric_value": index} for index in range(1, 15)]

    decision = router.route(
        intent="compare region trend",
        rows=rows,
        group_by=["region"],
    )

    assert decision.reasons
    assert any("selected_engine" in item for item in decision.reasons)
    assert isinstance(decision.complexity_score, int)
