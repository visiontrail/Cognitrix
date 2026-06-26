import { create } from "zustand";
import {
  DEFAULT_CANVAS_FORMAT,
  normalizeCanvasFormat,
} from "@/lib/workspace/canvas-formats";
import {
  WORKSPACE_SELECTION_STORAGE_KEY,
  WORKSPACE_SNAPSHOT_STORAGE_KEY,
  safeLoadFromStorage,
  safeSaveToStorage,
} from "@/lib/chat/session-storage";
import type {
  Workspace,
  WorkspaceNode,
  WorkspaceEdge,
  WorkspaceSnapshot,
  WorkspaceCanvasFormat,
  WorkspaceCanvasFormatId,
  WebDesignLayout,
  WebDesignPage,
  WebDesignSidebarItem,
  WebDesignTextZone,
  WebDesignTextStyle,
} from "@/types/workspace";

const DEFAULT_WEB_DESIGN_LAYOUT: WebDesignLayout = {
  grid: {
    columns: 3,
    rows: [
      { id: "row-1", height: 400 },
      { id: "row-2", height: 400 },
    ],
  },
  zones: [],
  sidebar: [{ id: "section-1", label: "Section 1", pageId: "section-1", anchorRowId: "row-1", children: [] }],
  pages: [
    {
      id: "section-1",
      title: "Section 1",
      grid: {
        columns: 3,
        rows: [
          { id: "row-1", height: 400 },
          { id: "row-2", height: 400 },
        ],
      },
      zones: [],
    },
  ],
  activePageId: "section-1",
  preview: false,
};

type PersistedWorkspaceSelection = {
  version: 1;
  activeWorkspaceId: string | null;
};

type WorkspaceState = {
  workspaces: Workspace[];
  activeWorkspaceId: string | null;
  nodes: WorkspaceNode[];
  edges: WorkspaceEdge[];
  nodesByFormat: Partial<Record<WorkspaceCanvasFormatId, WorkspaceNode[]>>;
  edgesByFormat: Partial<Record<WorkspaceCanvasFormatId, WorkspaceEdge[]>>;
  viewport: { x: number; y: number; zoom: number };
  canvasFormat: WorkspaceCanvasFormat;
  webDesign: WebDesignLayout;
  hasUnsavedChanges: boolean;

  setWorkspaces: (workspaces: Workspace[]) => void;
  addWorkspace: (workspace: Workspace) => void;
  updateWorkspaceTitle: (workspaceId: string, title: string) => void;
  removeWorkspace: (workspaceId: string) => void;
  setActiveWorkspace: (workspaceId: string | null) => void;
  setNodes: (nodes: WorkspaceNode[]) => void;
  setEdges: (edges: WorkspaceEdge[]) => void;
  addNode: (node: WorkspaceNode) => void;
  addNodeToWebDesign: (node: WorkspaceNode) => void;
  updateNode: (nodeId: string, data: Partial<WorkspaceNode>) => void;
  removeNode: (nodeId: string) => void;
  removeNodes: (nodeIds: string[]) => void;
  groupNodes: (nodeIds: string[], title?: string) => string | null;
  ungroupNodes: (nodeIds: string[]) => void;
  setViewport: (viewport: { x: number; y: number; zoom: number }) => void;
  setCanvasFormat: (canvasFormat: WorkspaceCanvasFormat) => void;
  setWebDesignColumns: (columns: number) => void;
  addWebDesignRow: () => void;
  removeWebDesignRow: (rowId: string) => void;
  setWebDesignRowHeight: (rowId: string, height: number) => void;
  placeWebDesignZone: (nodeId: string, column: number, row: number) => void;
  moveWebDesignZone: (zoneId: string, column: number, row: number) => void;
  resizeWebDesignZone: (zoneId: string, colSpan: number, rowSpan: number) => void;
  removeWebDesignZone: (zoneId: string) => void;
  addWebDesignTextZone: (style: WebDesignTextStyle) => void;
  updateWebDesignTextZone: (zoneId: string, updates: Partial<Omit<WebDesignTextZone, "id">>) => void;
  removeWebDesignTextZone: (zoneId: string) => void;
  setWebDesignPreview: (preview: boolean) => void;
  setActiveWebDesignPage: (pageId: string) => void;
  addWebDesignSidebarItem: (parentId?: string, labels?: { sectionLabel: string; childLabel: string }) => void;
  updateWebDesignSidebarItem: (itemId: string, updates: Partial<Omit<WebDesignSidebarItem, "id" | "children">>) => void;
  removeWebDesignSidebarItem: (itemId: string) => void;
  loadSnapshot: (snapshot: WorkspaceSnapshot) => void;
  getSnapshot: () => WorkspaceSnapshot | null;
  setHasUnsavedChanges: (value: boolean) => void;
};

function loadPersistedWorkspaceSelection(): PersistedWorkspaceSelection | null {
  const state = safeLoadFromStorage<Partial<PersistedWorkspaceSelection>>(WORKSPACE_SELECTION_STORAGE_KEY);
  if (!state || state.version !== 1) {
    return null;
  }

  return {
    version: 1,
    activeWorkspaceId: typeof state.activeWorkspaceId === "string" ? state.activeWorkspaceId : null,
  };
}

function persistWorkspaceSelection(activeWorkspaceId: string | null): void {
  safeSaveToStorage<PersistedWorkspaceSelection>(WORKSPACE_SELECTION_STORAGE_KEY, {
    version: 1,
    activeWorkspaceId,
  });
}

const persistedWorkspaceSelection = loadPersistedWorkspaceSelection();

export const useWorkspaceStore = create<WorkspaceState>((set, get) => ({
  workspaces: [],
  activeWorkspaceId: persistedWorkspaceSelection?.activeWorkspaceId ?? null,
  nodes: [],
  edges: [],
  nodesByFormat: {},
  edgesByFormat: {},
  viewport: { x: 0, y: 0, zoom: 1 },
  canvasFormat: DEFAULT_CANVAS_FORMAT,
  webDesign: DEFAULT_WEB_DESIGN_LAYOUT,
  hasUnsavedChanges: false,

  setWorkspaces: (workspaces) =>
    set((state) => {
      const workspaceIds = new Set(workspaces.map((workspace) => workspace.id));
      const activeWorkspaceId =
        state.activeWorkspaceId && workspaceIds.has(state.activeWorkspaceId)
          ? state.activeWorkspaceId
          : null;
      persistWorkspaceSelection(activeWorkspaceId);
      return { workspaces, activeWorkspaceId };
    }),

  addWorkspace: (workspace) =>
    set((state) => ({
      workspaces: [workspace, ...state.workspaces],
    })),

  updateWorkspaceTitle: (workspaceId, title) =>
    set((state) => ({
      workspaces: state.workspaces.map((workspace) =>
        workspace.id === workspaceId
          ? { ...workspace, title, updatedAt: new Date().toISOString() }
          : workspace
      ),
    })),

  removeWorkspace: (workspaceId) =>
    set((state) => {
      const workspaces = state.workspaces.filter((w) => w.id !== workspaceId);
      const activeWorkspaceId = state.activeWorkspaceId === workspaceId ? null : state.activeWorkspaceId;
      persistWorkspaceSelection(activeWorkspaceId);
      return { workspaces, activeWorkspaceId };
    }),

  setActiveWorkspace: (workspaceId) => {
    const currentState = get();
    // No-op when re-selecting the already-active workspace; avoids wiping canvas state
    // without a subsequent snapshot reload (TanStack Query won't re-run queryFn when the
    // key is unchanged, leaving the store permanently empty).
    if (currentState.activeWorkspaceId === workspaceId) return;

    // Flush unsaved changes to localStorage before clearing state for the new workspace.
    // The auto-save debounce (900ms) may not have fired yet, so we save synchronously here
    // to prevent losing canvas format selection and node placement on workspace switch.
    if (currentState.hasUnsavedChanges && currentState.activeWorkspaceId) {
      const snapshot = currentState.getSnapshot();
      if (snapshot) {
        const persisted = safeLoadFromStorage<{ version: 1; snapshots: Record<string, unknown> }>(
          WORKSPACE_SNAPSHOT_STORAGE_KEY
        );
        safeSaveToStorage(WORKSPACE_SNAPSHOT_STORAGE_KEY, {
          version: 1,
          snapshots: { ...(persisted?.snapshots ?? {}), [snapshot.workspaceId]: snapshot },
        });
      }
    }
    persistWorkspaceSelection(workspaceId);
    set({
      activeWorkspaceId: workspaceId,
      nodes: [],
      edges: [],
      nodesByFormat: {},
      edgesByFormat: {},
      viewport: { x: 0, y: 0, zoom: 1 },
      canvasFormat: DEFAULT_CANVAS_FORMAT,
      webDesign: DEFAULT_WEB_DESIGN_LAYOUT,
      hasUnsavedChanges: false,
    });
  },

  setNodes: (nodes) => set({ nodes, hasUnsavedChanges: true }),

  setEdges: (edges) => set({ edges, hasUnsavedChanges: true }),

  addNode: (node) =>
    set((state) => ({
      nodes: [...state.nodes, node],
      hasUnsavedChanges: true,
    })),

  addNodeToWebDesign: (node) =>
    set((state) => {
      if (node.data.type !== "chart") return {};

      // Persist the current format's nodes before switching away from it
      const nodesByFormat: Partial<Record<WorkspaceCanvasFormatId, WorkspaceNode[]>> = {
        ...state.nodesByFormat,
        [state.canvasFormat.id]: state.nodes,
      };
      const edgesByFormat: Partial<Record<WorkspaceCanvasFormatId, WorkspaceEdge[]>> = {
        ...state.edgesByFormat,
        [state.canvasFormat.id]: state.edges,
      };

      // Add the node exclusively to the web-design format bucket
      const webDesignNodes = [...(nodesByFormat["web-design"] ?? []), node];
      nodesByFormat["web-design"] = webDesignNodes;

      const activePage = getActiveWebDesignPage(state.webDesign);
      const placement = findNextWebDesignCell(activePage);
      const rows =
        placement.row < activePage.grid.rows.length
          ? activePage.grid.rows
          : [...activePage.grid.rows, { id: `row-${activePage.grid.rows.length + 1}`, height: 400 }];
      const nextPage = {
        ...activePage,
        grid: { ...activePage.grid, rows },
        zones: [
          ...activePage.zones,
          {
            id: `zone-${node.id}`,
            nodeId: node.id,
            chartId: node.data.assetId,
            column: placement.column,
            row: placement.row,
            colSpan: 1,
            rowSpan: 1,
          },
        ],
      };

      return {
        nodes: webDesignNodes,
        edges: edgesByFormat["web-design"] ?? [],
        nodesByFormat,
        edgesByFormat,
        canvasFormat: { id: "web-design" },
        webDesign: replaceActiveWebDesignPage(state.webDesign, nextPage, { preview: false }),
        hasUnsavedChanges: true,
      };
    }),

  updateNode: (nodeId, data) =>
    set((state) => ({
      nodes: state.nodes.map((n) =>
        n.id === nodeId ? { ...n, ...data, data: { ...n.data, ...(data.data ?? {}) } } : n
      ),
      hasUnsavedChanges: true,
    })),

  removeNode: (nodeId) =>
    set((state) => ({
      ...removeNodesFromCanvas(state.nodes, state.edges, [nodeId]),
      hasUnsavedChanges: true,
    })),

  removeNodes: (nodeIds) =>
    set((state) => ({
      ...removeNodesFromCanvas(state.nodes, state.edges, nodeIds),
      hasUnsavedChanges: true,
    })),

  groupNodes: (nodeIds, title = "Group") => {
    let groupId: string | null = null;
    set((state) => {
      const selectedIds = new Set(nodeIds);
      const nodeMap = new Map(state.nodes.map((node) => [node.id, node]));
      const groupableNodes = state.nodes.filter(
        (node) => selectedIds.has(node.id) && node.data.type !== "section"
      );
      if (groupableNodes.length < 2) return {};

      const nextGroupId = `section-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
      groupId = nextGroupId;
      const padding = 28;
      const bounds = getNodesAbsoluteBounds(groupableNodes, nodeMap);
      const groupPosition = {
        x: Math.round(bounds.x - padding),
        y: Math.round(bounds.y - padding),
      };
      const groupWidth = Math.round(bounds.width + padding * 2);
      const groupHeight = Math.round(bounds.height + padding * 2);
      const groupNode: WorkspaceNode = {
        id: nextGroupId,
        type: "sectionNode",
        position: groupPosition,
        width: groupWidth,
        height: groupHeight,
        initialWidth: groupWidth,
        initialHeight: groupHeight,
        data: {
          type: "section",
          title,
          width: groupWidth,
          height: groupHeight,
        },
      };

      const groupableIds = new Set(groupableNodes.map((node) => node.id));
      const nextNodes = state.nodes.map((node) => {
        if (!groupableIds.has(node.id)) return { ...node, selected: false };
        const absolutePosition = getAbsoluteNodePosition(node, nodeMap);
        return {
          ...node,
          parentId: nextGroupId,
          extent: "parent" as const,
          expandParent: true,
          position: {
            x: Math.round(absolutePosition.x - groupPosition.x),
            y: Math.round(absolutePosition.y - groupPosition.y),
          },
          selected: false,
        };
      });

      return {
        nodes: [groupNode, ...nextNodes],
        hasUnsavedChanges: true,
      };
    });
    return groupId;
  },

  ungroupNodes: (nodeIds) =>
    set((state) => {
      const selectedIds = new Set(nodeIds);
      const nodeMap = new Map(state.nodes.map((node) => [node.id, node]));
      const groupIds = new Set<string>();

      for (const node of state.nodes) {
        if (!selectedIds.has(node.id)) continue;
        if (node.data.type === "section") {
          groupIds.add(node.id);
        } else if (node.parentId) {
          groupIds.add(node.parentId);
        }
      }

      if (!groupIds.size) return {};

      const descendantIds = collectDescendantNodeIds(state.nodes, groupIds);
      const nextNodes = state.nodes
        .filter((node) => !groupIds.has(node.id))
        .map((node) => {
          if (!descendantIds.has(node.id)) return node;
          return {
            ...node,
            parentId: undefined,
            extent: undefined,
            expandParent: undefined,
            position: roundPosition(getAbsoluteNodePosition(node, nodeMap)),
            selected: selectedIds.has(node.id) || Boolean(node.parentId && groupIds.has(node.parentId)),
          };
        });

      return {
        nodes: nextNodes,
        hasUnsavedChanges: true,
      };
    }),

  setViewport: (viewport) => set({ viewport }),

  setCanvasFormat: (canvasFormat) =>
    set((state) => {
      const nextCanvasFormat = normalizeCanvasFormat(canvasFormat);
      if (state.canvasFormat.id === nextCanvasFormat.id) {
        return {};
      }

      // Persist current format's nodes before switching
      const nodesByFormat: Partial<Record<WorkspaceCanvasFormatId, WorkspaceNode[]>> = {
        ...state.nodesByFormat,
        [state.canvasFormat.id]: state.nodes,
      };
      const edgesByFormat: Partial<Record<WorkspaceCanvasFormatId, WorkspaceEdge[]>> = {
        ...state.edgesByFormat,
        [state.canvasFormat.id]: state.edges,
      };

      return {
        canvasFormat: nextCanvasFormat,
        nodes: nodesByFormat[nextCanvasFormat.id] ?? [],
        edges: edgesByFormat[nextCanvasFormat.id] ?? [],
        nodesByFormat,
        edgesByFormat,
        hasUnsavedChanges: true,
      };
    }),

  setWebDesignColumns: (columns) =>
    set((state) => {
      const nextColumns = clamp(columns, 2, 10);
      return {
        webDesign: updateActiveWebDesignPage(state.webDesign, (page) =>
          clampPageToColumns(
            {
              ...page,
              grid: {
                ...page.grid,
                columns: nextColumns,
              },
            },
            nextColumns
          )
        ),
        hasUnsavedChanges: true,
      };
    }),

  addWebDesignRow: () =>
    set((state) => {
      const activePage = getActiveWebDesignPage(state.webDesign);
      const nextIndex = activePage.grid.rows.length + 1;
      return {
        webDesign: updateActiveWebDesignPage(state.webDesign, (page) => ({
          ...page,
          grid: {
            ...page.grid,
            rows: [...page.grid.rows, { id: `row-${nextIndex}`, height: 400 }],
          },
        })),
        hasUnsavedChanges: true,
      };
    }),

  removeWebDesignRow: (rowId) =>
    set((state) => {
      const activePage = getActiveWebDesignPage(state.webDesign);
      if (activePage.grid.rows.length <= 1) return {};
      const rows = activePage.grid.rows.filter((row) => row.id !== rowId);
      return {
        webDesign: updateActiveWebDesignPage(
          {
            ...state.webDesign,
            sidebar: retargetSidebar(state.webDesign.sidebar, rows[0]?.id ?? "row-1"),
          },
          (page) => ({
            ...page,
            grid: { ...page.grid, rows },
            zones: page.zones.filter((zone) => rows[zone.row]),
          })
        ),
        hasUnsavedChanges: true,
      };
    }),

  setWebDesignRowHeight: (rowId, height) =>
    set((state) => ({
      webDesign: updateActiveWebDesignPage(state.webDesign, (page) => ({
        ...page,
        grid: {
          ...page.grid,
          rows: page.grid.rows.map((row) =>
            row.id === rowId ? { ...row, height: clamp(height, 40, 800) } : row
          ),
        },
      })),
      hasUnsavedChanges: true,
    })),

  placeWebDesignZone: (nodeId, column, row) =>
    set((state) => {
      const activePage = getActiveWebDesignPage(state.webDesign);
      const chartNode = state.nodes.find((node) => node.id === nodeId && node.data.type === "chart");
      if (!chartNode || activePage.zones.some((zone) => zone.nodeId === nodeId)) return {};
      if (chartNode.data.type !== "chart") return {};
      const chartData = chartNode.data;
      const safeColumn = clamp(column, 0, activePage.grid.columns - 1);
      const safeRow = clamp(row, 0, activePage.grid.rows.length - 1);
      if (activePage.zones.some((zone) => zone.column === safeColumn && zone.row === safeRow)) {
        return {};
      }
      return {
        webDesign: updateActiveWebDesignPage(state.webDesign, (page) => ({
          ...page,
          zones: [
            ...page.zones,
            {
              id: `zone-${nodeId}-${Date.now().toString(36)}`,
              nodeId,
              chartId: chartData.assetId,
              column: safeColumn,
              row: safeRow,
              colSpan: 1,
              rowSpan: 1,
            },
          ],
        })),
        hasUnsavedChanges: true,
      };
    }),

  moveWebDesignZone: (zoneId, column, row) =>
    set((state) => {
      const activePage = getActiveWebDesignPage(state.webDesign);
      const zone = activePage.zones.find((item) => item.id === zoneId);
      if (!zone) return {};

      const safeColumn = clamp(column, 0, activePage.grid.columns - zone.colSpan);
      const safeRow = clamp(row, 0, activePage.grid.rows.length - zone.rowSpan);
      if (zone.column === safeColumn && zone.row === safeRow) return {};
      if (zoneOverlaps(activePage.zones, zoneId, safeColumn, safeRow, zone.colSpan, zone.rowSpan)) {
        return {};
      }

      return {
        webDesign: updateActiveWebDesignPage(state.webDesign, (page) => ({
          ...page,
          zones: page.zones.map((item) =>
            item.id === zoneId ? { ...item, column: safeColumn, row: safeRow } : item
          ),
        })),
        hasUnsavedChanges: true,
      };
    }),

  resizeWebDesignZone: (zoneId, colSpan, rowSpan) =>
    set((state) => ({
      webDesign: updateActiveWebDesignPage(state.webDesign, (page) => ({
        ...page,
        zones: page.zones.map((zone) =>
          zone.id === zoneId
            ? {
                ...zone,
                colSpan: clamp(colSpan, 1, page.grid.columns - zone.column),
                rowSpan: clamp(rowSpan, 1, page.grid.rows.length - zone.row),
              }
            : zone
        ),
      })),
      hasUnsavedChanges: true,
    })),

  removeWebDesignZone: (zoneId) =>
    set((state) => ({
      webDesign: updateActiveWebDesignPage(state.webDesign, (page) => ({
        ...page,
        zones: page.zones.filter((zone) => zone.id !== zoneId),
      })),
      hasUnsavedChanges: true,
    })),

  addWebDesignTextZone: (style) =>
    set((state) => {
      const activePage = getActiveWebDesignPage(state.webDesign);
      const allZones = [
        ...activePage.zones.map((z) => ({ column: z.column, row: z.row, colSpan: z.colSpan, rowSpan: z.rowSpan })),
        ...(activePage.textZones ?? []).map((z) => ({ column: z.column, row: z.row, colSpan: z.colSpan, rowSpan: z.rowSpan })),
      ];
      const placement = findNextFreeCell(activePage.grid, allZones);
      const rows =
        placement.row < activePage.grid.rows.length
          ? activePage.grid.rows
          : [...activePage.grid.rows, { id: `row-${activePage.grid.rows.length + 1}`, height: 200 }];
      const defaultContent =
        style === "title" ? "标题" : style === "subtitle" ? "副标题" : "在此输入分析说明...";
      const newZone: WebDesignTextZone = {
        id: `text-zone-${Date.now().toString(36)}`,
        column: placement.column,
        row: placement.row,
        colSpan: style === "title" ? activePage.grid.columns : 1,
        rowSpan: 1,
        content: defaultContent,
        style,
      };
      return {
        webDesign: updateActiveWebDesignPage(state.webDesign, (page) => ({
          ...page,
          grid: { ...page.grid, rows },
          textZones: [...(page.textZones ?? []), newZone],
        })),
        hasUnsavedChanges: true,
      };
    }),

  updateWebDesignTextZone: (zoneId, updates) =>
    set((state) => ({
      webDesign: updateActiveWebDesignPage(state.webDesign, (page) => ({
        ...page,
        textZones: (page.textZones ?? []).map((zone) =>
          zone.id === zoneId ? { ...zone, ...updates } : zone
        ),
      })),
      hasUnsavedChanges: true,
    })),

  removeWebDesignTextZone: (zoneId) =>
    set((state) => ({
      webDesign: updateActiveWebDesignPage(state.webDesign, (page) => ({
        ...page,
        textZones: (page.textZones ?? []).filter((zone) => zone.id !== zoneId),
      })),
      hasUnsavedChanges: true,
    })),

  setWebDesignPreview: (preview) =>
    set((state) => ({
      webDesign: { ...state.webDesign, preview },
      hasUnsavedChanges: true,
    })),

  setActiveWebDesignPage: (pageId) =>
    set((state) => {
      const layout = ensureWebDesignPages(state.webDesign);
      const page = layout.pages?.find((item) => item.id === pageId);
      if (!page || layout.activePageId === pageId) return {};
      return {
        webDesign: {
          ...layout,
          activePageId: pageId,
          grid: page.grid,
          zones: page.zones,
        },
        hasUnsavedChanges: true,
      };
    }),

  addWebDesignSidebarItem: (parentId, labels) =>
    set((state) => {
      const layout = ensureWebDesignPages(state.webDesign);
      const activePage = getActiveWebDesignPage(layout);
      const result = addSidebarItem(
        layout.sidebar,
        parentId,
        activePage.grid.rows[0]?.id ?? "row-1",
        labels
      );
      if (!result) return {};
      const nextPage: WebDesignPage = {
        id: result.item.id,
        title: result.item.label,
        grid: cloneGrid(activePage.grid),
        zones: [],
      };
      return {
        webDesign: {
          ...layout,
          sidebar: result.items,
          pages: [...(layout.pages ?? []), nextPage],
          activePageId: nextPage.id,
          grid: nextPage.grid,
          zones: nextPage.zones,
        },
        hasUnsavedChanges: true,
      };
    }),

  updateWebDesignSidebarItem: (itemId, updates) =>
    set((state) => {
      const layout = ensureWebDesignPages(state.webDesign);
      const sidebar = mapSidebarItems(layout.sidebar, (item) =>
        item.id === itemId ? { ...item, ...updates } : item
      );
      const target = findSidebarItem(sidebar, itemId);
      const targetPageId = target?.pageId ?? itemId;
      const pages = (layout.pages ?? []).map((page) =>
        page.id === targetPageId && updates.label !== undefined ? { ...page, title: updates.label } : page
      );
      return {
        webDesign: {
          ...layout,
          sidebar,
          pages,
        },
        hasUnsavedChanges: true,
      };
    }),

  removeWebDesignSidebarItem: (itemId) =>
    set((state) => {
      const layout = ensureWebDesignPages(state.webDesign);
      const removedPageIds = collectSidebarPageIds(layout.sidebar, itemId);
      let sidebar = removeSidebarItem(layout.sidebar, itemId);
      let pages = (layout.pages ?? []).filter((page) => !removedPageIds.has(page.id));
      if (!sidebar.length || !pages.length) {
        sidebar = DEFAULT_WEB_DESIGN_LAYOUT.sidebar;
        pages = DEFAULT_WEB_DESIGN_LAYOUT.pages ?? [];
      }
      const activePageId = pages.some((page) => page.id === layout.activePageId)
        ? layout.activePageId
        : pages[0]?.id;
      const activePage = pages.find((page) => page.id === activePageId) ?? pages[0];
      return {
        webDesign: {
          ...layout,
          sidebar,
          pages,
          activePageId: activePage?.id,
          grid: activePage?.grid ?? DEFAULT_WEB_DESIGN_LAYOUT.grid,
          zones: activePage?.zones ?? [],
        },
        hasUnsavedChanges: true,
      };
    }),

  loadSnapshot: (snapshot) =>
    set((state) => {
      // Reject stale background refetches for a workspace that is no longer active.
      // This can happen when the user switches workspaces quickly and a previous
      // queryFn resolves after the active workspace has already changed.
      if (snapshot.workspaceId !== state.activeWorkspaceId) {
        return {};
      }
      const canvasFormat = normalizeCanvasFormat(snapshot.canvasFormat);

      // Start from per-format maps if available
      const nodesByFormat: Partial<Record<WorkspaceCanvasFormatId, WorkspaceNode[]>> = {
        ...(snapshot.nodesByFormat ?? {}),
      };
      const edgesByFormat: Partial<Record<WorkspaceCanvasFormatId, WorkspaceEdge[]>> = {
        ...(snapshot.edgesByFormat ?? {}),
      };

      // Migrate legacy flat nodes/edges into the saved canvas-format bucket
      if (snapshot.nodes?.length && !nodesByFormat[canvasFormat.id]) {
        nodesByFormat[canvasFormat.id] = snapshot.nodes;
      }
      if (snapshot.edges?.length && !edgesByFormat[canvasFormat.id]) {
        edgesByFormat[canvasFormat.id] = snapshot.edges;
      }

      return {
        nodes: nodesByFormat[canvasFormat.id] ?? [],
        edges: edgesByFormat[canvasFormat.id] ?? [],
        nodesByFormat,
        edgesByFormat,
        viewport: snapshot.viewport,
        canvasFormat,
        webDesign: normalizeWebDesignLayout(snapshot.webDesign),
        hasUnsavedChanges: false,
      };
    }),

  getSnapshot: () => {
    const { activeWorkspaceId, nodes, edges, nodesByFormat, edgesByFormat, viewport, canvasFormat, webDesign } = get();
    if (!activeWorkspaceId) return null;

    // Flush active format's nodes into the per-format maps before saving
    const snapshotNodesByFormat: Partial<Record<WorkspaceCanvasFormatId, WorkspaceNode[]>> = {
      ...nodesByFormat,
      [canvasFormat.id]: nodes,
    };
    const snapshotEdgesByFormat: Partial<Record<WorkspaceCanvasFormatId, WorkspaceEdge[]>> = {
      ...edgesByFormat,
      [canvasFormat.id]: edges,
    };

    return {
      workspaceId: activeWorkspaceId,
      nodes,
      edges,
      nodesByFormat: snapshotNodesByFormat,
      edgesByFormat: snapshotEdgesByFormat,
      viewport,
      canvasFormat,
      webDesign,
    };
  },

  setHasUnsavedChanges: (value) => set({ hasUnsavedChanges: value }),
}));

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, Math.trunc(value)));
}

function roundPosition(position: { x: number; y: number }): { x: number; y: number } {
  return {
    x: Math.round(position.x),
    y: Math.round(position.y),
  };
}

function removeNodesFromCanvas(
  nodes: WorkspaceNode[],
  edges: WorkspaceEdge[],
  nodeIds: string[]
): Pick<WorkspaceState, "nodes" | "edges"> {
  const idsToRemove = collectDescendantNodeIds(nodes, new Set(nodeIds));
  for (const id of nodeIds) {
    idsToRemove.add(id);
  }
  return {
    nodes: nodes.filter((node) => !idsToRemove.has(node.id)),
    edges: edges.filter((edge) => !idsToRemove.has(edge.source) && !idsToRemove.has(edge.target)),
  };
}

function collectDescendantNodeIds(nodes: WorkspaceNode[], rootIds: Set<string>): Set<string> {
  const ids = new Set<string>();
  let changed = true;
  while (changed) {
    changed = false;
    for (const node of nodes) {
      if (!node.parentId) continue;
      if ((rootIds.has(node.parentId) || ids.has(node.parentId)) && !ids.has(node.id)) {
        ids.add(node.id);
        changed = true;
      }
    }
  }
  return ids;
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

function getNodeDimensions(node: WorkspaceNode): { width: number; height: number } {
  const width = Number(node.width ?? node.measured?.width ?? ("width" in node.data ? node.data.width : 240) ?? 240);
  const height = Number(
    node.height ??
      node.measured?.height ??
      ("height" in node.data ? node.data.height : undefined) ??
      (node.data.type === "divider" ? 24 : 160)
  );
  return {
    width: Number.isFinite(width) ? width : 240,
    height: Number.isFinite(height) ? height : 160,
  };
}

function getNodesAbsoluteBounds(
  nodes: WorkspaceNode[],
  nodeMap: Map<string, WorkspaceNode>
): { x: number; y: number; width: number; height: number } {
  const boxes = nodes.map((node) => {
    const position = getAbsoluteNodePosition(node, nodeMap);
    const dimensions = getNodeDimensions(node);
    return {
      x: position.x,
      y: position.y,
      right: position.x + dimensions.width,
      bottom: position.y + dimensions.height,
    };
  });
  const x = Math.min(...boxes.map((box) => box.x));
  const y = Math.min(...boxes.map((box) => box.y));
  const right = Math.max(...boxes.map((box) => box.right));
  const bottom = Math.max(...boxes.map((box) => box.bottom));
  return { x, y, width: right - x, height: bottom - y };
}

function normalizeWebDesignLayout(value: unknown): WebDesignLayout {
  if (!value || typeof value !== "object") return DEFAULT_WEB_DESIGN_LAYOUT;
  const layout = value as Partial<WebDesignLayout>;
  const grid = {
    columns: clamp(Number(layout.grid?.columns ?? 3), 2, 10),
    rows: Array.isArray(layout.grid?.rows) && layout.grid.rows.length
      ? layout.grid.rows.map((row, index) => ({
          id: String(row.id || `row-${index + 1}`),
          height: clamp(Number(row.height ?? 400), 40, 800),
        }))
      : DEFAULT_WEB_DESIGN_LAYOUT.grid.rows,
  };
  const zones = Array.isArray(layout.zones) ? layout.zones : [];
  const sidebar = Array.isArray(layout.sidebar) && layout.sidebar.length
    ? normalizeSidebar(layout.sidebar, grid.rows[0]?.id ?? "row-1")
    : DEFAULT_WEB_DESIGN_LAYOUT.sidebar;
  return ensureWebDesignPages({
    grid: {
      columns: grid.columns,
      rows: grid.rows,
    },
    zones,
    sidebar,
    pages: normalizePages(layout.pages, grid, zones),
    activePageId: typeof layout.activePageId === "string" ? layout.activePageId : undefined,
    preview: Boolean(layout.preview),
  });
}

function findNextFreeCell(
  grid: WebDesignPage["grid"],
  zones: { column: number; row: number; colSpan: number; rowSpan: number }[]
): { column: number; row: number } {
  const occupied = new Set<string>();
  for (const zone of zones) {
    for (let row = zone.row; row < zone.row + zone.rowSpan; row += 1) {
      for (let column = zone.column; column < zone.column + zone.colSpan; column += 1) {
        occupied.add(`${column}:${row}`);
      }
    }
  }
  for (let row = 0; row < grid.rows.length; row += 1) {
    for (let column = 0; column < grid.columns; column += 1) {
      if (!occupied.has(`${column}:${row}`)) return { column, row };
    }
  }
  return { column: 0, row: grid.rows.length };
}

function findNextWebDesignCell(page: Pick<WebDesignPage, "grid" | "zones">): { column: number; row: number } {
  const occupied = new Set<string>();
  for (const zone of page.zones) {
    for (let row = zone.row; row < zone.row + zone.rowSpan; row += 1) {
      for (let column = zone.column; column < zone.column + zone.colSpan; column += 1) {
        occupied.add(`${column}:${row}`);
      }
    }
  }

  for (let row = 0; row < page.grid.rows.length; row += 1) {
    for (let column = 0; column < page.grid.columns; column += 1) {
      if (!occupied.has(`${column}:${row}`)) return { column, row };
    }
  }

  return { column: 0, row: page.grid.rows.length };
}

function zoneOverlaps(
  zones: WebDesignLayout["zones"],
  zoneId: string,
  column: number,
  row: number,
  colSpan: number,
  rowSpan: number
): boolean {
  return zones.some((zone) => {
    if (zone.id === zoneId) return false;

    return (
      column < zone.column + zone.colSpan &&
      column + colSpan > zone.column &&
      row < zone.row + zone.rowSpan &&
      row + rowSpan > zone.row
    );
  });
}

function clampPageToColumns(page: WebDesignPage, columns: number): WebDesignPage {
  return {
    ...page,
    zones: page.zones.map((zone) => ({
      ...zone,
      column: clamp(zone.column, 0, columns - 1),
      colSpan: clamp(zone.colSpan, 1, columns - clamp(zone.column, 0, columns - 1)),
    })),
  };
}

function getActiveWebDesignPage(layout: WebDesignLayout): WebDesignPage {
  const normalized = ensureWebDesignPages(layout);
  const activePage =
    normalized.pages?.find((page) => page.id === normalized.activePageId) ??
    normalized.pages?.[0];
  return activePage ?? {
    id: "section-1",
    title: "Section 1",
    grid: normalized.grid,
    zones: normalized.zones,
  };
}

function replaceActiveWebDesignPage(
  layout: WebDesignLayout,
  page: WebDesignPage,
  overrides: Partial<Pick<WebDesignLayout, "preview">> = {}
): WebDesignLayout {
  const normalized = ensureWebDesignPages(layout);
  const pages = normalized.pages?.some((item) => item.id === page.id)
    ? normalized.pages.map((item) => (item.id === page.id ? page : item))
    : [...(normalized.pages ?? []), page];
  return {
    ...normalized,
    ...overrides,
    activePageId: page.id,
    grid: page.grid,
    zones: page.zones,
    pages,
  };
}

function updateActiveWebDesignPage(
  layout: WebDesignLayout,
  updater: (page: WebDesignPage) => WebDesignPage
): WebDesignLayout {
  return replaceActiveWebDesignPage(layout, updater(getActiveWebDesignPage(layout)));
}

function addSidebarItem(
  items: WebDesignSidebarItem[],
  parentId: string | undefined,
  anchorRowId: string,
  labels?: { sectionLabel: string; childLabel: string }
): { items: WebDesignSidebarItem[]; item: WebDesignSidebarItem } | null {
  const id = `section-${Date.now().toString(36)}`;
  const nextItem = {
    id,
    label: parentId ? labels?.childLabel ?? "Sub-section" : labels?.sectionLabel ?? `Section ${items.length + 1}`,
    pageId: id,
    anchorRowId,
    children: [],
  };
  if (!parentId) return { items: [...items, nextItem], item: nextItem };
  let found = false;
  const nextItems = items.map((item) => {
    if (item.id !== parentId) return item;
    found = true;
    return { ...item, children: [...item.children, nextItem] };
  });
  if (!found) return null;
  return {
    items: nextItems,
    item: nextItem,
  };
}

function mapSidebarItems(
  items: WebDesignSidebarItem[],
  mapper: (item: WebDesignSidebarItem) => WebDesignSidebarItem
): WebDesignSidebarItem[] {
  return items.map((item) => mapper({ ...item, children: mapSidebarItems(item.children, mapper) }));
}

function ensureWebDesignPages(layout: WebDesignLayout): WebDesignLayout {
  const fallbackGrid = layout.grid ?? DEFAULT_WEB_DESIGN_LAYOUT.grid;
  const sidebar = normalizeSidebar(
    layout.sidebar?.length ? layout.sidebar : DEFAULT_WEB_DESIGN_LAYOUT.sidebar,
    fallbackGrid.rows[0]?.id ?? "row-1"
  );
  const sidebarItems = flattenSidebar(sidebar);
  const pagesById = new Map((layout.pages ?? []).map((page) => [page.id, page]));
  const pages = sidebarItems.map((item, index) => {
    const pageId = item.pageId ?? item.id;
    const existing = pagesById.get(pageId);
    if (existing) {
      return {
        ...existing,
        title: existing.title || item.label,
        grid: normalizeGrid(existing.grid ?? fallbackGrid),
        zones: Array.isArray(existing.zones) ? existing.zones : [],
        textZones: Array.isArray(existing.textZones) ? existing.textZones : [],
      };
    }
    return {
      id: pageId,
      title: item.label,
      grid: cloneGrid(index === 0 ? fallbackGrid : DEFAULT_WEB_DESIGN_LAYOUT.grid),
      zones: index === 0 && Array.isArray(layout.zones) ? layout.zones : [],
      textZones: [],
    };
  });
  const activePageId = pages.some((page) => page.id === layout.activePageId)
    ? layout.activePageId
    : pages[0]?.id;
  const activePage = pages.find((page) => page.id === activePageId) ?? pages[0];
  return {
    ...layout,
    sidebar,
    pages,
    activePageId,
    grid: activePage?.grid ?? fallbackGrid,
    zones: activePage?.zones ?? [],
  };
}

function normalizePages(
  pages: WebDesignLayout["pages"],
  fallbackGrid: WebDesignLayout["grid"],
  fallbackZones: WebDesignLayout["zones"]
): WebDesignPage[] | undefined {
  if (!Array.isArray(pages)) return undefined;
  return pages.map((page, index) => ({
    id: String(page.id || `section-${index + 1}`),
    title: String(page.title || `Section ${index + 1}`),
    grid: normalizeGrid(page.grid ?? fallbackGrid),
    zones: Array.isArray(page.zones) ? page.zones : index === 0 ? fallbackZones : [],
    textZones: Array.isArray(page.textZones) ? page.textZones : [],
  }));
}

function normalizeGrid(grid: WebDesignLayout["grid"]): WebDesignLayout["grid"] {
  return {
    columns: clamp(Number(grid.columns ?? 3), 2, 10),
    rows: Array.isArray(grid.rows) && grid.rows.length
      ? grid.rows.map((row, index) => ({
          id: String(row.id || `row-${index + 1}`),
          height: clamp(Number(row.height ?? 400), 40, 800),
        }))
      : cloneGrid(DEFAULT_WEB_DESIGN_LAYOUT.grid).rows,
  };
}

function normalizeSidebar(items: WebDesignSidebarItem[], fallbackRowId: string): WebDesignSidebarItem[] {
  return items.map((item, index) => {
    const id = String(item.id || `section-${index + 1}`);
    return {
      id,
      label: String(item.label ?? `Section ${index + 1}`),
      pageId: typeof item.pageId === "string" ? item.pageId : id,
      anchorRowId: String(item.anchorRowId || fallbackRowId),
      children: normalizeSidebar(Array.isArray(item.children) ? item.children : [], fallbackRowId),
    };
  });
}

function cloneGrid(grid: WebDesignLayout["grid"]): WebDesignLayout["grid"] {
  return {
    columns: grid.columns,
    rows: grid.rows.map((row) => ({ ...row })),
  };
}

function flattenSidebar(items: WebDesignSidebarItem[]): WebDesignSidebarItem[] {
  return items.flatMap((item) => [item, ...flattenSidebar(item.children)]);
}

function findSidebarItem(items: WebDesignSidebarItem[], itemId: string): WebDesignSidebarItem | undefined {
  for (const item of items) {
    if (item.id === itemId) return item;
    const child = findSidebarItem(item.children, itemId);
    if (child) return child;
  }
  return undefined;
}

function collectSidebarPageIds(items: WebDesignSidebarItem[], itemId: string): Set<string> {
  const target = findSidebarItem(items, itemId);
  return new Set(target ? flattenSidebar([target]).map((item) => item.pageId ?? item.id) : []);
}

function removeSidebarItem(items: WebDesignSidebarItem[], itemId: string): WebDesignSidebarItem[] {
  return items
    .filter((item) => item.id !== itemId)
    .map((item) => ({ ...item, children: removeSidebarItem(item.children, itemId) }));
}

function retargetSidebar(items: WebDesignSidebarItem[], fallbackRowId: string): WebDesignSidebarItem[] {
  return items.map((item) => ({
    ...item,
    anchorRowId: item.anchorRowId || fallbackRowId,
    children: retargetSidebar(item.children, fallbackRowId),
  }));
}
