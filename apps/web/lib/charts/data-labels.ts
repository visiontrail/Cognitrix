import { isRecord } from "@/lib/utils";

/**
 * Force ECharts series to render their underlying data values directly on the
 * chart (on bars, slices, points, …) when the user opts into "show data
 * labels" from the chat composer.
 *
 * The backend (and the frontend fallback builders) emit plain ECharts `option`
 * objects, so this transform is intentionally generic: it walks `option.series`
 * and turns `label.show` on for every series, supplying a value-bearing
 * formatter only when none already exists. That makes the option work for any
 * ECharts chart type without special-casing each one.
 *
 * The transform is non-mutating — it returns shallow copies — so the original
 * spec is never altered in place.
 */

const VALUE_FORMATTER = "{c}";
const NAMED_VALUE_FORMATTER = "{b}: {c}";
const PIE_FORMATTER = "{b}: {c} ({d}%)";

// Series types whose primary datum is a single scalar, so `{c}` renders a
// meaningful value. Types with array/object data (boxplot, candlestick, radar,
// heatmap, parallel, …) are left to ECharts' own default label content.
const SCALAR_VALUE_SERIES = new Set(["bar", "line", "scatter", "effectScatter", "pictorialBar"]);

type EChartsOption = Record<string, unknown>;

export function applyDataLabels(option: EChartsOption): EChartsOption {
  if (!isRecord(option)) {
    return option;
  }
  const series = option.series;
  if (series === undefined || series === null) {
    return option;
  }

  const horizontal = detectHorizontalBars(option);

  if (Array.isArray(series)) {
    if (series.length === 0) {
      return option;
    }
    return { ...option, series: series.map((entry) => withSeriesLabel(entry, horizontal)) };
  }
  if (isRecord(series)) {
    return { ...option, series: withSeriesLabel(series, horizontal) };
  }
  return option;
}

function withSeriesLabel(series: unknown, horizontal: boolean): unknown {
  if (!isRecord(series)) {
    return series;
  }
  const existing = isRecord(series.label) ? series.label : {};
  const type = typeof series.type === "string" ? series.type : "";
  const stacked = typeof series.stack === "string" && series.stack.length > 0;

  const label: Record<string, unknown> = { ...existing, show: true };

  if (existing.position === undefined) {
    const position = defaultPosition(type, { horizontal, stacked });
    if (position) {
      label.position = position;
    }
  }

  const formatter = resolveFormatter(type, existing.formatter);
  if (formatter === undefined) {
    delete label.formatter;
  } else {
    label.formatter = formatter;
  }

  return { ...series, label };
}

function defaultPosition(
  type: string,
  { horizontal, stacked }: { horizontal: boolean; stacked: boolean }
): string | undefined {
  if (type === "bar" || type === "pictorialBar") {
    if (stacked) {
      return "inside";
    }
    return horizontal ? "right" : "top";
  }
  if (type === "line" || type === "scatter" || type === "effectScatter") {
    return "top";
  }
  // pie / funnel / and other advanced types keep their native default position.
  return undefined;
}

function resolveFormatter(type: string, existing: unknown): unknown {
  // Never replace a function formatter — it may compute units or rich text.
  if (typeof existing === "function") {
    return existing;
  }
  const isPieLike = type === "pie" || type === "funnel";
  if (typeof existing === "string" && existing.trim().length > 0) {
    // A percentage-only pie/funnel label hides the raw value the user asked to
    // see, so surface the value alongside it.
    if (isPieLike && existing.includes("{d}") && !existing.includes("{c}")) {
      return type === "pie" ? PIE_FORMATTER : NAMED_VALUE_FORMATTER;
    }
    return existing;
  }
  // No usable formatter: provide a value-bearing default for the types where
  // `{c}` is meaningful; otherwise defer to ECharts' default label content.
  if (isPieLike) {
    return type === "pie" ? PIE_FORMATTER : NAMED_VALUE_FORMATTER;
  }
  if (type === "" || SCALAR_VALUE_SERIES.has(type)) {
    return VALUE_FORMATTER;
  }
  return existing;
}

function detectHorizontalBars(option: EChartsOption): boolean {
  const xHasValue = toAxisList(option.xAxis).some((axis) => axisType(axis) === "value");
  const yHasCategory = toAxisList(option.yAxis).some((axis) => axisType(axis) === "category");
  return xHasValue && yHasCategory;
}

function toAxisList(axis: unknown): Record<string, unknown>[] {
  if (Array.isArray(axis)) {
    return axis.filter(isRecord);
  }
  if (isRecord(axis)) {
    return [axis];
  }
  return [];
}

function axisType(axis: Record<string, unknown>): "value" | "category" | "other" {
  if (typeof axis.type === "string") {
    return axis.type === "value" ? "value" : axis.type === "category" ? "category" : "other";
  }
  // ECharts infers a category axis when `data` is present.
  return Array.isArray(axis.data) ? "category" : "other";
}
