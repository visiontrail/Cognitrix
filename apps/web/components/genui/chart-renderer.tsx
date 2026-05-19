"use client";

import { ChartPreview } from "@/components/charts/chart-preview";
import { buildGaugeFallbackOption, buildSingleValueFallbackOption } from "@/lib/charts/kpi-options";
import { buildRichTreemapFallbackOption } from "@/lib/charts/treemap-option";
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
  "negative_bar",
  "grouped_bar",
  "line",
  "pie",
  "area",
  "stacked_bar",
  "stacked_line",
  "scatter",
  "scatter_clustering",
  "radar",
  "funnel",
  "multiple_funnel",
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
  "bar-y-category": "grouped_bar",
  "bar_y_category": "grouped_bar",
  "groupedbar": "grouped_bar",
  "grouped-bar": "grouped_bar",
  "horizontal_bar": "grouped_bar",
  "horizontal-bar": "grouped_bar",
  "horizontal_grouped_bar": "grouped_bar",
  "horizontal-grouped-bar": "grouped_bar",
  "negativebar": "negative_bar",
  "negative-bar": "negative_bar",
  "bar-negative": "negative_bar",
  "bar_negative": "negative_bar",
  "bar-negative2": "negative_bar",
  "bar_negative2": "negative_bar",
  "positive_negative_bar": "negative_bar",
  "positive-negative-bar": "negative_bar",
  "scatterclustering": "scatter_clustering",
  "scatter-clustering": "scatter_clustering",
  "scatter_cluster": "scatter_clustering",
  "scatter-cluster": "scatter_clustering",
  "clustered_scatter": "scatter_clustering",
  "clustered-scatter": "scatter_clustering",
  "stackedline": "stacked_line",
  "stacked-line": "stacked_line",
  "singlevalue": "single_value",
  "single-value": "single_value",
  "radialbar": "radialBar",
  "radial_bar": "radialBar",
  "wordcloud": "wordCloud",
  "word_cloud": "wordCloud",
  "funnelmutiple": "multiple_funnel",
  "funnel-mutiple": "multiple_funnel",
  "funnel_mutiple": "multiple_funnel",
  "funnelmultiple": "multiple_funnel",
  "funnel-multiple": "multiple_funnel",
  "funnel_multiple": "multiple_funnel",
  "multiplefunnel": "multiple_funnel",
  "multiple-funnel": "multiple_funnel",
  "multiple-funnels": "multiple_funnel",
  "multiple_funnels": "multiple_funnel",
};
const FALLBACK_OPTION_TYPES = new Set<KnownChartType>([
  "bar",
  "negative_bar",
  "grouped_bar",
  "line",
  "pie",
  "area",
  "stacked_bar",
  "stacked_line",
  "scatter",
  "scatter_clustering",
  "radar",
  "funnel",
  "multiple_funnel",
  "treemap",
  "single_value",
  "gauge",
]);
const FUNNEL_INSIDE_LABEL = {
  show: true,
  position: "inside",
  formatter: "{b}\n{c}",
  color: "#fff",
  fontWeight: 600,
};

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
    const name = configuredYKey ?? yKey ?? "value";
    return chartType === "gauge"
      ? buildGaugeFallbackOption({ title, value, name })
      : buildSingleValueFallbackOption({ title, value, name });
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

  if (chartType === "negative_bar") {
    return {
      title: { text: title, left: "center" },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      grid: { top: 60, left: "3%", right: "4%", bottom: 20, containLabel: true },
      xAxis: {
        type: "value",
        position: "top",
        splitLine: { lineStyle: { type: "dashed" } },
      },
      yAxis: {
        type: "category",
        axisLine: { show: false },
        axisLabel: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        data: categories,
      },
      series: [
        {
          name: configuredYKey ?? yKey,
          type: "bar",
          stack: "Total",
          label: { show: true, formatter: "{b}" },
          data: values.map((value) => ({
            value,
            itemStyle: { color: value < 0 ? "#c96442" : "#4b7f8c" },
            ...(value < 0 ? { label: { position: "right" } } : {}),
          })),
        },
      ],
    };
  }

  if (chartType === "treemap") {
    const nameKey = typeof config.nameKey === "string" ? config.nameKey : null;
    return buildRichTreemapFallbackOption({ rows, title, xKey, yKey, nameKey });
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
          label: FUNNEL_INSIDE_LABEL,
          labelLine: { show: false },
          emphasis: { label: FUNNEL_INSIDE_LABEL },
        },
      ],
    };
  }

  if (chartType === "multiple_funnel") {
    const data = rows.map((row, index) => ({
      name: String(row[xKey] ?? `item-${index + 1}`),
      value: asNumber(row[yKey]),
    }));
    return {
      title: { text: title, left: "left", top: "bottom" },
      tooltip: { trigger: "item", formatter: "{a}<br/>{b}: {c}" },
      legend: { orient: "vertical", left: "left", data: data.map((item) => item.name) },
      series: [
        {
          name: "Funnel",
          type: "funnel",
          width: "40%",
          height: "45%",
          left: "5%",
          top: "50%",
          label: FUNNEL_INSIDE_LABEL,
          labelLine: { show: false },
          emphasis: { label: FUNNEL_INSIDE_LABEL },
          data,
        },
        {
          name: "Pyramid",
          type: "funnel",
          width: "40%",
          height: "45%",
          left: "5%",
          top: "5%",
          sort: "ascending",
          label: FUNNEL_INSIDE_LABEL,
          labelLine: { show: false },
          emphasis: { label: FUNNEL_INSIDE_LABEL },
          data,
        },
        {
          name: "Funnel",
          type: "funnel",
          width: "40%",
          height: "45%",
          left: "55%",
          top: "5%",
          label: FUNNEL_INSIDE_LABEL,
          labelLine: { show: false },
          emphasis: { label: FUNNEL_INSIDE_LABEL },
          data,
        },
        {
          name: "Pyramid",
          type: "funnel",
          width: "40%",
          height: "45%",
          left: "55%",
          top: "50%",
          sort: "ascending",
          label: FUNNEL_INSIDE_LABEL,
          labelLine: { show: false },
          emphasis: { label: FUNNEL_INSIDE_LABEL },
          data,
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
      tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
      legend: { orient: "vertical", left: "left" },
      series: [
        {
          type: "pie",
          radius: "50%",
          data: rows.map((row, index) => ({
            name: String(row[xKey] ?? `item-${index + 1}`),
            value: asNumber(row[yKey]),
          })),
          label: {
            show: true,
            formatter: "{b}\n{d}%",
          },
          labelLine: { show: true },
          emphasis: {
            itemStyle: {
              shadowBlur: 10,
              shadowOffsetX: 0,
              shadowColor: "rgba(0, 0, 0, 0.5)",
            },
          },
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

  if (chartType === "scatter_clustering") {
    return buildScatterClusteringOption({
      rows,
      xKey,
      yKey,
      title,
      labelKey: typeof config.nameKey === "string" ? config.nameKey : null,
    });
  }

  if (chartType === "grouped_bar" || chartType === "stacked_bar") {
    const seriesKey = typeof config.seriesKey === "string" ? config.seriesKey : null;
    if (!seriesKey) {
      const horizontalAxis = chartType === "grouped_bar";
      return {
        title: { text: title, left: "center" },
        tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
        grid: { left: "3%", right: "4%", bottom: "3%", containLabel: true },
        xAxis: horizontalAxis
          ? { type: "value" }
          : { type: "category", data: categories, axisLabel: { interval: 0, rotate: 30 } },
        yAxis: horizontalAxis
          ? { type: "category", data: categories }
          : { type: "value" },
        series: [{ type: "bar", ...(chartType === "stacked_bar" ? { stack: "total" } : {}), data: values }],
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
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      legend: { top: 28 },
      grid: { left: "3%", right: "4%", bottom: "3%", containLabel: true },
      xAxis: chartType === "grouped_bar"
        ? { type: "value" }
        : { type: "category", data: categoryOrder, axisLabel: { interval: 0, rotate: 30 } },
      yAxis: chartType === "grouped_bar"
        ? { type: "category", data: categoryOrder }
        : { type: "value" },
      series: seriesOrder.map((seriesName) => ({
        type: "bar",
        name: seriesName,
        ...(chartType === "stacked_bar" ? { stack: "total" } : {}),
        data: categoryOrder.map((category) => matrix.get(seriesName)?.get(category) ?? 0),
      })),
    };
  }

  if (chartType === "stacked_line") {
    const seriesKey = typeof config.seriesKey === "string" ? config.seriesKey : null;
    const stackedAreaStyle = { opacity: 0.2 };
    if (!seriesKey) {
      return {
        title: { text: title, left: "center" },
        tooltip: { trigger: "axis" },
        grid: { left: "3%", right: "4%", bottom: "3%", containLabel: true },
        xAxis: { type: "category", data: categories, axisLabel: { interval: 0, rotate: 30 } },
        yAxis: { type: "value" },
        series: [{ type: "line", smooth: true, stack: "total", areaStyle: stackedAreaStyle, data: values }],
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
        type: "line",
        name: seriesName,
        smooth: true,
        stack: "total",
        areaStyle: stackedAreaStyle,
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

function buildScatterClusteringOption({
  rows,
  xKey,
  yKey,
  title,
  labelKey,
}: {
  rows: Array<Record<string, unknown>>;
  xKey: string;
  yKey: string;
  title: string;
  labelKey: string | null;
}): Record<string, unknown> {
  const points = rows.map((row, index) => [
    asNumber(row[xKey]),
    asNumber(row[yKey]),
    labelKey ? String(row[labelKey] ?? `item-${index + 1}`) : `item-${index + 1}`,
  ]);
  const clusterCount = Math.min(6, Math.max(2, Math.round(Math.sqrt(Math.max(points.length, 2)))));
  const clusterDimension = 3;
  const colors = ["#37A2DA", "#e06343", "#37a354", "#b55dba", "#b5bd48", "#8378EA"];

  return {
    __requiresEchartsStat__: { transforms: ["clustering"] },
    title: { text: title, left: "center" },
    dataset: [
      { dimensions: [xKey, yKey, "label"], source: points },
      {
        transform: {
          type: "ecStat:clustering",
          config: {
            clusterCount,
            dimensions: [0, 1],
            outputType: "single",
            outputClusterIndexDimension: { index: clusterDimension, name: "cluster" },
            outputCentroidDimensions: [
              { index: 4, name: "centroid_x" },
              { index: 5, name: "centroid_y" },
            ],
          },
        },
      },
    ],
    tooltip: { position: "top" },
    visualMap: {
      type: "piecewise",
      top: "middle",
      min: 0,
      max: clusterCount,
      left: 10,
      splitNumber: clusterCount,
      dimension: clusterDimension,
      pieces: Array.from({ length: clusterCount }, (_, index) => ({
        value: index,
        label: `cluster ${index}`,
        color: colors[index % colors.length],
      })),
    },
    grid: { left: 120, right: 24, top: 56, bottom: 40 },
    xAxis: { type: "value", name: xKey },
    yAxis: { type: "value", name: yKey },
    series: [
      {
        type: "scatter",
        datasetIndex: 1,
        encode: { x: 0, y: 1, tooltip: [2, 0, 1, clusterDimension], itemName: 2 },
        symbolSize: 15,
        itemStyle: { borderColor: "#555" },
      },
    ],
  };
}
