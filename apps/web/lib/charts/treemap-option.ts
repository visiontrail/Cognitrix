import { isRecord } from "@/lib/utils";

const RICH_TREEMAP_MARKER = "__cognitrixRichTreemap";

type TreeField = {
  name: string;
  value: string;
};

type TreemapNode = {
  id: string;
  name: string;
  value: [number, number, number];
  metricValue: number;
  shareOfTotal: number;
  shareOfParent: number;
  itemCount: number;
  groupName?: string;
  metricLabel: string;
  rawFields?: TreeField[];
  children?: TreemapNode[];
};

type TreemapFormatterParams = {
  name?: unknown;
  value?: unknown;
  color?: unknown;
  data?: unknown;
  treePathInfo?: Array<{ name?: string }>;
};

type TreemapText = {
  ofTotal: string;
  shareOfTotal: string;
  shareOfParent: string;
  items: string;
};

export function buildRichTreemapFallbackOption({
  rows,
  title,
  xKey,
  yKey,
  nameKey,
}: {
  rows: Array<Record<string, unknown>>;
  title: string;
  xKey: string;
  yKey: string;
  nameKey?: string | null;
}): Record<string, unknown> {
  const values = rows.map((row) => Math.max(asNumber(row[yKey]), 0));
  const total = values.reduce((sum, value) => sum + value, 0) || 1;
  const groups = new Map<string, Array<{ row: Record<string, unknown>; index: number; value: number }>>();

  rows.forEach((row, index) => {
    const groupName = String(row[xKey] ?? "other");
    const groupRows = groups.get(groupName) ?? [];
    groupRows.push({ row, index, value: values[index] ?? 0 });
    groups.set(groupName, groupRows);
  });

  const buildLeaf = (
    row: Record<string, unknown>,
    index: number,
    groupName: string | undefined,
    parentTotal: number
  ): TreemapNode => {
    const metricValue = Math.max(asNumber(row[yKey]), 0);
    const name = String((nameKey ? row[nameKey] : row[xKey]) ?? `item-${index + 1}`);
    return {
      id: `${groupName ?? "root"}::${name}::${index}`,
      name,
      value: [metricValue, total > 0 ? (metricValue / total) * 100 : 0, 1],
      metricValue,
      shareOfTotal: total > 0 ? (metricValue / total) * 100 : 0,
      shareOfParent: parentTotal > 0 ? (metricValue / parentTotal) * 100 : 0,
      itemCount: 1,
      groupName,
      metricLabel: yKey,
      rawFields: rowFields(row, new Set([xKey, yKey, ...(nameKey ? [nameKey] : [])])),
    };
  };

  let data: TreemapNode[];
  if (groups.size <= 1 && !nameKey) {
    const groupRows = Array.from(groups.values())[0] ?? [];
    const parentTotal = groupRows.reduce((sum, item) => sum + item.value, 0) || total;
    data = groupRows
      .slice()
      .sort((a, b) => b.value - a.value)
      .map(({ row, index }) => buildLeaf(row, index, undefined, parentTotal));
  } else {
    data = Array.from(groups.entries())
      .map(([groupName, groupRows]) => {
        const groupTotal = groupRows.reduce((sum, item) => sum + item.value, 0);
        const children = groupRows
          .slice()
          .sort((a, b) => b.value - a.value)
          .map(({ row, index }) => buildLeaf(row, index, groupName, groupTotal));
        return {
          id: `group::${groupName}`,
          name: groupName,
          value: [groupTotal, total > 0 ? (groupTotal / total) * 100 : 0, children.length] as [number, number, number],
          metricValue: groupTotal,
          shareOfTotal: total > 0 ? (groupTotal / total) * 100 : 0,
          shareOfParent: total > 0 ? (groupTotal / total) * 100 : 0,
          itemCount: children.length,
          metricLabel: yKey,
          children,
        };
      })
      .sort((a, b) => b.metricValue - a.metricValue);
  }

  return richTreemapBaseOption(title, data);
}

export function enhanceRichTreemapOption(option: Record<string, unknown>, locale = "en-US"): Record<string, unknown> {
  const series = option.series;
  if (!Array.isArray(series)) {
    return option;
  }

  const text = treemapText(locale);
  let changed = option[RICH_TREEMAP_MARKER] === true;
  const nextSeries = series.map((item) => {
    if (!isRecord(item) || item.type !== "treemap" || item[RICH_TREEMAP_MARKER] !== true) {
      return item;
    }
    changed = true;
    const label = isRecord(item.label) ? item.label : {};
    const tooltip = isRecord(item.tooltip) ? item.tooltip : {};
    return {
      ...item,
      label: { ...label, formatter: (params: TreemapFormatterParams) => richTreemapLabelFormatter(params, text) },
      tooltip: { ...tooltip, formatter: (params: TreemapFormatterParams) => richTreemapTooltipFormatter(params, text) },
    };
  });

  if (!changed) {
    return option;
  }

  const tooltip = isRecord(option.tooltip) ? option.tooltip : {};
  return {
    ...option,
    tooltip: {
      ...tooltip,
      trigger: "item",
      confine: true,
      formatter: (params: TreemapFormatterParams) => richTreemapTooltipFormatter(params, text),
    },
    series: nextSeries,
  };
}

function richTreemapBaseOption(title: string, data: TreemapNode[]): Record<string, unknown> {
  return {
    [RICH_TREEMAP_MARKER]: true,
    title: { text: title, left: "center", top: 4, textStyle: { fontSize: 14, fontWeight: 600 } },
    tooltip: { trigger: "item", confine: true },
    series: [
      {
        [RICH_TREEMAP_MARKER]: true,
        name: title,
        type: "treemap",
        top: 44,
        left: 4,
        right: 4,
        bottom: 8,
        data,
        visualDimension: 0,
        colorMappingBy: "id",
        visibleMin: 24,
        nodeClick: "zoomToNode",
        roam: false,
        label: {
          show: true,
          position: "insideTopLeft",
          minMargin: 4,
          overflow: "truncate",
          rich: {
            name: { fontSize: 12, fontWeight: 600, lineHeight: 18, color: "#ffffff" },
            metric: { fontSize: 18, fontWeight: 700, lineHeight: 24, color: "#fff7cc" },
            share: { fontSize: 12, lineHeight: 18, color: "#ffffff" },
            count: { fontSize: 11, lineHeight: 16, color: "rgba(255,255,255,0.86)" },
            label: {
              fontSize: 9,
              lineHeight: 16,
              color: "#ffffff",
              backgroundColor: "rgba(0,0,0,0.28)",
              borderRadius: 2,
              padding: [1, 4],
            },
            hr: {
              width: "100%",
              borderColor: "rgba(255,255,255,0.22)",
              borderWidth: 0.5,
              height: 0,
              lineHeight: 8,
            },
          },
        },
        upperLabel: {
          show: true,
          height: 26,
          color: "#ffffff",
          fontSize: 12,
          fontWeight: 600,
          backgroundColor: "rgba(0,0,0,0.22)",
        },
        itemStyle: { borderColor: "#101010", borderWidth: 1 },
        breadcrumb: {
          show: true,
          bottom: 0,
          height: 20,
          itemStyle: { color: "rgba(255,255,255,0.92)", borderColor: "rgba(0,0,0,0.12)" },
          emphasis: { itemStyle: { color: "#fff7cc" } },
        },
        color: ["#3f6f76", "#b85f48", "#7d6aa8", "#8a9b4f", "#d08a3f", "#4f7fb8", "#a85d73", "#5f8f67"],
        levels: [
          { itemStyle: { borderColor: "#111111", borderWidth: 3, gapWidth: 3 } },
          {
            colorSaturation: [0.35, 0.72],
            upperLabel: { show: true },
            itemStyle: { borderColor: "#f7f4ef", borderWidth: 2, gapWidth: 2 },
          },
          {
            colorSaturation: [0.45, 0.9],
            itemStyle: { borderColor: "rgba(255,255,255,0.72)", borderWidth: 1, gapWidth: 1 },
          },
        ],
      },
    ],
  };
}

function richTreemapLabelFormatter(params: TreemapFormatterParams, text: TreemapText): string {
  const data = isRecord(params.data) ? params.data : {};
  const name = richTextSafe(String(params.name ?? data.name ?? ""));
  const value = typeof data.metricValue === "number" ? data.metricValue : firstNumericValue(params.value);
  const share = typeof data.shareOfTotal === "number" ? data.shareOfTotal : null;
  const count = typeof data.itemCount === "number" ? data.itemCount : null;
  const metricLabel = richTextSafe(String(data.metricLabel ?? "value"));
  const lines = [`{name|${name}}`, "{hr|}", `{metric|${formatCompactNumber(value)}} {label|${metricLabel}}`];
  if (share !== null) {
    lines.push(`{share|${formatPercent(share)}} {label|${text.ofTotal}}`);
  }
  if (count !== null && count > 1) {
    lines.push(`{count|${count} ${text.items}}`);
  }
  return lines.join("\n");
}

function richTreemapTooltipFormatter(params: TreemapFormatterParams, text: TreemapText): string {
  const data = isRecord(params.data) ? params.data : {};
  const metricValue = typeof data.metricValue === "number" ? data.metricValue : firstNumericValue(params.value);
  const metricLabel = escapeHtml(String(data.metricLabel ?? "value"));
  const shareOfTotal = typeof data.shareOfTotal === "number" ? data.shareOfTotal : null;
  const shareOfParent = typeof data.shareOfParent === "number" ? data.shareOfParent : null;
  const itemCount = typeof data.itemCount === "number" ? data.itemCount : null;
  const path = Array.isArray(params.treePathInfo) && params.treePathInfo.length
    ? params.treePathInfo.map((item) => item.name).filter(Boolean).join(" / ")
    : String(params.name ?? "");
  const color = typeof params.color === "string" ? params.color : "#6b7280";
  const fields = Array.isArray(data.rawFields) ? data.rawFields.filter(isRecord).slice(0, 6) : [];

  const fieldRows = fields.map((field) => {
    const name = escapeHtml(String(field.name ?? ""));
    const value = escapeHtml(String(field.value ?? ""));
    return `<div style="display:flex;gap:12px;justify-content:space-between;"><span style="color:#8a8580;">${name}</span><span style="font-weight:500;color:#2f2d2a;">${value}</span></div>`;
  }).join("");

  return [
    `<div style="min-width:220px;max-width:320px;">`,
    `<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;font-weight:700;color:#211f1c;"><span style="width:9px;height:9px;border-radius:50%;background:${escapeHtml(color)};display:inline-block;"></span>${escapeHtml(path)}</div>`,
    `<div style="display:grid;grid-template-columns:1fr auto;gap:4px 14px;font-size:12px;line-height:1.55;">`,
    `<span style="color:#8a8580;">${metricLabel}</span><strong>${escapeHtml(formatFullNumber(metricValue))}</strong>`,
    shareOfTotal === null ? "" : `<span style="color:#8a8580;">${escapeHtml(text.shareOfTotal)}</span><strong>${escapeHtml(formatPercent(shareOfTotal))}</strong>`,
    shareOfParent === null ? "" : `<span style="color:#8a8580;">${escapeHtml(text.shareOfParent)}</span><strong>${escapeHtml(formatPercent(shareOfParent))}</strong>`,
    itemCount === null || itemCount <= 1 ? "" : `<span style="color:#8a8580;">${escapeHtml(text.items)}</span><strong>${itemCount}</strong>`,
    `</div>`,
    fieldRows ? `<div style="margin-top:8px;padding-top:8px;border-top:1px solid rgba(0,0,0,0.08);font-size:12px;line-height:1.55;">${fieldRows}</div>` : "",
    `</div>`,
  ].join("");
}

function treemapText(locale: string): TreemapText {
  if (locale === "zh-CN") {
    return {
      ofTotal: "整体",
      shareOfTotal: "整体占比",
      shareOfParent: "父级占比",
      items: "项",
    };
  }
  return {
    ofTotal: "of total",
    shareOfTotal: "Share of total",
    shareOfParent: "Share of parent",
    items: "items",
  };
}

function rowFields(row: Record<string, unknown>, skipped: Set<string>): TreeField[] {
  const fields: TreeField[] = [];
  for (const [key, value] of Object.entries(row)) {
    if (skipped.has(key) || value == null) {
      continue;
    }
    fields.push({ name: key, value: String(value) });
    if (fields.length >= 6) {
      break;
    }
  }
  return fields;
}

function asNumber(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

function firstNumericValue(value: unknown): number {
  if (Array.isArray(value)) {
    return asNumber(value[0]);
  }
  return asNumber(value);
}

function formatCompactNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function formatFullNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
}

function formatPercent(value: number): string {
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value)}%`;
}

function richTextSafe(value: string): string {
  return value.replace(/[{}]/g, "").slice(0, 80);
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
