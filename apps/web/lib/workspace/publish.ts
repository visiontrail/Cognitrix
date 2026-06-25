import { getAuthorizationHeader } from "@/lib/auth/session";
import { API_BASE_URL } from "@/lib/api-base";
import { extractChartRows } from "@/lib/workspace/chart-rows";
import type { ChartNodeData, WebDesignLayout, WorkspaceNode } from "@/types/workspace";

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
};

export type PublicationState =
  | (PublicationStatus & { is_active: true })
  | { is_active: false };

export type PublishHistoryItem = {
  page_id: string;
  version: number;
  published_at: string;
  published_by: string;
};

export async function publishWorkspace(
  workspaceId: string,
  layout: WebDesignLayout,
  nodes: WorkspaceNode[]
): Promise<PublicationStatus> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const chartNodes = nodes.filter((node): node is WorkspaceNode & { data: ChartNodeData } =>
    node.data.type === "chart"
  );
  const chartByNodeId = new Map(chartNodes.map((node) => [node.id, node]));
  const pages = layout.pages?.length
    ? layout.pages
    : [{ id: layout.activePageId ?? "section-1", title: "Section 1", grid: layout.grid, zones: layout.zones, textZones: [] }];
  const zones = pages.flatMap((page) => page.zones);
  const chartIds = new Set<string>();
  const charts = zones
    .map((zone) => chartByNodeId.get(zone.nodeId))
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

  const response = await fetch(`${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}/publish`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    body: JSON.stringify({
      layout: {
        grid: layout.grid,
        zones: layout.zones,
        pages: pages.map((page) => ({
          id: page.id,
          title: page.title,
          grid: page.grid,
          zones: page.zones,
          textZones: page.textZones ?? [],
        })),
        activePageId: layout.activePageId,
      },
      sidebar: layout.sidebar,
      charts,
    }),
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
  workspaceId: string
): Promise<PublicationState> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const response = await fetch(
    `${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}/publish`,
    { method: "GET", headers }
  );
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error("Publication status failed");
  return payload as PublicationState;
}

export async function cancelPublication(workspaceId: string): Promise<void> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const response = await fetch(
    `${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}/publish`,
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
