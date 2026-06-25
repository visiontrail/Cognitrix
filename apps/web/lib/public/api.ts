import { API_BASE_URL } from "@/lib/api-base";

// Public published-page types. These mirror the snapshot manifest written at
// publish time and are fetched by public token without any auth headers.

export type PublishedTextZone = {
  id: string;
  column: number;
  row: number;
  colSpan: number;
  rowSpan: number;
  content: string;
  style: "title" | "subtitle" | "body";
};

export type PublishedZone = {
  id: string;
  nodeId: string;
  chartId?: string;
  chart_id?: string;
  column: number;
  row: number;
  colSpan: number;
  rowSpan: number;
};

export type PublishedPageLayout = {
  id: string;
  title: string;
  grid: { columns: number; rows: { id: string; height: number }[] };
  zones: PublishedZone[];
  textZones?: PublishedTextZone[];
};

export type PublishedChartEntry = {
  chart_id: string;
  title: string;
  chart_type?: string;
  data_truncated?: boolean;
};

export type PublishedSidebarItem = {
  id: string;
  label: string;
  pageId?: string;
  anchorRowId: string;
  children: PublishedSidebarItem[];
};

export type PublishedManifest = {
  layout: {
    grid: { columns: number; rows: { id: string; height: number }[] };
    zones: PublishedZone[];
    pages?: PublishedPageLayout[];
    activePageId?: string;
  };
  sidebar: PublishedSidebarItem[];
  charts: PublishedChartEntry[];
};

export type PublicManifestResponse = {
  version: number;
  published_at: string;
  manifest: PublishedManifest;
};

export type PublicChartData = {
  chart_id: string;
  spec: {
    chartType?: string;
    chart_type?: string;
    title?: string;
    echartsOption?: Record<string, unknown>;
  };
  rows: Record<string, unknown>[];
  data_truncated: boolean;
};

export class PublicPageError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "PublicPageError";
    this.status = status;
  }
}

export async function fetchPublicManifest(token: string): Promise<PublicManifestResponse> {
  const response = await fetch(
    `${API_BASE_URL}/public/pages/${encodeURIComponent(token)}/manifest`,
    { cache: "no-store" }
  );
  if (response.status === 404) {
    throw new PublicPageError("not_found", 404);
  }
  if (!response.ok) {
    throw new PublicPageError("error", response.status);
  }
  return response.json();
}

export async function fetchPublicChartData(
  token: string,
  chartId: string
): Promise<PublicChartData> {
  const response = await fetch(
    `${API_BASE_URL}/public/pages/${encodeURIComponent(token)}/charts/${encodeURIComponent(chartId)}/data`,
    { cache: "no-store" }
  );
  if (response.status === 404) {
    throw new PublicPageError("not_found", 404);
  }
  if (!response.ok) {
    throw new PublicPageError("error", response.status);
  }
  return response.json();
}
