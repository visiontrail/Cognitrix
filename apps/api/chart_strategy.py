from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ChartRouteDecision:
    engine: str
    chart_type: str
    reasons: list[str]


class ChartStrategyRouter:
    """Resolve chart routing and build persistence-ready visualization specs.

    The primary BI flow runs through the Claude Agent SDK, which lets the model
    pick `chart_type`/`engine` directly based on its understanding of the
    question and the returned data. Legacy semantic queries and atomic Agent
    Canvas `place_chart` calls use this router to turn that decision into a
    complete spec. It deliberately makes no keyword-, threshold-, or
    row-count-based decisions: when the caller supplies a `chart_type`, we
    trust it; otherwise the data shape chooses a conservative default.
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
        y_key = self._metric_key(normalized_rows, x_key=x_key)
        series_key = self._series_key(normalized_rows, group_by=group_by, x_key=x_key)

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

        # Canvas and persisted assets render through ECharts even when the
        # route metadata says "recharts". Always persist a complete option so
        # a fresh client does not need to reconstruct (or accidentally
        # downgrade) the selected visual family.
        option = self._build_option(
            chart_type=decision.chart_type,
            rows=normalized_rows,
            x_key=x_key,
            y_key=y_key,
            series_key=series_key,
            metric=metric,
        )
        config: dict[str, Any] = {
            "xKey": x_key,
            "yKey": y_key,
            "series": [{"name": metric, "dataKey": y_key}],
            "option": option,
        }
        if series_key:
            config["seriesKey"] = series_key
        base["config"] = config
        return base

    def _build_option(
        self,
        *,
        chart_type: str,
        rows: list[dict[str, Any]],
        x_key: str,
        y_key: str,
        series_key: str | None,
        metric: str,
    ) -> dict[str, Any]:
        categories = [str(row.get(x_key, f"item-{index + 1}")) for index, row in enumerate(rows)]
        values = [row.get(y_key, 0) for row in rows]

        if chart_type == "single_value":
            return self._single_value_option(value=values[0] if values else 0, metric=metric)
        if chart_type == "gauge":
            return self._gauge_option(value=values[0] if values else 0, metric=metric)
        if chart_type == "table":
            columns = list(rows[0]) if rows else []
            return {
                "__table__": True,
                "__columns__": columns,
                "__rows__": rows,
                "__title__": metric,
                "series": [],
            }
        if chart_type == "pie":
            return self._pie_option(categories=categories, values=values)
        if chart_type == "funnel":
            return self._funnel_option(categories=categories, values=values)
        if chart_type == "treemap":
            return self._treemap_option(categories=categories, values=values)
        if chart_type == "radar":
            return self._radar_option(
                rows=rows,
                categories=categories,
                x_key=x_key,
                y_key=y_key,
                series_key=series_key,
                metric=metric,
            )
        if chart_type == "scatter":
            return self._scatter_option(rows=rows, x_key=x_key, y_key=y_key, metric=metric)
        if chart_type == "heatmap":
            return self._heatmap_option(
                rows=rows, x_key=x_key, y_key=y_key, series_key=series_key, metric=metric
            )
        if chart_type == "negative_bar":
            return self._negative_bar_option(categories=categories, values=values, metric=metric)

        return self._cartesian_option(
            chart_type=chart_type,
            rows=rows,
            x_key=x_key,
            y_key=y_key,
            series_key=series_key,
            metric=metric,
        )

    @staticmethod
    def _single_value_option(*, value: Any, metric: str) -> dict[str, Any]:
        numeric = ChartStrategyRouter._chart_number(value)
        return {
            "tooltip": {"trigger": "item", "formatter": f"{metric}: {numeric}"},
            "series": [],
            "graphic": [
                {
                    "type": "text",
                    "left": "center",
                    "top": "middle",
                    "style": {
                        "text": str(numeric),
                        "fontSize": 58,
                        "fontWeight": 800,
                        "textAlign": "center",
                    },
                }
            ],
        }

    @staticmethod
    def _gauge_option(*, value: Any, metric: str) -> dict[str, Any]:
        numeric = ChartStrategyRouter._chart_number(value)
        maximum = 100 if numeric <= 100 else max(1, int(numeric * 1.2))
        return {
            "tooltip": {"formatter": "{a}<br/>{b}: {c}"},
            "series": [
                {
                    "name": metric,
                    "type": "gauge",
                    "max": maximum,
                    "progress": {"show": True},
                    "detail": {"valueAnimation": True, "formatter": "{value}"},
                    "data": [{"value": numeric, "name": metric}],
                }
            ],
        }

    @staticmethod
    def _pie_option(*, categories: list[str], values: list[Any]) -> dict[str, Any]:
        return {
            "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
            "legend": {"type": "scroll", "bottom": 0},
            "series": [
                {
                    "type": "pie",
                    "radius": ["35%", "65%"],
                    "data": [
                        {"name": category, "value": ChartStrategyRouter._chart_number(value)}
                        for category, value in zip(categories, values, strict=False)
                    ],
                }
            ],
        }

    @staticmethod
    def _treemap_option(*, categories: list[str], values: list[Any]) -> dict[str, Any]:
        return {
            "tooltip": {"trigger": "item"},
            "series": [
                {
                    "type": "treemap",
                    "roam": False,
                    "label": {"show": True, "formatter": "{b}"},
                    "data": [
                        {"name": category, "value": ChartStrategyRouter._chart_number(value)}
                        for category, value in zip(categories, values, strict=False)
                    ],
                }
            ],
        }

    @staticmethod
    def _scatter_option(
        *, rows: list[dict[str, Any]], x_key: str, y_key: str, metric: str
    ) -> dict[str, Any]:
        return {
            "tooltip": {"trigger": "item"},
            "xAxis": {"type": "value", "name": x_key},
            "yAxis": {"type": "value", "name": y_key},
            "series": [
                {
                    "name": metric,
                    "type": "scatter",
                    "data": [
                        [
                            ChartStrategyRouter._chart_number(row.get(x_key)),
                            ChartStrategyRouter._chart_number(row.get(y_key)),
                        ]
                        for row in rows
                    ],
                }
            ],
        }

    @staticmethod
    def _radar_option(
        *,
        rows: list[dict[str, Any]],
        categories: list[str],
        x_key: str,
        y_key: str,
        series_key: str | None,
        metric: str,
    ) -> dict[str, Any]:
        unique_categories = list(dict.fromkeys(categories))
        maximums = {
            category: max(
                [
                    ChartStrategyRouter._chart_number(row.get(y_key))
                    for row in rows
                    if str(row.get(x_key)) == category
                ]
                or [0]
            )
            for category in unique_categories
        }
        indicators = [
            {"name": category, "max": max(1, maximums[category] * 1.2)}
            for category in unique_categories
        ]
        if series_key:
            names = list(dict.fromkeys(str(row.get(series_key, "")) for row in rows))
            matrix = {
                (str(row.get(series_key, "")), str(row.get(x_key, ""))): row.get(y_key, 0)
                for row in rows
            }
            data = [
                {
                    "name": name,
                    "value": [
                        ChartStrategyRouter._chart_number(matrix.get((name, category), 0))
                        for category in unique_categories
                    ],
                }
                for name in names
            ]
        else:
            data = [
                {
                    "name": metric,
                    "value": [ChartStrategyRouter._chart_number(row.get(y_key)) for row in rows],
                }
            ]
        return {
            "tooltip": {},
            "legend": {"bottom": 0} if series_key else {"show": False},
            "radar": {"indicator": indicators},
            "series": [{"type": "radar", "data": data}],
        }

    @staticmethod
    def _heatmap_option(
        *,
        rows: list[dict[str, Any]],
        x_key: str,
        y_key: str,
        series_key: str | None,
        metric: str,
    ) -> dict[str, Any]:
        x_categories = list(dict.fromkeys(str(row.get(x_key, "")) for row in rows))
        resolved_series_key = series_key or "series"
        y_categories = list(
            dict.fromkeys(str(row.get(resolved_series_key, metric)) for row in rows)
        )
        data = [
            [
                x_categories.index(str(row.get(x_key, ""))),
                y_categories.index(str(row.get(resolved_series_key, metric))),
                ChartStrategyRouter._chart_number(row.get(y_key)),
            ]
            for row in rows
        ]
        maximum = max([point[2] for point in data] or [0])
        return {
            "tooltip": {"position": "top"},
            "grid": {"left": "3%", "right": "8%", "bottom": 60, "containLabel": True},
            "xAxis": {"type": "category", "data": x_categories},
            "yAxis": {"type": "category", "data": y_categories},
            "visualMap": {"min": 0, "max": max(1, maximum), "calculable": True, "bottom": 0},
            "series": [{"name": metric, "type": "heatmap", "data": data}],
        }

    @staticmethod
    def _cartesian_option(
        *,
        chart_type: str,
        rows: list[dict[str, Any]],
        x_key: str,
        y_key: str,
        series_key: str | None,
        metric: str,
    ) -> dict[str, Any]:
        categories = list(dict.fromkeys(str(row.get(x_key, "")) for row in rows))
        render_type = "line" if chart_type in {"line", "stacked_line", "area"} else "bar"
        stacked = chart_type in {"stacked_bar", "stacked_line"}
        area = chart_type == "area"
        if series_key:
            names = list(dict.fromkeys(str(row.get(series_key, "")) for row in rows))
            matrix = {
                (str(row.get(series_key, "")), str(row.get(x_key, ""))): row.get(y_key, 0)
                for row in rows
            }
            series = [
                {
                    "name": name,
                    "type": render_type,
                    "data": [
                        ChartStrategyRouter._chart_number(matrix.get((name, category), 0))
                        for category in categories
                    ],
                    **({"stack": "total"} if stacked else {}),
                    **({"areaStyle": {"opacity": 0.35}} if area else {}),
                }
                for name in names
            ]
        else:
            series = [
                {
                    "name": metric,
                    "type": render_type,
                    "data": [ChartStrategyRouter._chart_number(row.get(y_key)) for row in rows],
                    **({"stack": "total"} if stacked else {}),
                    **({"areaStyle": {"opacity": 0.35}} if area else {}),
                }
            ]
        return {
            "tooltip": {"trigger": "axis"},
            "legend": {"top": 0} if series_key else {"show": False},
            "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
            "xAxis": {
                "type": "category",
                "data": categories,
                "axisLabel": {"interval": 0, "rotate": 30},
            },
            "yAxis": {"type": "value"},
            "series": series,
        }

    @staticmethod
    def _chart_number(value: Any) -> float | int:
        if isinstance(value, bool) or value is None:
            return 0
        if isinstance(value, (int, float)):
            return value if value == value else 0
        try:
            parsed = float(str(value))
        except (TypeError, ValueError):
            return 0
        return parsed if parsed == parsed else 0

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
        recharts_supported = {"bar", "pie", "table", "single_value"}
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
            first = rows[0]
            requested = next((key for key in group_by if key in first), None)
            x_key = requested or ("segment" if "segment" in first else next(iter(first), "label"))
            return rows, x_key

        return [], (group_by[0] if group_by else "label")

    @staticmethod
    def _metric_key(rows: list[dict[str, Any]], *, x_key: str) -> str:
        if rows and "metric_value" in rows[0]:
            return "metric_value"
        if rows:
            for key, value in rows[0].items():
                if key == x_key or key == "series" or isinstance(value, bool):
                    continue
                if isinstance(value, (int, float)):
                    return key
        return "metric_value"

    @staticmethod
    def _series_key(
        rows: list[dict[str, Any]], *, group_by: list[str], x_key: str
    ) -> str | None:
        if not rows:
            return None
        first = rows[0]
        if "series" in first:
            return "series"
        return next((key for key in group_by if key != x_key and key in first), None)

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
