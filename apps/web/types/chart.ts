export type KnownChartType =
  | "bar"
  | "negative_bar"
  | "grouped_bar"
  | "line"
  | "pie"
  | "area"
  | "stacked_bar"
  | "stacked_line"
  | "scatter"
  | "scatter_clustering"
  | "radar"
  | "funnel"
  | "multiple_funnel"
  | "radialBar"
  | "composed"
  | "gauge"
  | "heatmap"
  | "treemap"
  | "sankey"
  | "sunburst"
  | "boxplot"
  | "candlestick"
  | "graph"
  | "map"
  | "parallel"
  | "wordCloud"
  | "table"
  | "single_value"
  | "note"
  | "empty";

// Preserve backend-provided chart types verbatim so the frontend never silently downgrades them.
export type ChartType = KnownChartType | (string & {});

export type ChartSpec = {
  chartType: ChartType;
  title: string;
  subtitle?: string;
  echartsOption: Record<string, unknown>;
  dataSource?: ChartDataSource;
};

export type ChartDataSource = {
  categories: string[];
  series: ChartSeriesData[];
};

export type ChartSeriesData = {
  name: string;
  data: number[];
  type?: string;
};

export type ChartAsset = {
  id: string;
  title: string;
  description?: string;
  chartType: ChartType;
  spec: ChartSpec;
  assistantRows?: Record<string, unknown>[];
  assistantRowsComplete?: boolean;
  sourceMeta: ChartSourceMeta;
  createdAt: string;
  updatedAt: string;
};

export type ChartSourceMeta = {
  sessionId: string;
  messageId: string;
  prompt: string;
  datasetTable?: string;
};

export type ChartValidationResult = {
  valid: boolean;
  errors: string[];
  warnings: string[];
};

export function validateChartSpec(spec: unknown): ChartValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];

  if (!spec || typeof spec !== "object") {
    return { valid: false, errors: ["Chart spec must be an object"], warnings };
  }

  const s = spec as Record<string, unknown>;

  if (!s.chartType || typeof s.chartType !== "string") {
    errors.push("Missing or invalid chartType");
  }

  if (!s.title || typeof s.title !== "string") {
    errors.push("Missing or invalid title");
  }

  if (!s.echartsOption || typeof s.echartsOption !== "object") {
    errors.push("Missing or invalid echartsOption");
  }

  if (s.echartsOption && typeof s.echartsOption === "object") {
    const opt = s.echartsOption as Record<string, unknown>;
    if (!opt.series && !opt.xAxis && !opt.yAxis) {
      warnings.push("ECharts option appears to be missing core config (series/xAxis/yAxis)");
    }
  }

  return { valid: errors.length === 0, errors, warnings };
}
