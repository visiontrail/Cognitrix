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
    )

    def route(
        self,
        *,
        intent: str,
        rows: list[dict[str, Any]],
        group_by: list[str],
    ) -> ChartRouteDecision:
        score, reasons = self._score_complexity(intent=intent, rows=rows, group_by=group_by)
        engine = "echarts" if score >= self.COMPLEXITY_THRESHOLD else "recharts"
        chart_type = self._pick_chart_type(engine=engine, rows=rows, group_by=group_by)
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

        categories = [
            self._truncate_label(str(item.get(x_key, f"item-{index + 1}")))
            for index, item in enumerate(normalized_rows)
        ]
        values = [item.get("metric_value", 0) for item in normalized_rows]
        option = {
            "tooltip": {"trigger": "axis"},
            "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
            "xAxis": {"type": "category", "data": categories, "axisLabel": self._build_axis_label(categories)},
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

    def _pick_chart_type(self, *, engine: str, rows: list[dict[str, Any]], group_by: list[str]) -> str:
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

    @staticmethod
    def _truncate_label(label: str, max_len: int = 14) -> str:
        if len(label) <= max_len:
            return label
        return label[: max_len - 1] + "…"

    @staticmethod
    def _build_axis_label(categories: list[str]) -> dict:
        count = len(categories)
        max_len = max((len(c) for c in categories), default=0)
        if count <= 5 and max_len <= 8:
            return {"interval": 0}
        # Fewer / shorter labels: gentle 30° tilt; many / long labels: steeper 45°
        rotate = 30 if (count <= 10 or max_len <= 6) else 45
        width = 90 if rotate == 30 else 70
        return {"interval": 0, "rotate": rotate, "overflow": "truncate", "width": width}
