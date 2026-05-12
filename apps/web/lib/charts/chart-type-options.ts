import type { KnownChartType } from "@/types/chart";
import type { Locale } from "@/lib/i18n/dictionary";

export type QueryChartType = Extract<
  KnownChartType,
  | "bar"
  | "stacked_bar"
  | "stacked_line"
  | "line"
  | "area"
  | "scatter"
  | "pie"
  | "funnel"
  | "radar"
  | "treemap"
  | "sunburst"
  | "sankey"
  | "graph"
  | "boxplot"
  | "candlestick"
  | "map"
  | "heatmap"
  | "parallel"
  | "gauge"
  | "single_value"
  | "wordCloud"
  | "table"
>;

export type ChartTypeOption = {
  type: QueryChartType;
  label: string;
  description: string;
  group: string;
};

type LocalizedText = Record<Locale, string>;

type ChartTypeOptionDefinition = {
  type: QueryChartType;
  label: LocalizedText;
  description: LocalizedText;
  group: LocalizedText;
};

const QUERY_CHART_TYPE_DEFINITIONS: ChartTypeOptionDefinition[] = [
  {
    type: "bar",
    label: { "en-US": "Bar", "zh-CN": "柱状图" },
    description: { "en-US": "Compare categorical values.", "zh-CN": "比较不同类别的数值。" },
    group: { "en-US": "Comparison", "zh-CN": "比较" },
  },
  {
    type: "stacked_bar",
    label: { "en-US": "Stacked bar", "zh-CN": "堆叠柱状图" },
    description: { "en-US": "Compare totals by stacked groups.", "zh-CN": "按堆叠分组比较总量。" },
    group: { "en-US": "Comparison", "zh-CN": "比较" },
  },
  {
    type: "stacked_line",
    label: { "en-US": "Stacked line", "zh-CN": "堆叠折线图" },
    description: { "en-US": "Show cumulative trends by stacked series.", "zh-CN": "按系列堆叠展示累计趋势。" },
    group: { "en-US": "Trend", "zh-CN": "趋势" },
  },
  {
    type: "line",
    label: { "en-US": "Line", "zh-CN": "折线图" },
    description: { "en-US": "Show trends over time or order.", "zh-CN": "展示时间或顺序上的趋势。" },
    group: { "en-US": "Trend", "zh-CN": "趋势" },
  },
  {
    type: "area",
    label: { "en-US": "Area", "zh-CN": "面积图" },
    description: { "en-US": "Trend with filled volume.", "zh-CN": "用填充面积展示趋势规模。" },
    group: { "en-US": "Trend", "zh-CN": "趋势" },
  },
  {
    type: "scatter",
    label: { "en-US": "Scatter", "zh-CN": "散点图" },
    description: { "en-US": "Show correlation between numeric fields.", "zh-CN": "展示数值字段之间的相关性。" },
    group: { "en-US": "Distribution", "zh-CN": "分布" },
  },
  {
    type: "pie",
    label: { "en-US": "Pie", "zh-CN": "饼图" },
    description: { "en-US": "Show share of a whole.", "zh-CN": "展示整体中的占比。" },
    group: { "en-US": "Share", "zh-CN": "占比" },
  },
  {
    type: "funnel",
    label: { "en-US": "Funnel", "zh-CN": "漏斗图" },
    description: { "en-US": "Show pipeline or conversion stages.", "zh-CN": "展示流程或转化阶段。" },
    group: { "en-US": "Process", "zh-CN": "流程" },
  },
  {
    type: "radar",
    label: { "en-US": "Radar", "zh-CN": "雷达图" },
    description: { "en-US": "Compare multiple dimensions.", "zh-CN": "比较多个维度的表现。" },
    group: { "en-US": "Comparison", "zh-CN": "比较" },
  },
  {
    type: "treemap",
    label: { "en-US": "Treemap", "zh-CN": "矩形树图" },
    description: { "en-US": "Show hierarchical part-to-whole blocks.", "zh-CN": "用层级矩形展示整体与部分关系。" },
    group: { "en-US": "Hierarchy", "zh-CN": "层级" },
  },
  {
    type: "sunburst",
    label: { "en-US": "Sunburst", "zh-CN": "旭日图" },
    description: { "en-US": "Show nested hierarchy as rings.", "zh-CN": "用环形层级展示嵌套结构。" },
    group: { "en-US": "Hierarchy", "zh-CN": "层级" },
  },
  {
    type: "sankey",
    label: { "en-US": "Sankey", "zh-CN": "桑基图" },
    description: { "en-US": "Show weighted flow between stages.", "zh-CN": "展示阶段之间带权重的流向。" },
    group: { "en-US": "Flow", "zh-CN": "流向" },
  },
  {
    type: "graph",
    label: { "en-US": "Graph", "zh-CN": "关系图" },
    description: { "en-US": "Show relationships or networks.", "zh-CN": "展示实体关系或网络结构。" },
    group: { "en-US": "Relationship", "zh-CN": "关系" },
  },
  {
    type: "boxplot",
    label: { "en-US": "Boxplot", "zh-CN": "箱线图" },
    description: { "en-US": "Show statistical distribution.", "zh-CN": "展示统计分布特征。" },
    group: { "en-US": "Statistics", "zh-CN": "统计" },
  },
  {
    type: "candlestick",
    label: { "en-US": "Candlestick", "zh-CN": "K 线图" },
    description: { "en-US": "Show OHLC financial values.", "zh-CN": "展示开高低收等金融数据。" },
    group: { "en-US": "Finance", "zh-CN": "金融" },
  },
  {
    type: "map",
    label: { "en-US": "China map", "zh-CN": "中国地图" },
    description: { "en-US": "Show province-level choropleth values.", "zh-CN": "展示省级区域分布数值。" },
    group: { "en-US": "Geography", "zh-CN": "地理" },
  },
  {
    type: "heatmap",
    label: { "en-US": "Heatmap", "zh-CN": "热力图" },
    description: { "en-US": "Show intensity across a 2D grid.", "zh-CN": "展示二维网格上的强度分布。" },
    group: { "en-US": "Intensity", "zh-CN": "强度" },
  },
  {
    type: "parallel",
    label: { "en-US": "Parallel", "zh-CN": "平行坐标图" },
    description: { "en-US": "Compare many numeric dimensions.", "zh-CN": "比较多个数值维度。" },
    group: { "en-US": "Multivariate", "zh-CN": "多变量" },
  },
  {
    type: "gauge",
    label: { "en-US": "Gauge", "zh-CN": "仪表盘" },
    description: { "en-US": "Show one KPI on a dial.", "zh-CN": "用表盘展示单个 KPI。" },
    group: { "en-US": "KPI", "zh-CN": "指标" },
  },
  {
    type: "single_value",
    label: { "en-US": "Single value", "zh-CN": "单值卡" },
    description: { "en-US": "Show one headline metric.", "zh-CN": "展示一个核心指标值。" },
    group: { "en-US": "KPI", "zh-CN": "指标" },
  },
  {
    type: "wordCloud",
    label: { "en-US": "Word cloud", "zh-CN": "词云" },
    description: { "en-US": "Show weighted words or tags.", "zh-CN": "展示带权重的词语或标签。" },
    group: { "en-US": "Text", "zh-CN": "文本" },
  },
  {
    type: "table",
    label: { "en-US": "Table", "zh-CN": "表格" },
    description: { "en-US": "Show structured multi-column data.", "zh-CN": "展示结构化的多列表数据。" },
    group: { "en-US": "Tabular", "zh-CN": "表格" },
  },
];

export function getQueryChartTypeOptions(locale: Locale): ChartTypeOption[] {
  return QUERY_CHART_TYPE_DEFINITIONS.map((item) => ({
    type: item.type,
    label: item.label[locale],
    description: item.description[locale],
    group: item.group[locale],
  }));
}

export const QUERY_CHART_TYPE_OPTIONS: ChartTypeOption[] = getQueryChartTypeOptions("en-US");

const QUERY_CHART_TYPE_SET = new Set<string>(QUERY_CHART_TYPE_DEFINITIONS.map((item) => item.type));

export function isQueryChartType(value: string): value is QueryChartType {
  return QUERY_CHART_TYPE_SET.has(value);
}

export function findQueryChartType(value: string): QueryChartType | null {
  return isQueryChartType(value) ? value : null;
}
