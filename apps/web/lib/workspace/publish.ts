import { getAuthorizationHeader } from "@/lib/auth/session";
import { API_BASE_URL } from "@/lib/api-base";
import { extractChartRows } from "@/lib/workspace/chart-rows";
import { normalizeCanvasFormat } from "@/lib/workspace/canvas-formats";
import { isRecord } from "@/lib/utils";
import type { PublishedCanvasNode, PublishedManifest } from "@/lib/public/api";
import type { ChartSpec } from "@/types/chart";
import type {
  ChartNodeData,
  WebDesignLayout,
  WorkspaceCanvasFormat,
  WorkspaceCanvasFormatId,
  WorkspaceEdge,
  WorkspaceNode,
  WorkspaceSnapshot,
} from "@/types/workspace";

const configuredClearance = Number(process.env.NEXT_PUBLIC_DEFAULT_CLEARANCE ?? 1);
const DEFAULT_CLEARANCE = Number.isFinite(configuredClearance)
  ? Math.max(0, Math.trunc(configuredClearance))
  : 1;
const DEFAULT_AUTH_CONTEXT = {
  userId: process.env.NEXT_PUBLIC_DEFAULT_USER_ID ?? "demo-user",
  projectId: process.env.NEXT_PUBLIC_DEFAULT_PROJECT_ID ?? "demo-project",
  role: process.env.NEXT_PUBLIC_DEFAULT_ROLE ?? "hr",
  department: process.env.NEXT_PUBLIC_DEFAULT_DEPARTMENT ?? "HR",
  clearance: DEFAULT_CLEARANCE,
};

export type PublicationStatus = {
  token: string;
  public_url: string;
  published_page_id: string;
  version: number;
  published_at: string;
  is_active: boolean;
  canvas_format_id?: string;
  canvas_kind?: "free_layout" | "fixed_size" | "web_page";
};

export type PublicationState =
  | (PublicationStatus & { is_active: true })
  | { is_active: false };

/**
 * Resolve a browser-openable public URL for a published page.
 *
 * The backend-computed `public_url` is derived from the API request's base URL,
 * which resolves to the internal proxy target (e.g. `http://api:8000`) when the
 * browser talks to the API through the Next.js `/api/backend` proxy. The public
 * page (`/p/{token}`) is served by this Next.js app, so the only reliably
 * correct host is the browser's own origin. Fall back to the server value when
 * running outside the browser (SSR).
 */
export function resolvePublicUrl(status: { token: string; public_url?: string }): string {
  if (typeof window !== "undefined" && window.location?.origin) {
    return `${window.location.origin}/p/${status.token}`;
  }
  return status.public_url ?? "";
}

export type PublishHistoryItem = {
  page_id: string;
  version: number;
  published_at: string;
  published_by: string;
  canvas_format_id?: string;
  canvas_kind?: "free_layout" | "fixed_size" | "web_page";
};

export type PublishedVersionChartData = {
  page_id?: string;
  chart_id: string;
  spec: Record<string, unknown>;
  rows: Record<string, unknown>[];
  data_truncated?: boolean;
};

export type PublishedVersionSnapshot = {
  page_id: string;
  version: number;
  published_at: string;
  published_by: string;
  canvas_format_id?: string;
  canvas_kind?: "free_layout" | "fixed_size" | "web_page";
  manifest: PublishedManifest;
  charts: PublishedVersionChartData[];
};

export type CanvasPublishSnapshot = {
  canvas_format: WorkspaceCanvasFormat;
  viewport: { x: number; y: number; zoom: number };
  nodes: WorkspaceNode[];
  edges: WorkspaceEdge[];
  web_design?: {
    layout: {
      grid: WebDesignLayout["grid"];
      zones: WebDesignLayout["zones"];
      pages: NonNullable<WebDesignLayout["pages"]>;
      activePageId?: string;
    };
    sidebar: WebDesignLayout["sidebar"];
  };
  charts: {
    chart_id: string;
    title: string;
    chart_type: string;
    spec: ChartNodeData["spec"];
    rows: Record<string, unknown>[];
  }[];
};

export function buildActiveCanvasPublishPayload({
  canvasFormat,
  viewport,
  nodes,
  edges,
  webDesign,
}: {
  canvasFormat: WorkspaceCanvasFormat;
  viewport: { x: number; y: number; zoom: number };
  nodes: WorkspaceNode[];
  edges: WorkspaceEdge[];
  webDesign: WebDesignLayout;
}): CanvasPublishSnapshot {
  const chartNodes = nodes.filter((node): node is WorkspaceNode & { data: ChartNodeData } =>
    node.data.type === "chart"
  );
  const chartByNodeId = new Map(chartNodes.map((node) => [node.id, node]));
  const pages = webDesign.pages?.length
    ? webDesign.pages
    : [{ id: webDesign.activePageId ?? "section-1", title: "Section 1", grid: webDesign.grid, zones: webDesign.zones, textZones: [] }];
  const zones = canvasFormat.id === "web-design"
    ? pages.flatMap((page) => page.zones)
    : [];
  const chartIds = new Set<string>();
  const chartsFromWebZones = zones
    .map((zone) => chartByNodeId.get(zone.nodeId));
  const chartsFromNodes = canvasFormat.id === "web-design" ? [] : chartNodes;
  const charts = [...chartsFromWebZones, ...chartsFromNodes]
    .filter((node): node is WorkspaceNode & { data: ChartNodeData } => Boolean(node))
    .filter((node) => {
      if (chartIds.has(node.data.assetId)) return false;
      chartIds.add(node.data.assetId);
      return true;
    })
    .map((node) => ({
      chart_id: node.data.assetId,
      title: node.data.title,
      chart_type: node.data.chartType,
      spec: node.data.spec,
      rows: extractChartRows(node.data),
    }));
  const publishNodes = canvasFormat.id === "web-design" ? nodes : flattenGroupedCanvasNodes(nodes);

  const payload: CanvasPublishSnapshot = {
    canvas_format: canvasFormat,
    viewport,
    nodes: publishNodes,
    edges,
    charts,
  };

  if (canvasFormat.id === "web-design") {
    payload.web_design = {
      layout: {
        grid: webDesign.grid,
        zones: webDesign.zones,
        pages: pages.map((page) => ({
          id: page.id,
          title: page.title,
          grid: page.grid,
          zones: page.zones,
          textZones: page.textZones ?? [],
        })),
        activePageId: webDesign.activePageId,
      },
      sidebar: webDesign.sidebar,
    };
  }

  return payload;
}

function flattenGroupedCanvasNodes(nodes: WorkspaceNode[]): WorkspaceNode[] {
  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  return nodes.map((node) => ({
    ...node,
    parentId: undefined,
    extent: undefined,
    expandParent: undefined,
    position: roundPosition(getAbsoluteNodePosition(node, nodeMap)),
  }));
}

function getAbsoluteNodePosition(
  node: WorkspaceNode,
  nodeMap: Map<string, WorkspaceNode>,
  visited = new Set<string>()
): { x: number; y: number } {
  if (!node.parentId || visited.has(node.id)) return node.position;
  const parent = nodeMap.get(node.parentId);
  if (!parent) return node.position;
  visited.add(node.id);
  const parentPosition = getAbsoluteNodePosition(parent, nodeMap, visited);
  return {
    x: parentPosition.x + node.position.x,
    y: parentPosition.y + node.position.y,
  };
}

function roundPosition(position: { x: number; y: number }): { x: number; y: number } {
  return {
    x: Math.round(position.x),
    y: Math.round(position.y),
  };
}

export async function publishWorkspace(
  workspaceId: string,
  snapshot: CanvasPublishSnapshot
): Promise<PublicationStatus> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const response = await fetch(`${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}/publish`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    body: JSON.stringify(snapshot),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof payload === "object" && payload && "detail" in payload
      ? (payload.detail as { message?: string })
      : null;
    throw new Error(detail?.message || "Publish failed");
  }
  return payload as PublicationStatus;
}

export async function fetchPublicationStatus(
  workspaceId: string,
  canvasFormatId?: string
): Promise<PublicationState> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const query = canvasFormatId
    ? `?canvas_format_id=${encodeURIComponent(canvasFormatId)}`
    : "";
  const response = await fetch(
    `${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}/publish${query}`,
    { method: "GET", headers }
  );
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error("Publication status failed");
  return payload as PublicationState;
}

export async function cancelPublication(
  workspaceId: string,
  canvasFormatId?: string
): Promise<void> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const query = canvasFormatId
    ? `?canvas_format_id=${encodeURIComponent(canvasFormatId)}`
    : "";
  const response = await fetch(
    `${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}/publish${query}`,
    { method: "DELETE", headers }
  );
  if (!response.ok) throw new Error("Cancel publication failed");
}

export async function fetchPublishHistory(workspaceId: string): Promise<PublishHistoryItem[]> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const response = await fetch(`${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}/published`, {
    method: "GET",
    headers,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error("Publish history failed");
  }
  const data = payload as { published_pages?: PublishHistoryItem[] };
  return Array.isArray(data.published_pages) ? data.published_pages : [];
}

export async function fetchPublishedVersionSnapshot(
  workspaceId: string,
  pageId: string
): Promise<PublishedVersionSnapshot> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const response = await fetch(
    `${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}/published/${encodeURIComponent(pageId)}/snapshot`,
    { method: "GET", headers }
  );
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error("Published version snapshot failed");
  }
  return payload as PublishedVersionSnapshot;
}

export function buildWorkspaceSnapshotFromPublishedVersion({
  workspaceId,
  published,
  baseSnapshot,
}: {
  workspaceId: string;
  published: PublishedVersionSnapshot;
  baseSnapshot?: WorkspaceSnapshot | null;
}): WorkspaceSnapshot {
  const manifest = published.manifest;
  const canvasFormat = normalizeCanvasFormat({
    id: manifest.canvas?.format_id ?? published.canvas_format_id,
  });
  const chartById = new Map(published.charts.map((chart) => [chart.chart_id, chart]));
  const restoredNodes = restorePublishedNodes(manifest.content?.nodes ?? [], chartById);
  const restoredEdges = Array.isArray(manifest.content?.edges)
    ? (manifest.content.edges as WorkspaceEdge[])
    : [];
  const nodesByFormat: Partial<Record<WorkspaceCanvasFormatId, WorkspaceNode[]>> = {
    ...(baseSnapshot?.nodesByFormat ?? {}),
    [canvasFormat.id]: restoredNodes,
  };
  const edgesByFormat: Partial<Record<WorkspaceCanvasFormatId, WorkspaceEdge[]>> = {
    ...(baseSnapshot?.edgesByFormat ?? {}),
    [canvasFormat.id]: restoredEdges,
  };

  return {
    workspaceId,
    nodes: restoredNodes,
    edges: restoredEdges,
    nodesByFormat,
    edgesByFormat,
    viewport: normalizeViewport(manifest.canvas?.viewport),
    canvasFormat,
    webDesign:
      canvasFormat.id === "web-design"
        ? restorePublishedWebDesign(manifest)
        : baseSnapshot?.webDesign,
  };
}

function restorePublishedNodes(
  nodes: PublishedCanvasNode[],
  chartById: Map<string, PublishedVersionChartData>
): WorkspaceNode[] {
  return nodes.map((node) => restorePublishedNode(node, chartById));
}

function restorePublishedNode(
  node: PublishedCanvasNode,
  chartById: Map<string, PublishedVersionChartData>
): WorkspaceNode {
  const nodeType = node.data.type;
  const width = positiveNumber(node.width ?? node.data.width, defaultNodeWidth(nodeType));
  const height = positiveNumber(
    node.height ?? ("height" in node.data ? node.data.height : undefined),
    defaultNodeHeight(nodeType)
  );

  return {
    id: node.id,
    type: node.type || nodeTypeToReactFlowType(nodeType),
    position: normalizePosition(node.position),
    width,
    height,
    initialWidth: width,
    initialHeight: height,
    hidden: Boolean(node.hidden),
    zIndex: typeof node.zIndex === "number" ? node.zIndex : undefined,
    data: restorePublishedNodeData(node, width, height, chartById),
  } as WorkspaceNode;
}

function restorePublishedNodeData(
  node: PublishedCanvasNode,
  width: number,
  height: number,
  chartById: Map<string, PublishedVersionChartData>
): WorkspaceNode["data"] {
  const data = node.data;
  if (data.type === "chart") {
    const assetId = asString(data.assetId) || node.id;
    const chart = chartById.get(assetId);
    const chartType =
      asString(data.chartType) ||
      asString(chart?.spec?.chartType) ||
      asString(chart?.spec?.chart_type) ||
      "bar";
    const title = asString(data.title) || asString(chart?.spec?.title) || assetId;
    return {
      type: "chart",
      assetId,
      title,
      chartType,
      spec: normalizeRestoredChartSpec(chart, { chartId: assetId, title, chartType }),
      width,
      height,
    };
  }

  if (data.type === "text") {
    return {
      type: "text",
      content: asString(data.content),
      fontSize: optionalNumber(data.fontSize),
      fontWeight: data.fontWeight === "bold" ? "bold" : data.fontWeight === "normal" ? "normal" : undefined,
      color: asString(data.color) || undefined,
      width,
      height,
    };
  }

  if (data.type === "stickyNote") {
    return {
      type: "stickyNote",
      content: asString(data.content),
      color: ["yellow", "blue", "green", "pink"].includes(asString(data.color))
        ? (data.color as "yellow" | "blue" | "green" | "pink")
        : "yellow",
      width,
      height,
      rotation: optionalNumber(data.rotation),
    };
  }

  if (data.type === "divider") {
    return {
      type: "divider",
      label: asString(data.label) || undefined,
      lineStyle: data.lineStyle === "dashed" ? "dashed" : "solid",
      width,
      rotation: optionalNumber(data.rotation),
    };
  }

  return {
    type: "section",
    title: asString(data.title) || "Section",
    width,
    height,
  };
}

function normalizeRestoredChartSpec(
  chart: PublishedVersionChartData | undefined,
  fallback: { chartId: string; title: string; chartType: string }
): ChartSpec {
  const rawSpec = isRecord(chart?.spec) ? chart.spec : {};
  const echartsOption = isRecord(rawSpec.echartsOption) ? rawSpec.echartsOption : {};
  const rows = Array.isArray(chart?.rows) ? chart.rows.filter(isRecord) : [];
  return {
    ...rawSpec,
    chartType: (asString(rawSpec.chartType) || asString(rawSpec.chart_type) || fallback.chartType) as ChartSpec["chartType"],
    title: asString(rawSpec.title) || fallback.title || fallback.chartId,
    echartsOption: {
      ...echartsOption,
      __rows__: rows,
    },
  };
}

function restorePublishedWebDesign(manifest: PublishedManifest): WebDesignLayout {
  const webDesign = manifest.content?.web_design;
  const layout = webDesign?.layout ?? manifest.layout;
  return {
    grid: layout?.grid ?? {
      columns: 3,
      rows: [
        { id: "row-1", height: 400 },
        { id: "row-2", height: 400 },
      ],
    },
    zones: (layout?.zones ?? []) as WebDesignLayout["zones"],
    sidebar: (webDesign?.sidebar ?? manifest.sidebar ?? []) as WebDesignLayout["sidebar"],
    pages: layout?.pages as WebDesignLayout["pages"] | undefined,
    activePageId: layout?.activePageId,
    preview: false,
  };
}

function normalizeViewport(value: unknown): { x: number; y: number; zoom: number } {
  if (!isRecord(value)) {
    return { x: 0, y: 0, zoom: 1 };
  }
  return {
    x: finiteNumber(value.x, 0),
    y: finiteNumber(value.y, 0),
    zoom: positiveNumber(value.zoom, 1),
  };
}

function normalizePosition(value: unknown): { x: number; y: number } {
  if (!isRecord(value)) {
    return { x: 0, y: 0 };
  }
  return {
    x: finiteNumber(value.x, 0),
    y: finiteNumber(value.y, 0),
  };
}

function nodeTypeToReactFlowType(type: PublishedCanvasNode["data"]["type"]): string {
  if (type === "chart") return "chartNode";
  if (type === "text") return "textNode";
  if (type === "stickyNote") return "stickyNoteNode";
  if (type === "divider") return "dividerNode";
  return "sectionNode";
}

function defaultNodeWidth(type: PublishedCanvasNode["data"]["type"]): number {
  if (type === "chart") return 520;
  if (type === "text") return 480;
  if (type === "stickyNote") return 240;
  if (type === "divider") return 480;
  return 640;
}

function defaultNodeHeight(type: PublishedCanvasNode["data"]["type"]): number {
  if (type === "chart") return 380;
  if (type === "text") return 220;
  if (type === "stickyNote") return 200;
  if (type === "divider") return 24;
  return 320;
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function optionalNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function finiteNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function positiveNumber(value: unknown, fallback: number): number {
  const numeric = finiteNumber(value, fallback);
  return numeric > 0 ? numeric : fallback;
}
