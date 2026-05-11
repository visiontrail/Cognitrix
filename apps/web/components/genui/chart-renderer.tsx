"use client";

import { ChartPreview } from "@/components/charts/chart-preview";
import { isRecord } from "@/lib/utils";
import type { ChartSpec, ChartType, KnownChartType } from "@/types/chart";

type LegacyGenUISpec = {
  engine?: string;
  chart_type?: string;
  title: string;
  data?: Array<Record<string, unknown>>;
  config?: Record<string, unknown>;
};

export function ChartRenderer({ spec }: { spec: LegacyGenUISpec }) {
  const mapped = mapLegacySpec(spec);
  if (!mapped) {
    return (
      <div className="p-4 text-center text-stone-gray">
        <p>Unsupported chart spec format</p>
      </div>
    );
  }

  return (
    <div className="rounded-comfortable overflow-hidden">
      <ChartPreview spec={mapped} height={320} />
    </div>
  );
}

function mapLegacySpec(spec: LegacyGenUISpec): ChartSpec | null {
  const chartType = normalizeChartType(spec.chart_type);
  if (chartType === "empty") {
    return null;
  }

  const option = resolveOption(spec, chartType);
  if (!option) {
    return null;
  }

  return {
    chartType,
    title: spec.title,
    echartsOption: option,
  };
}

const SUPPORTED_CHART_TYPES = new Set<KnownChartType>([
  "bar",
  "line",
  "pie",
  "area",
  "stacked_bar",
  "scatter",
  "radar",
  "funnel",
  "radialBar",
  "composed",
  "gauge",
  "heatmap",
  "treemap",
  "sankey",
  "sunburst",
  "boxplot",
  "candlestick",
  "graph",
  "map",
  "parallel",
  "wordCloud",
  "table",
  "single_value",
  "note",
  "empty",
]);
const SUPPORTED_CHART_TYPES_BY_LOWER = new Map<string, KnownChartType>(
  Array.from(SUPPORTED_CHART_TYPES).map((item) => [item.toLowerCase(), item])
);
const CHART_TYPE_ALIASES: Record<string, KnownChartType> = {
  "stackedbar": "stacked_bar",
  "stacked-bar": "stacked_bar",
  "singlevalue": "single_value",
  "single-value": "single_value",
  "radialbar": "radialBar",
  "radial_bar": "radialBar",
  "wordcloud": "wordCloud",
  "word_cloud": "wordCloud",
};
const FALLBACK_OPTION_TYPES = new Set<KnownChartType>([
  "bar",
  "line",
  "pie",
  "area",
  "stacked_bar",
  "scatter",
  "radar",
  "funnel",
  "treemap",
  "single_value",
  "gauge",
]);

function normalizeChartType(rawChartType: unknown): ChartType {
  const normalized = String(rawChartType ?? "bar").trim();
  if (!normalized) {
    return "bar";
  }

  if (SUPPORTED_CHART_TYPES.has(normalized as KnownChartType)) {
    return normalized as KnownChartType;
  }

  const lowered = normalized.toLowerCase();
  const canonical = SUPPORTED_CHART_TYPES_BY_LOWER.get(lowered);
  if (canonical) {
    return canonical;
  }

  const aliased = CHART_TYPE_ALIASES[lowered];
  if (aliased) {
    return aliased;
  }

  return normalized as ChartType;
}

function resolveOption(spec: LegacyGenUISpec, chartType: ChartType): Record<string, unknown> | null {
  const config = isRecord(spec.config) ? spec.config : {};
  const rawOption = config.option;
  if (isRecord(rawOption)) {
    return rawOption;
  }

  const rows = Array.isArray(spec.data) ? spec.data.filter(isRecord) : [];
  const title = spec.title || "Chart";
  const configuredYKey = typeof config.yKey === "string" ? config.yKey : null;

  if (chartType === "single_value" || chartType === "gauge") {
    const yKey = configuredYKey ?? inferYKey(rows, null);
    const value = rows.length > 0 && yKey ? asNumber(rows[0]?.[yKey]) : 0;
    return {
      title: { text: title, left: "center" },
      series: [
        {
          type: "gauge",
          detail: { formatter: "{value}" },
          data: [{ value, name: configuredYKey ?? yKey ?? "value" }],
        },
      ],
    };
  }

  if (!FALLBACK_OPTION_TYPES.has(chartType as KnownChartType)) {
    // Never remap unsupported/advanced types to another type on the frontend.
    return null;
  }

  const xKey = typeof config.xKey === "string" ? config.xKey : inferXKey(rows);
  const yKey = configuredYKey ?? inferYKey(rows, xKey);
  if (!xKey || !yKey) {
    return null;
  }

  const categories = rows.map((row, index) => String(row[xKey] ?? `item-${index + 1}`));
  const values = rows.map((row) => asNumber(row[yKey]));

  if (chartType === "treemap") {
    return {
      title: { text: title, left: "center" },
      series: [
        {
          type: "treemap",
          roam: false,
          nodeClick: false,
          data: rows.map((row, index) => ({
            name: String(row[xKey] ?? `item-${index + 1}`),
            value: asNumber(row[yKey]),
          })),
        },
      ],
    };
  }

  if (chartType === "funnel") {
    return {
      title: { text: title, left: "center" },
      tooltip: { trigger: "item" },
      series: [
        {
          type: "funnel",
          left: "10%",
          top: 60,
          bottom: 20,
          width: "80%",
          data: rows.map((row, index) => ({
            name: String(row[xKey] ?? `item-${index + 1}`),
            value: asNumber(row[yKey]),
          })),
        },
      ],
    };
  }

  if (chartType === "radar") {
    const maxValue = Math.max(1, ...values);
    return {
      title: { text: title, left: "center" },
      tooltip: {},
      radar: {
        indicator: categories.map((name) => ({
          name,
          max: Math.ceil(maxValue * 1.2),
        })),
      },
      series: [
        {
          type: "radar",
          data: [{ value: values, name: title }],
        },
      ],
    };
  }

  if (chartType === "pie") {
    return {
      title: { text: title, left: "center" },
      tooltip: { trigger: "item" },
      series: [
        {
          type: "pie",
          radius: "65%",
          data: rows.map((row, index) => ({
            name: String(row[xKey] ?? `item-${index + 1}`),
            value: asNumber(row[yKey]),
          })),
        },
      ],
    };
  }

  if (chartType === "scatter") {
    const points = rows.map((row, index) => {
      const xValue = row[xKey];
      if (typeof xValue === "number") {
        return [xValue, asNumber(row[yKey])];
      }
      return [index + 1, asNumber(row[yKey])];
    });
    return {
      title: { text: title, left: "center" },
      tooltip: { trigger: "item" },
      xAxis: { type: "value", name: xKey },
      yAxis: { type: "value", name: yKey },
      series: [{ type: "scatter", data: points }],
    };
  }

  if (chartType === "stacked_bar") {
    const seriesKey = typeof config.seriesKey === "string" ? config.seriesKey : null;
    if (!seriesKey) {
      return {
        title: { text: title, left: "center" },
        tooltip: { trigger: "axis" },
        grid: { left: "3%", right: "4%", bottom: "3%", containLabel: true },
        xAxis: { type: "category", data: categories, axisLabel: { interval: 0, rotate: 30 } },
        yAxis: { type: "value" },
        series: [{ type: "bar", stack: "total", data: values }],
      };
    }

    const categoryOrder: string[] = [];
    const categorySet = new Set<string>();
    const seriesOrder: string[] = [];
    const seriesSet = new Set<string>();
    const matrix = new Map<string, Map<string, number>>();

    for (const row of rows) {
      const category = String(row[xKey] ?? "");
      const seriesName = String(row[seriesKey] ?? "");
      if (!categorySet.has(category)) {
        categorySet.add(category);
        categoryOrder.push(category);
      }
      if (!seriesSet.has(seriesName)) {
        seriesSet.add(seriesName);
        seriesOrder.push(seriesName);
      }
      const rowMap = matrix.get(seriesName) ?? new Map<string, number>();
      rowMap.set(category, asNumber(row[yKey]));
      matrix.set(seriesName, rowMap);
    }

    return {
      title: { text: title, left: "center" },
      tooltip: { trigger: "axis" },
      legend: { top: 28 },
      grid: { left: "3%", right: "4%", bottom: "3%", containLabel: true },
      xAxis: { type: "category", data: categoryOrder, axisLabel: { interval: 0, rotate: 30 } },
      yAxis: { type: "value" },
      series: seriesOrder.map((seriesName) => ({
        type: "bar",
        name: seriesName,
        stack: "total",
        data: categoryOrder.map((category) => matrix.get(seriesName)?.get(category) ?? 0),
      })),
    };
  }

  const seriesType = chartType === "line" || chartType === "area" ? "line" : "bar";
  return {
    title: { text: title, left: "center" },
    tooltip: { trigger: "axis" },
    grid: { left: "3%", right: "4%", bottom: "3%", containLabel: true },
    xAxis: { type: "category", data: categories, axisLabel: { interval: 0, rotate: 30 } },
    yAxis: { type: "value" },
    series: [
      {
        type: seriesType,
        data: values,
        smooth: chartType === "line" || chartType === "area",
        ...(chartType === "area" ? { areaStyle: {} } : {}),
      },
    ],
  };
}

function inferXKey(rows: Array<Record<string, unknown>>): string | null {
  if (!rows.length) {
    return null;
  }
  const keys = Object.keys(rows[0] ?? {});
  if (!keys.length) {
    return null;
  }
  if (keys.includes("label")) {
    return "label";
  }
  const stringKey = keys.find((key) => typeof rows[0]?.[key] === "string");
  return stringKey ?? keys[0];
}

function inferYKey(rows: Array<Record<string, unknown>>, xKey: string | null): string | null {
  if (!rows.length) {
    return null;
  }
  const firstRow = rows[0];
  const keys = Object.keys(firstRow);
  const numberKey = keys.find((key) => key !== xKey && typeof firstRow[key] === "number");
  if (numberKey) {
    return numberKey;
  }
  if (keys.includes("metric_value")) {
    return "metric_value";
  }
  return keys.find((key) => key !== xKey) ?? null;
}

function asNumber(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return 0;
}

