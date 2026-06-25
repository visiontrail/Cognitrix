import { getAuthorizationHeader } from "@/lib/auth/session";
import { API_BASE_URL } from "@/lib/api-base";
import { extractChartRows } from "@/lib/workspace/chart-rows";
import type {
  ChartNodeData,
  WebDesignLayout,
  WorkspaceCanvasFormat,
  WorkspaceEdge,
  WorkspaceNode,
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

  const payload: CanvasPublishSnapshot = {
    canvas_format: canvasFormat,
    viewport,
    nodes,
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
