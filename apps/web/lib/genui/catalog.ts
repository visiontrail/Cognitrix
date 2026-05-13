export const GENUI_CATALOG = {
  recharts: [
    "bar",
    "grouped_bar",
    "line",
    "stacked_line",
    "pie",
    "area",
    "scatter",
    "radar",
    "treemap",
    "funnel",
    "radialBar",
    "composed",
    "table",
    "single_value",
    "note",
    "empty"
  ],
  echarts: [
    "bar",
    "negative_bar",
    "grouped_bar",
    "line",
    "stacked_line",
    "pie",
    "scatter",
    "treemap",
    "heatmap",
    "radar",
    "funnel",
    "gauge",
    "sankey",
    "sunburst",
    "boxplot",
    "candlestick",
    "graph",
    "map",
    "parallel",
    "wordCloud"
  ]
} as const;

export type GenUIEngine = keyof typeof GENUI_CATALOG;

export type GenUIChartTypeForEngine<T extends GenUIEngine> = (typeof GENUI_CATALOG)[T][number];

export type GenUIRegistryKey = {
  [E in GenUIEngine]: `${E}:${GenUIChartTypeForEngine<E>}`;
}[GenUIEngine];

export const GENUI_REGISTRY_KEYS: GenUIRegistryKey[] = (Object.entries(GENUI_CATALOG) as Array<
  [GenUIEngine, readonly string[]]
>)
  .flatMap(([engine, chartTypes]) => chartTypes.map((chartType) => `${engine}:${chartType}` as GenUIRegistryKey))
  .sort();

export function isKnownRegistryKey(key: string): key is GenUIRegistryKey {
  return GENUI_REGISTRY_KEYS.includes(key as GenUIRegistryKey);
}
