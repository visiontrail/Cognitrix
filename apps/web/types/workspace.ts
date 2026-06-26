import type { Node, Edge } from "@xyflow/react";

export type Workspace = {
  id: string;
  title: string;
  description?: string;
  createdAt: string;
  updatedAt: string;
  nodeCount: number;
  thumbnail?: string;
  role?: string;
};

export type WorkspaceNodeType = "chart" | "text" | "section";

export type ChartNodeData = {
  type: "chart";
  assetId: string;
  title: string;
  chartType: string;
  spec: import("./chart").ChartSpec;
  width: number;
  height: number;
};

export type TextNodeData = {
  type: "text";
  content: string;
  fontSize?: number;
  fontWeight?: "normal" | "bold";
  color?: string;
  width: number;
  height: number;
};

export type SectionNodeData = {
  type: "section";
  title: string;
  width: number;
  height: number;
};

export type StickyNoteColor = "yellow" | "blue" | "green" | "pink";

export type StickyNoteNodeData = {
  type: "stickyNote";
  content: string;
  color: StickyNoteColor;
  width: number;
  height: number;
  rotation?: number;
};

export type DividerNodeData = {
  type: "divider";
  label?: string;
  lineStyle: "solid" | "dashed";
  width: number;
  rotation?: number;
};

export type WorkspaceNodeData = ChartNodeData | TextNodeData | SectionNodeData | StickyNoteNodeData | DividerNodeData;

export type WorkspaceNode = Node<WorkspaceNodeData>;
export type WorkspaceEdge = Edge;

export type WorkspaceCanvasFormatId =
  | "infinite"
  | "web-design"
  | "a4-portrait"
  | "a4-landscape"
  | "a3-portrait"
  | "letter-portrait"
  | "wide-16-9";

export type WorkspaceCanvasFormat = {
  id: WorkspaceCanvasFormatId;
};

export type WorkspaceSnapshot = {
  workspaceId: string;
  /** @deprecated use nodesByFormat instead; kept for backward-compat migration */
  nodes?: WorkspaceNode[];
  /** @deprecated use edgesByFormat instead; kept for backward-compat migration */
  edges?: WorkspaceEdge[];
  nodesByFormat?: Partial<Record<WorkspaceCanvasFormatId, WorkspaceNode[]>>;
  edgesByFormat?: Partial<Record<WorkspaceCanvasFormatId, WorkspaceEdge[]>>;
  /** Per-format page count for paginated fixed canvases (A4/A3/Letter/16:9). */
  canvasPages?: Partial<Record<WorkspaceCanvasFormatId, number>>;
  viewport: { x: number; y: number; zoom: number };
  canvasFormat?: WorkspaceCanvasFormat;
  webDesign?: WebDesignLayout;
};

export type WebDesignGridRow = {
  id: string;
  height: number;
};

export type WebDesignGridConfig = {
  columns: number;
  rows: WebDesignGridRow[];
};

export type WebDesignZone = {
  id: string;
  nodeId: string;
  chartId: string;
  column: number;
  row: number;
  colSpan: number;
  rowSpan: number;
};

export type WebDesignTextStyle = "title" | "subtitle" | "body";

export type WebDesignTextZone = {
  id: string;
  column: number;
  row: number;
  colSpan: number;
  rowSpan: number;
  content: string;
  style: WebDesignTextStyle;
};

export type WebDesignSidebarItem = {
  id: string;
  label: string;
  pageId?: string;
  anchorRowId: string;
  children: WebDesignSidebarItem[];
};

export type WebDesignPage = {
  id: string;
  title: string;
  grid: WebDesignGridConfig;
  zones: WebDesignZone[];
  textZones?: WebDesignTextZone[];
};

export type WebDesignLayout = {
  grid: WebDesignGridConfig;
  zones: WebDesignZone[];
  sidebar: WebDesignSidebarItem[];
  pages?: WebDesignPage[];
  activePageId?: string;
  preview: boolean;
};

export type TableCatalogBusinessType = "roster" | "project_progress" | "attendance" | "other";
export type TableCatalogWriteMode =
  | "update_existing"
  | "time_partitioned_new_table"
  | "new_table"
  | "append_only";
export type TableCatalogTimeGrain = "none" | "month" | "quarter" | "year";

export type TableCatalogEntry = {
  id: string;
  workspaceId: string;
  tableName: string;
  humanLabel: string;
  businessType: TableCatalogBusinessType;
  writeMode: TableCatalogWriteMode;
  timeGrain: TableCatalogTimeGrain;
  isActiveTarget: boolean;
  primaryKeys: string[];
  matchColumns: string[];
  description?: string;
  createdAt: string;
  updatedAt: string;
};

export type TableCatalogDataColumn = {
  name: string;
  type: string;
  nullable: boolean;
  primaryKey: boolean;
  label?: string;
  originalName?: string;
  description?: string;
};

export type TableCatalogDataPreview = {
  entry: TableCatalogEntry;
  table: string;
  rowCount: number;
  limit: number;
  offset: number;
  hasMore: boolean;
  columns: TableCatalogDataColumn[];
  rows: Record<string, unknown>[];
};

export type SavedReportPage = {
  id: string;
  workspaceId: string;
  title: string;
  description?: string;
  snapshot: WorkspaceSnapshot;
  createdAt: string;
  updatedAt: string;
  createdBy: string;
  isPublished: boolean;
  shareUrl?: string;
};
