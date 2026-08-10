import { create } from "zustand";
import {
  DEFAULT_CANVAS_FORMAT,
  MAX_CANVAS_PAGES,
  getCanvasFormatPreset,
  getCanvasPageCount,
  getCanvasPageStride,
  getMaxOccupiedCanvasPage,
  isBoundedCanvasFormat,
  normalizeCanvasFormat,
} from "@/lib/workspace/canvas-formats";
import { getCanvasBackgroundPreset } from "@/lib/workspace/canvas-backgrounds";
import { findOpenCanvasPosition } from "@/lib/workspace/canvas-layout";
import {
  WORKSPACE_SELECTION_STORAGE_KEY,
  WORKSPACE_SNAPSHOT_STORAGE_KEY,
  safeLoadFromStorage,
  safeSaveToStorage,
} from "@/lib/chat/session-storage";
import {
  CHART_DEFAULT_H,
  CHART_DEFAULT_W,
  compactLayout,
  createFluidGrid,
  findSlot,
  isFluidGrid,
  layoutItemsToPage,
  migrateLegacyPage,
  minSizeFor,
  moveItem,
  pageToLayoutItems,
  resizeItem,
  rowUnitOf,
  type LayoutItem,
} from "@/lib/workspace/web-design-layout";
import {
  AGENT_ERROR_CHART_TYPE,
  agentRunIdFromRootPageId,
  isAgentNodeForRun,
  textStyleForSectionLevel,
  type AgentCanvasStoreOp,
} from "@/lib/workspace/agent-canvas-layout";
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
import type { ChartAsset } from "@/types/chart";

const DEFAULT_WEB_DESIGN_LAYOUT: WebDesignLayout = {
  grid: createFluidGrid(),
  zones: [],
  sidebar: [{ id: "section-1", label: "Section 1", pageId: "section-1", anchorRowId: "row-1", children: [] }],
  pages: [
    {
      id: "section-1",
      title: "Section 1",
      grid: createFluidGrid(),
      zones: [],
      textZones: [],
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
  canvasPages: Partial<Record<WorkspaceCanvasFormatId, number>>;
  canvasBackgrounds: Partial<Record<WorkspaceCanvasFormatId, string>>;
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
  /** Replace one chart's asset/spec without changing its canvas geometry. */
  replaceChartNodeAsset: (nodeId: string, asset: ChartAsset) => boolean;
  removeNode: (nodeId: string) => void;
  removeNodes: (nodeIds: string[]) => void;
  groupNodes: (nodeIds: string[], title?: string) => string | null;
  ungroupNodes: (nodeIds: string[]) => void;
  setViewport: (viewport: { x: number; y: number; zoom: number }) => void;
  setCanvasFormat: (canvasFormat: WorkspaceCanvasFormat) => void;
  setCanvasBackground: (backgroundId: string) => void;
  addCanvasPage: () => void;
  removeCanvasPage: () => void;
  deleteCanvasPage: (pageIndex: number) => void;
  /** Move a chart or text block to grid units (x, y); collisions push down, then the page compacts. */
  moveWebDesignBlock: (blockId: string, x: number, y: number) => void;
  /** Resize a chart or text block to grid units (w, h) with per-kind minimums. */
  resizeWebDesignBlock: (blockId: string, w: number, h: number) => void;
  /** Commit a full drag/resize preview layout in one state update. */
  commitWebDesignLayout: (items: LayoutItem[]) => void;
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
  /**
   * Apply one agent-canvas op onto the run's page in strict seq order.
   * Idempotent: an op whose block id already exists is skipped (returns false),
   * except a `place_chart` replacing an error placeholder in place.
   */
  applyAgentCanvasOp: (op: AgentCanvasStoreOp) => boolean;
  /** Run-level undo: delete the run's page (cascade) and its chart nodes. */
  undoAgentRun: (pageId: string) => void;
};

function nodeFootprint(node: WorkspaceNode): { width: number; height: number } {
  const data = node.data as { width?: number; height?: number };
  const width = Number(node.width ?? node.measured?.width ?? data.width ?? 0);
  const height = Number(node.height ?? node.measured?.height ?? data.height ?? 24);
  return {
    width: Number.isFinite(width) && width > 0 ? width : 320,
    height: Number.isFinite(height) && height > 0 ? height : 180,
  };
}

function lowestNodeBottom(nodes: WorkspaceNode[]): number {
  return nodes.reduce((lowest, node) => {
    if (node.hidden || node.parentId) return lowest;
    return Math.max(lowest, Number(node.position?.y ?? 0) + nodeFootprint(node).height);
  }, 0);
}

function applyAgentOpToNodeCanvas(
  state: WorkspaceState,
  op: AgentCanvasStoreOp
): { applied: boolean; patch: Partial<WorkspaceState> } {
  const formatId = op.canvasFormat;
  const isActive = state.canvasFormat.id === formatId;
  const targetNodes = [...(isActive ? state.nodes : (state.nodesByFormat[formatId] ?? []))];
  const nodeId = op.type === "create_page" ? op.node.id : op.node.id;
  const existingIndex = targetNodes.findIndex((node) => node.id === nodeId);

  if (existingIndex >= 0) {
    if (op.type !== "place_chart") return { applied: false, patch: {} };
    const existing = targetNodes[existingIndex];
    if (
      existing.data.type !== "chart" ||
      existing.data.chartType !== AGENT_ERROR_CHART_TYPE ||
      op.node.data.type !== "chart"
    ) {
      return { applied: false, patch: {} };
    }
    const existingData = existing.data;
    const replacementData = op.node.data;
    targetNodes[existingIndex] = {
      ...op.node,
      id: existing.id,
      position: existing.position,
      width: existing.width,
      height: existing.height,
      initialWidth: existing.initialWidth,
      initialHeight: existing.initialHeight,
      data: {
        ...replacementData,
        width: existingData.width,
        height: existingData.height,
      },
    };
    return {
      applied: true,
      patch: {
        nodesByFormat: { ...state.nodesByFormat, [formatId]: targetNodes },
        ...(isActive ? { nodes: targetNodes } : {}),
        hasUnsavedChanges: true,
      },
    };
  }

  const preset = getCanvasFormatPreset(formatId);
  const bounded = isBoundedCanvasFormat(preset);
  const currentPageCount = getCanvasPageCount(formatId, state.canvasPages);
  const runNodes = targetNodes.filter((node) => isAgentNodeForRun(node, op.runId));
  const size = nodeFootprint(op.node);
  let position: { x: number; y: number };
  let nextPageCount = currentPageCount;

  if (op.type === "create_page") {
    if (bounded) {
      const relevant = runNodes.length > 0 ? runNodes : targetNodes;
      const startPage = relevant.length > 0 ? getMaxOccupiedCanvasPage(relevant, preset) + 1 : 0;
      nextPageCount = Math.max(currentPageCount, startPage + 1);
      position = findOpenCanvasPosition(
        targetNodes,
        size,
        formatId,
        nextPageCount,
        { startPageIndex: startPage }
      );
    } else {
      const relevant = runNodes.length > 0 ? runNodes : targetNodes;
      const startY = relevant.length > 0 ? lowestNodeBottom(relevant) + 64 : 50;
      position = findOpenCanvasPosition(targetNodes, size, formatId, 1, { startY });
    }
  } else {
    const marker = runNodes.find(
      (node) => node.data.agentPageId === op.pageId && node.data.agentPageMarker
    );
    if (!marker) return { applied: false, patch: {} };

    if (bounded) {
      const stride = getCanvasPageStride(preset);
      const startPage = Math.max(0, Math.floor(Number(marker.position?.y ?? 0) / stride));
      // Include one spare physical page so dense dashboard sections spill
      // safely without ever landing outside a publishable page boundary.
      const searchPageCount = Math.max(currentPageCount + 1, startPage + 2);
      position = findOpenCanvasPosition(
        targetNodes,
        size,
        formatId,
        searchPageCount,
        { startPageIndex: startPage }
      );
      const placedPage = Math.max(0, Math.floor(position.y / stride));
      nextPageCount = Math.max(currentPageCount, placedPage + 1);
    } else {
      const markerSize = nodeFootprint(marker);
      position = findOpenCanvasPosition(targetNodes, size, formatId, 1, {
        startY: Number(marker.position?.y ?? 0) + markerSize.height + 24,
        contentWidth: markerSize.width,
      });
    }
  }

  const placedNode: WorkspaceNode = { ...op.node, position };
  targetNodes.push(placedNode);
  return {
    applied: true,
    patch: {
      nodesByFormat: { ...state.nodesByFormat, [formatId]: targetNodes },
      ...(isActive ? { nodes: targetNodes } : {}),
      ...(bounded && nextPageCount !== currentPageCount
        ? { canvasPages: { ...state.canvasPages, [formatId]: nextPageCount } }
        : {}),
      hasUnsavedChanges: true,
    },
  };
}

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
  canvasPages: {},
  canvasBackgrounds: {},
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
      canvasPages: {},
      canvasBackgrounds: {},
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
      const items = pageToLayoutItems(activePage);
      const slot = findSlot(items, CHART_DEFAULT_W, CHART_DEFAULT_H);
      const nextPage = {
        ...activePage,
        zones: [
          ...activePage.zones,
          {
            id: `zone-${node.id}`,
            nodeId: node.id,
            chartId: node.data.assetId,
            column: slot.x,
            row: slot.y,
            colSpan: CHART_DEFAULT_W,
            rowSpan: CHART_DEFAULT_H,
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

  replaceChartNodeAsset: (nodeId, asset) => {
    let replaced = false;
    const replaceIn = (nodes: WorkspaceNode[] | undefined): WorkspaceNode[] =>
      (nodes ?? []).map((node) => {
        if (node.id !== nodeId || node.data.type !== "chart") return node;
        replaced = true;
        return {
          ...node,
          data: {
            ...node.data,
            assetId: asset.id,
            title: asset.title,
            chartType: asset.chartType,
            spec: asset.spec,
            assistantRows: asset.assistantRows,
            assistantRowsComplete: asset.assistantRowsComplete,
          },
        };
      });

    set((state) => {
      const nodes = replaceIn(state.nodes);
      const nodesByFormat = Object.fromEntries(
        Object.entries(state.nodesByFormat).map(([format, formatNodes]) => [
          format,
          replaceIn(formatNodes),
        ])
      ) as Partial<Record<WorkspaceCanvasFormatId, WorkspaceNode[]>>;
      const pages = state.webDesign.pages?.map((page) => ({
        ...page,
        zones: page.zones.map((zone) =>
          zone.nodeId === nodeId ? { ...zone, chartId: asset.id } : zone
        ),
      }));

      if (!replaced) return {};
      const activePage = pages?.find((page) => page.id === state.webDesign.activePageId);
      return {
        nodes,
        nodesByFormat,
        webDesign: {
          ...state.webDesign,
          ...(pages ? { pages } : {}),
          ...(activePage ? { grid: activePage.grid, zones: activePage.zones } : {}),
        },
        hasUnsavedChanges: true,
      };
    });
    return replaced;
  },

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

  setCanvasBackground: (backgroundId) =>
    set((state) => {
      if (state.canvasBackgrounds[state.canvasFormat.id] === backgroundId) {
        return {};
      }
      return {
        canvasBackgrounds: {
          ...state.canvasBackgrounds,
          [state.canvasFormat.id]: backgroundId,
        },
        hasUnsavedChanges: true,
      };
    }),

  addCanvasPage: () =>
    set((state) => {
      const preset = getCanvasFormatPreset(state.canvasFormat.id);
      if (!isBoundedCanvasFormat(preset)) return {};
      const current = getCanvasPageCount(state.canvasFormat.id, state.canvasPages);
      const next = Math.min(MAX_CANVAS_PAGES, current + 1);
      if (next === current) return {};
      return {
        canvasPages: { ...state.canvasPages, [state.canvasFormat.id]: next },
        hasUnsavedChanges: true,
      };
    }),

  removeCanvasPage: () =>
    set((state) => {
      const preset = getCanvasFormatPreset(state.canvasFormat.id);
      if (!isBoundedCanvasFormat(preset)) return {};
      const current = getCanvasPageCount(state.canvasFormat.id, state.canvasPages);
      // Never drop a page that still holds content, so removal can't orphan nodes
      // beyond the visible canvas.
      const minPages = Math.max(1, getMaxOccupiedCanvasPage(state.nodes, preset) + 1);
      const next = Math.max(minPages, current - 1);
      if (next === current) return {};
      return {
        canvasPages: { ...state.canvasPages, [state.canvasFormat.id]: next },
        hasUnsavedChanges: true,
      };
    }),

  // Delete an arbitrary page (Word/PPT style): drop the nodes that sit on that
  // page, slide every node below it up by one page, and decrement the count.
  deleteCanvasPage: (pageIndex) =>
    set((state) => {
      const preset = getCanvasFormatPreset(state.canvasFormat.id);
      if (!isBoundedCanvasFormat(preset)) return {};
      const current = getCanvasPageCount(state.canvasFormat.id, state.canvasPages);
      if (current <= 1) return {};
      const index = Math.trunc(pageIndex);
      if (!Number.isFinite(index) || index < 0 || index >= current) return {};

      const stride = getCanvasPageStride(preset);
      const pageTop = index * stride;
      const pageBottom = pageTop + stride;

      // Only top-level nodes carry absolute coordinates; grouped children move
      // with their parent, so classify and shift by parent position alone.
      const removeIds = state.nodes
        .filter((node) => !node.parentId)
        .filter((node) => {
          const top = Number(node.position?.y ?? 0);
          return top >= pageTop && top < pageBottom;
        })
        .map((node) => node.id);

      const pruned = removeIds.length
        ? removeNodesFromCanvas(state.nodes, state.edges, removeIds)
        : { nodes: state.nodes, edges: state.edges };

      const nextNodes = pruned.nodes.map((node) => {
        if (node.parentId) return node;
        const top = Number(node.position?.y ?? 0);
        if (top >= pageBottom) {
          return { ...node, position: { ...node.position, y: top - stride } };
        }
        return node;
      });

      return {
        nodes: nextNodes,
        edges: pruned.edges,
        canvasPages: { ...state.canvasPages, [state.canvasFormat.id]: current - 1 },
        hasUnsavedChanges: true,
      };
    }),

  moveWebDesignBlock: (blockId, x, y) =>
    set((state) => {
      const activePage = getActiveWebDesignPage(state.webDesign);
      const items = pageToLayoutItems(activePage);
      if (!items.some((item) => item.id === blockId)) return {};
      return {
        webDesign: updateActiveWebDesignPage(state.webDesign, (page) =>
          layoutItemsToPage(page, moveItem(pageToLayoutItems(page), blockId, x, y))
        ),
        hasUnsavedChanges: true,
      };
    }),

  resizeWebDesignBlock: (blockId, w, h) =>
    set((state) => {
      const activePage = getActiveWebDesignPage(state.webDesign);
      const target = pageToLayoutItems(activePage).find((item) => item.id === blockId);
      if (!target) return {};
      const { minW, minH } = minSizeFor(target.kind);
      return {
        webDesign: updateActiveWebDesignPage(state.webDesign, (page) =>
          layoutItemsToPage(page, resizeItem(pageToLayoutItems(page), blockId, w, h, minW, minH))
        ),
        hasUnsavedChanges: true,
      };
    }),

  commitWebDesignLayout: (items) =>
    set((state) => ({
      webDesign: updateActiveWebDesignPage(state.webDesign, (page) =>
        layoutItemsToPage(page, items)
      ),
      hasUnsavedChanges: true,
    })),

  removeWebDesignZone: (zoneId) =>
    set((state) => ({
      webDesign: updateActiveWebDesignPage(state.webDesign, (page) => {
        const next = { ...page, zones: page.zones.filter((zone) => zone.id !== zoneId) };
        return layoutItemsToPage(next, compactLayout(pageToLayoutItems(next)));
      }),
      hasUnsavedChanges: true,
    })),

  addWebDesignTextZone: (style) =>
    set((state) => {
      const activePage = getActiveWebDesignPage(state.webDesign);
      const size =
        style === "title"
          ? { w: 12, h: 1 }
          : style === "subtitle"
            ? { w: 12, h: 1 }
            : { w: 6, h: 2 };
      const slot = findSlot(pageToLayoutItems(activePage), size.w, size.h);
      const defaultContent =
        style === "title" ? "标题" : style === "subtitle" ? "副标题" : "在此输入分析说明...";
      const newZone: WebDesignTextZone = {
        id: `text-zone-${Date.now().toString(36)}`,
        column: slot.x,
        row: slot.y,
        colSpan: size.w,
        rowSpan: size.h,
        content: defaultContent,
        style,
      };
      return {
        webDesign: updateActiveWebDesignPage(state.webDesign, (page) => ({
          ...page,
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
      webDesign: updateActiveWebDesignPage(state.webDesign, (page) => {
        const next = { ...page, textZones: (page.textZones ?? []).filter((zone) => zone.id !== zoneId) };
        return layoutItemsToPage(next, compactLayout(pageToLayoutItems(next)));
      }),
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
        canvasPages: normalizeCanvasPages(snapshot.canvasPages),
        canvasBackgrounds: normalizeCanvasBackgrounds(snapshot.canvasBackgrounds),
        viewport: snapshot.viewport,
        canvasFormat,
        webDesign: normalizeWebDesignLayout(snapshot.webDesign),
        hasUnsavedChanges: false,
      };
    }),

  getSnapshot: () => {
    const { activeWorkspaceId, nodes, edges, nodesByFormat, edgesByFormat, canvasPages, canvasBackgrounds, viewport, canvasFormat, webDesign } = get();
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
      canvasPages,
      canvasBackgrounds,
      viewport,
      canvasFormat,
      webDesign,
    };
  },

  setHasUnsavedChanges: (value) => set({ hasUnsavedChanges: value }),

  applyAgentCanvasOp: (op) => {
    let applied = false;
    set((state) => {
      if (op.canvasFormat !== "web-design") {
        const result = applyAgentOpToNodeCanvas(state, op);
        applied = result.applied;
        return result.patch;
      }

      const layout = ensureWebDesignPages(state.webDesign);

      if (op.type === "create_page") {
        if ((layout.pages ?? []).some((page) => page.id === op.pageId)) return {};
        const page: WebDesignPage = {
          id: op.pageId,
          title: op.title,
          grid: createFluidGrid(),
          zones: [],
          textZones: [],
        };
        const sidebarItem: WebDesignSidebarItem = {
          id: op.pageId,
          label: op.title,
          pageId: op.pageId,
          anchorRowId: "row-1",
          children: [],
        };
        // A run may open several pages. Every page after the first is nested
        // under the run's root sidebar item, so the run reads as one unit and
        // run-level undo stays a single cascade delete.
        const parentId = op.parentPageId;
        const hasParent = Boolean(parentId) && Boolean(findSidebarItem(layout.sidebar, parentId));
        const sidebar = hasParent
          ? appendSidebarChild(layout.sidebar, parentId, sidebarItem)
          : [...layout.sidebar, sidebarItem];
        const nodesByFormat = { ...state.nodesByFormat };
        const edgesByFormat = { ...state.edgesByFormat };
        const isWebDesignActive = state.canvasFormat.id === "web-design";
        if (isWebDesignActive) {
          nodesByFormat["web-design"] = state.nodes;
          edgesByFormat["web-design"] = state.edges;
        }
        applied = true;
        return {
          ...(isWebDesignActive
            ? {
                nodes: nodesByFormat["web-design"] ?? [],
                edges: edgesByFormat["web-design"] ?? [],
              }
            : {}),
          nodesByFormat,
          edgesByFormat,
          webDesign: {
            ...layout,
            sidebar,
            pages: [...(layout.pages ?? []), page],
            // Follow the agent onto the page it is currently filling.
            activePageId: op.pageId,
            grid: page.grid,
            zones: page.zones,
            preview: false,
          },
          hasUnsavedChanges: true,
        };
      }

      const pages = layout.pages ?? [];
      const page = pages.find((item) => item.id === op.pageId);
      if (!page) return {};
      const blockExists =
        page.zones.some((zone) => zone.id === op.blockId) ||
        (page.textZones ?? []).some((zone) => zone.id === op.blockId);

      const replacePage = (nextPage: WebDesignPage, extra: Partial<WorkspaceState> = {}) => {
        const nextPages = pages.map((item) => (item.id === nextPage.id ? nextPage : item));
        const isActivePage = layout.activePageId === nextPage.id;
        return {
          ...extra,
          webDesign: {
            ...layout,
            pages: nextPages,
            grid: isActivePage ? nextPage.grid : layout.grid,
            zones: isActivePage ? nextPage.zones : layout.zones,
          },
          hasUnsavedChanges: true,
        };
      };

      if (op.type === "add_section" || op.type === "add_text_block") {
        if (blockExists) return {};
        const style =
          op.type === "add_section" ? textStyleForSectionLevel(op.level) : op.style;
        const content = op.type === "add_section" ? op.title : op.content;
        const size = style === "body" ? { w: 12, h: 2 } : { w: 12, h: 1 };
        const slot = findSlot(pageToLayoutItems(page), size.w, size.h);
        const zone: WebDesignTextZone = {
          id: op.blockId,
          column: slot.x,
          row: slot.y,
          colSpan: size.w,
          rowSpan: size.h,
          content,
          style,
        };
        applied = true;
        return replacePage({ ...page, textZones: [...(page.textZones ?? []), zone] });
      }

      // place_chart / error_placeholder: both add a chart-node-backed zone.
      const webDesignNodes = [...(state.nodesByFormat["web-design"] ?? [])];
      const isWebDesignActive = state.canvasFormat.id === "web-design";
      const existingZone = page.zones.find((zone) => zone.id === op.blockId);

      if (existingZone) {
        if (op.type !== "place_chart") return {};
        // Retry success replaces an error placeholder in place: same zone rect,
        // node data swapped to the real chart.
        const nodeIndex = webDesignNodes.findIndex((node) => node.id === existingZone.nodeId);
        const currentNode = nodeIndex >= 0 ? webDesignNodes[nodeIndex] : null;
        const isPlaceholder =
          currentNode?.data.type === "chart" &&
          currentNode.data.chartType === AGENT_ERROR_CHART_TYPE;
        if (!isPlaceholder) return {};
        const replacedNode = { ...op.node, id: existingZone.nodeId, position: currentNode.position };
        webDesignNodes[nodeIndex] = replacedNode;
        const nextZone = { ...existingZone, chartId: op.chartId };
        applied = true;
        return replacePage(
          {
            ...page,
            zones: page.zones.map((zone) => (zone.id === op.blockId ? nextZone : zone)),
          },
          {
            nodesByFormat: { ...state.nodesByFormat, "web-design": webDesignNodes },
            ...(isWebDesignActive ? { nodes: webDesignNodes } : {}),
          }
        );
      }

      if (blockExists) return {};
      const slot = findSlot(pageToLayoutItems(page), op.span.w, op.span.h);
      const zone = {
        id: op.blockId,
        nodeId: op.node.id,
        chartId: op.type === "place_chart" ? op.chartId : op.blockId,
        column: slot.x,
        row: slot.y,
        colSpan: op.span.w,
        rowSpan: op.span.h,
      };
      if (!webDesignNodes.some((node) => node.id === op.node.id)) {
        webDesignNodes.push(op.node);
      }
      applied = true;
      return replacePage(
        { ...page, zones: [...page.zones, zone] },
        {
          nodesByFormat: { ...state.nodesByFormat, "web-design": webDesignNodes },
          ...(isWebDesignActive ? { nodes: webDesignNodes } : {}),
        }
      );
    });
    return applied;
  },

  undoAgentRun: (pageId) =>
    set((state) => {
      const layout = ensureWebDesignPages(state.webDesign);
      const page = (layout.pages ?? []).find((item) => item.id === pageId);
      if (!page) {
        const runId = agentRunIdFromRootPageId(pageId);
        if (!runId) return {};
        const removeFrom = (nodes: WorkspaceNode[] | undefined) =>
          (nodes ?? []).filter((node) => !isAgentNodeForRun(node, runId));
        const removedIds = new Set(
          [
            ...state.nodes,
            ...Object.values(state.nodesByFormat).flatMap((nodes) => nodes ?? []),
          ]
            .filter((node) => isAgentNodeForRun(node, runId))
            .map((node) => node.id)
        );
        if (!removedIds.size) return {};

        const nodesByFormat = Object.fromEntries(
          Object.entries(state.nodesByFormat).map(([format, nodes]) => [format, removeFrom(nodes)])
        ) as Partial<Record<WorkspaceCanvasFormatId, WorkspaceNode[]>>;
        const edgesByFormat = Object.fromEntries(
          Object.entries(state.edgesByFormat).map(([format, edges]) => [
            format,
            (edges ?? []).filter(
              (edge) => !removedIds.has(edge.source) && !removedIds.has(edge.target)
            ),
          ])
        ) as Partial<Record<WorkspaceCanvasFormatId, WorkspaceEdge[]>>;
        const nodes = removeFrom(state.nodes);
        const edges = state.edges.filter(
          (edge) => !removedIds.has(edge.source) && !removedIds.has(edge.target)
        );
        nodesByFormat[state.canvasFormat.id] = nodes;
        edgesByFormat[state.canvasFormat.id] = edges;
        return {
          nodes,
          edges,
          nodesByFormat,
          edgesByFormat,
          hasUnsavedChanges: true,
        };
      }

      // Reuse the sidebar-item removal cascade (page + zones), then drop the
      // pages' chart nodes from the web-design bucket. Chart assets stay in
      // the asset library. A multi-page run nests its extra pages under the
      // root item, so the cascade must drive which nodes are removed — using
      // only the root page's zones would strand every later page's nodes.
      const removedPageIds = collectSidebarPageIds(layout.sidebar, pageId);
      removedPageIds.add(pageId);
      const nodeIds = new Set(
        (layout.pages ?? [])
          .filter((item) => removedPageIds.has(item.id))
          .flatMap((item) => item.zones.map((zone) => zone.nodeId))
      );
      let sidebar = removeSidebarItem(layout.sidebar, pageId);
      let pages = (layout.pages ?? []).filter((item) => !removedPageIds.has(item.id) && item.id !== pageId);
      if (!sidebar.length || !pages.length) {
        sidebar = DEFAULT_WEB_DESIGN_LAYOUT.sidebar;
        pages = DEFAULT_WEB_DESIGN_LAYOUT.pages ?? [];
      }
      const activePageId = pages.some((item) => item.id === layout.activePageId)
        ? layout.activePageId
        : pages[0]?.id;
      const activePage = pages.find((item) => item.id === activePageId) ?? pages[0];

      const webDesignNodes = (state.nodesByFormat["web-design"] ?? []).filter(
        (node) => !nodeIds.has(node.id)
      );
      const isWebDesignActive = state.canvasFormat.id === "web-design";
      return {
        nodesByFormat: { ...state.nodesByFormat, "web-design": webDesignNodes },
        ...(isWebDesignActive ? { nodes: webDesignNodes } : {}),
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
}));

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, Math.trunc(value)));
}

function normalizeCanvasPages(
  value: WorkspaceSnapshot["canvasPages"]
): Partial<Record<WorkspaceCanvasFormatId, number>> {
  if (!value || typeof value !== "object") return {};
  const result: Partial<Record<WorkspaceCanvasFormatId, number>> = {};
  for (const [key, raw] of Object.entries(value)) {
    const count = Number(raw);
    if (Number.isFinite(count) && count >= 1) {
      result[key as WorkspaceCanvasFormatId] = clamp(count, 1, MAX_CANVAS_PAGES);
    }
  }
  return result;
}

function normalizeCanvasBackgrounds(
  value: WorkspaceSnapshot["canvasBackgrounds"]
): Partial<Record<WorkspaceCanvasFormatId, string>> {
  if (!value || typeof value !== "object") return {};
  const result: Partial<Record<WorkspaceCanvasFormatId, string>> = {};
  for (const [key, raw] of Object.entries(value)) {
    if (typeof raw !== "string") continue;
    // Drop unknown ids so a removed/renamed preset falls back to the default.
    if (getCanvasBackgroundPreset(raw).id !== raw) continue;
    result[key as WorkspaceCanvasFormatId] = raw;
  }
  return result;
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
  const grid = layout.grid ?? createFluidGrid();
  const zones = Array.isArray(layout.zones) ? layout.zones : [];
  const sidebar = Array.isArray(layout.sidebar) && layout.sidebar.length
    ? normalizeSidebar(layout.sidebar, "row-1")
    : DEFAULT_WEB_DESIGN_LAYOUT.sidebar;
  const ensured = ensureWebDesignPages({
    grid,
    zones,
    sidebar,
    pages: normalizePages(layout.pages, grid, zones),
    activePageId: typeof layout.activePageId === "string" ? layout.activePageId : undefined,
    preview: Boolean(layout.preview),
  });
  // Every page — legacy fixed-pixel or already fluid — comes out as a fluid unit grid.
  const pages = (ensured.pages ?? []).map(migrateLegacyPage);
  const activePage = pages.find((page) => page.id === ensured.activePageId) ?? pages[0];
  return {
    ...ensured,
    pages,
    activePageId: activePage?.id ?? ensured.activePageId,
    grid: activePage?.grid ?? createFluidGrid(),
    zones: activePage?.zones ?? [],
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
  if (isFluidGrid(grid)) {
    return { columns: 12, rowUnit: rowUnitOf(grid), rows: [] };
  }
  // Legacy fixed-pixel grid: pass through mostly untouched; migrateLegacyPage
  // converts it to fluid units right after normalization.
  const columns = clamp(Number(grid.columns ?? 3), 1, 10);
  return {
    columns,
    columnWidths: Array.isArray(grid.columnWidths) ? grid.columnWidths : undefined,
    rows: Array.isArray(grid.rows) && grid.rows.length
      ? grid.rows.map((row, index) => ({
          id: String(row.id || `row-${index + 1}`),
          height: clamp(Number(row.height ?? 400), 40, 800),
        }))
      : [{ id: "row-1", height: 400 }],
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
    ...(Array.isArray(grid.columnWidths) ? { columnWidths: [...grid.columnWidths] } : {}),
    ...(isFluidGrid(grid) ? { rowUnit: rowUnitOf(grid) } : {}),
    rows: (grid.rows ?? []).map((row) => ({ ...row })),
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

/** Append `child` to the children of `parentId`, leaving the rest untouched. */
function appendSidebarChild(
  items: WebDesignSidebarItem[],
  parentId: string,
  child: WebDesignSidebarItem
): WebDesignSidebarItem[] {
  return items.map((item) =>
    item.id === parentId
      ? { ...item, children: [...item.children, child] }
      : { ...item, children: appendSidebarChild(item.children, parentId, child) }
  );
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
