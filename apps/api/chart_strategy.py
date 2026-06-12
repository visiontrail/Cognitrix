from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ChartRouteDecision:
    engine: str
    chart_type: str
    reasons: list[str]


class ChartStrategyRouter:
    """Thin chart routing for the legacy `/semantic/query` endpoint.

    The primary BI flow runs through the Claude Agent SDK, which lets the model
    pick `chart_type`/`engine` directly based on its understanding of the
    question and the returned data. This router only exists for callers that
    do not go through the agent (legacy semantic query). It deliberately makes
    no keyword-, threshold-, or row-count-based decisions: when the caller
    supplies a `chart_type`, we trust it; otherwise we default to a bar chart.
    """

    def route(
        self,
        *,
        intent: str,
        rows: list[dict[str, Any]],
        group_by: list[str],
        chart_type: str | None = None,
        engine: str | None = None,
    ) -> ChartRouteDecision:
        _ = intent
        resolved_chart_type = (chart_type or "").strip() or self._default_chart_type(
            rows=rows, group_by=group_by
        )
        resolved_engine = (engine or "").strip() or self._engine_for_chart_type(resolved_chart_type)
        return ChartRouteDecision(
            engine=resolved_engine,
            chart_type=resolved_chart_type,
            reasons=[f"chart_type={resolved_chart_type}", f"engine={resolved_engine}"],
        )

    def build_spec(
        self,
        *,
        metric: str,
        intent: str,
        rows: list[dict[str, Any]],
        group_by: list[str],
        chart_type: str | None = None,
        engine: str | None = None,
    ) -> dict[str, Any]:
        decision = self.route(
            intent=intent,
            rows=rows,
            group_by=group_by,
            chart_type=chart_type,
            engine=engine,
        )
        normalized_rows, x_key = self._normalize_rows(rows=rows, group_by=group_by)

        base: dict[str, Any] = {
            "engine": decision.engine,
            "chart_type": decision.chart_type,
            "title": metric,
            "data": normalized_rows,
            "route": {
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
        if decision.chart_type == "funnel":
            base["config"] = {
                "option": self._funnel_option(categories=categories, values=values)
            }
            return base

        option = {
            "tooltip": {"trigger": "axis"},
            "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
            "xAxis": {"type": "category", "data": categories, "axisLabel": {"interval": 0, "rotate": 30}},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "name": metric,
                    "type": decision.chart_type if decision.chart_type in {"line", "bar"} else "bar",
                    "smooth": True,
                    "data": values,
                }
            ],
        }
        base["config"] = {"option": option}
        return base

    def _default_chart_type(
        self,
        *,
        rows: list[dict[str, Any]],
        group_by: list[str],
    ) -> str:
        if self._has_negative_metric(rows) and group_by:
            return "negative_bar"
        if not group_by:
            return "single_value"
        return "bar"

    @staticmethod
    def _engine_for_chart_type(chart_type: str) -> str:
        # Recharts owns only the simple, default chart shapes. Any explicit
        # request for a richer type (line, scatter, treemap, heatmap, …) goes
        # to ECharts so we honour the caller's intent without second-guessing.
        recharts_supported = {"bar", "table", "single_value"}
        return "recharts" if chart_type in recharts_supported else "echarts"

    @staticmethod
    def _funnel_option(
        *,
        categories: list[str],
        values: list[Any],
    ) -> dict[str, Any]:
        inside_label = {
            "show": True,
            "position": "inside",
            "formatter": "{b}\n{c} ({d}%)",
            "color": "#fff",
            "fontWeight": 600,
        }
        return {
            "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
            "legend": {"show": False},
            "series": [
                {
                    "type": "funnel",
                    "left": "10%",
                    "width": "80%",
                    "data": [
                        {"name": category, "value": value}
                        for category, value in zip(categories, values, strict=False)
                    ],
                    "label": inside_label,
                    "labelLine": {"show": False},
                    "emphasis": {"label": inside_label},
                }
            ],
        }

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
