from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ChartRouteDecision:
    engine: str
    chart_type: str
    complexity_score: int
    reasons: list[str]


class ChartStrategyRouter:
    COMPLEXITY_THRESHOLD = 6
    COMPLEXITY_KEYWORDS = (
        "trend",
        "走势",
        "distribution",
        "分布",
        "heatmap",
        "热力",
        "scatter",
        "散点",
        "correlation",
        "相关",
        "compare",
        "对比",
        "top",
        "treemap",
        "树图",
        "矩形树图",
        "sunburst",
        "旭日",
        "sankey",
        "桑基",
        "radar",
        "雷达",
        "funnel",
        "漏斗",
        "gauge",
        "仪表盘",
        "boxplot",
        "箱线",
        "graph",
        "关系图",
        "网络图",
        "negative",
        "负数",
        "正负",
        "盈亏",
        "差异",
        "变化量",
        "净变化",
    )

    def route(
        self,
        *,
        intent: str,
        rows: list[dict[str, Any]],
        group_by: list[str],
    ) -> ChartRouteDecision:
        score, reasons = self._score_complexity(intent=intent, rows=rows, group_by=group_by)
        has_negative_value = self._has_negative_metric(rows)
        engine = "echarts" if score >= self.COMPLEXITY_THRESHOLD or has_negative_value else "recharts"
        chart_type = self._pick_chart_type(
            engine=engine,
            rows=rows,
            group_by=group_by,
            has_negative_value=has_negative_value,
        )
        if has_negative_value:
            reasons.append("negative_metric_value")
        reasons.append(
            f"complexity_score={score}, threshold={self.COMPLEXITY_THRESHOLD}, selected_engine={engine}"
        )
        return ChartRouteDecision(
            engine=engine,
            chart_type=chart_type,
            complexity_score=score,
            reasons=reasons,
        )

    def build_spec(
        self,
        *,
        metric: str,
        intent: str,
        rows: list[dict[str, Any]],
        group_by: list[str],
    ) -> dict[str, Any]:
        decision = self.route(intent=intent, rows=rows, group_by=group_by)
        normalized_rows, x_key = self._normalize_rows(rows=rows, group_by=group_by)

        base = {
            "engine": decision.engine,
            "chart_type": decision.chart_type,
            "title": metric,
            "data": normalized_rows,
            "route": {
                "complexity_score": decision.complexity_score,
                "threshold": self.COMPLEXITY_THRESHOLD,
                "reasons": decision.reasons,
                "selected_engine": decision.engine,
            },
        }

        if decision.engine == "recharts":
            base["config"] = {
                "xKey": x_key,
                "yKey": "metric_value",
                "series": [{"name": metric, "dataKey": "metric_value"}],
            }
            return base

        categories = [str(item.get(x_key, f"item-{index + 1}")) for index, item in enumerate(normalized_rows)]
        values = [item.get("metric_value", 0) for item in normalized_rows]
        if decision.chart_type == "negative_bar":
            base["config"] = {"option": self._negative_bar_option(categories=categories, values=values, metric=metric)}
            return base

        option = {
            "tooltip": {"trigger": "axis"},
            "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
            "xAxis": {"type": "category", "data": categories, "axisLabel": {"interval": 0, "rotate": 30}},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "name": metric,
                    "type": "line" if len(categories) > 10 else "bar",
                    "smooth": True,
                    "data": values,
                }
            ],
        }
        base["config"] = {"option": option}
        return base

    def _score_complexity(
        self,
        *,
        intent: str,
        rows: list[dict[str, Any]],
        group_by: list[str],
    ) -> tuple[int, list[str]]:
        score = 0
        reasons: list[str] = []

        row_count = len(rows)
        if row_count > 12:
            score += 2
            reasons.append("result_rows>12")
        if row_count > 50:
            score += 2
            reasons.append("result_rows>50")
        if row_count > 200:
            score += 2
            reasons.append("result_rows>200")

        if len(group_by) >= 2:
            score += 2
            reasons.append("multi_dimension_group_by")

        if group_by:
            unique_values = {str(row.get(group_by[0], "")) for row in rows}
            if len(unique_values) > 8:
                score += 2
                reasons.append("high_category_cardinality")

        lowered_intent = intent.lower()
        if any(keyword in lowered_intent for keyword in self.COMPLEXITY_KEYWORDS):
            score += 2
            reasons.append("complex_intent_keyword")

        if not reasons:
            reasons.append("simple_query_shape")

        return score, reasons

    def _pick_chart_type(
        self,
        *,
        engine: str,
        rows: list[dict[str, Any]],
        group_by: list[str],
        has_negative_value: bool = False,
    ) -> str:
        if has_negative_value and group_by:
            return "negative_bar"
        if engine == "echarts":
            return "line" if len(rows) > 10 else "bar"
        if not group_by:
            return "single_value"
        return "bar"

    def _normalize_rows(
        self,
        *,
        rows: list[dict[str, Any]],
        group_by: list[str],
    ) -> tuple[list[dict[str, Any]], str]:
        if rows:
            x_key = group_by[0] if group_by and group_by[0] in rows[0] else "label"
            normalized: list[dict[str, Any]] = []
            for index, row in enumerate(rows):
                if x_key not in row:
                    item = dict(row)
                    item[x_key] = f"item-{index + 1}"
                    normalized.append(item)
                else:
                    normalized.append(row)
            return normalized, x_key

        # Ensure frontend can always render an empty state without null checks.
        return [], (group_by[0] if group_by else "label")

    def _has_negative_metric(self, rows: list[dict[str, Any]]) -> bool:
        for row in rows:
            value = row.get("metric_value")
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) and value < 0:
                return True
        return False

    def _negative_bar_option(
        self,
        *,
        categories: list[str],
        values: list[Any],
        metric: str,
    ) -> dict[str, Any]:
        data = []
        for value in values:
            numeric = value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0
            item: dict[str, Any] = {
                "value": numeric,
                "itemStyle": {"color": "#c96442" if numeric < 0 else "#4b7f8c"},
            }
            if numeric < 0:
                item["label"] = {"position": "right"}
            data.append(item)

        return {
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "grid": {"top": 36, "left": "3%", "right": "4%", "bottom": 20, "containLabel": True},
            "xAxis": {
                "type": "value",
                "position": "top",
                "splitLine": {"lineStyle": {"type": "dashed"}},
            },
            "yAxis": {
                "type": "category",
                "axisLine": {"show": False},
                "axisLabel": {"show": False},
                "axisTick": {"show": False},
                "splitLine": {"show": False},
                "data": categories,
            },
            "series": [
                {
                    "name": metric,
                    "type": "bar",
                    "stack": "Total",
                    "label": {"show": True, "formatter": "{b}"},
                    "data": data,
                }
            ],
        }
