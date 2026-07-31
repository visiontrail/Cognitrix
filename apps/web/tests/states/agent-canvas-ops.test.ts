import { beforeEach, describe, expect, it } from "vitest";

import type { AgentCanvasWireOp } from "../../lib/chat/agent-canvas";
import { applyAgentCanvasWireOp, type AgentCanvasOpDeps } from "../../lib/workspace/agent-canvas-ops";
import { AGENT_ERROR_CHART_TYPE } from "../../lib/workspace/agent-canvas-layout";
import { pageToLayoutItems } from "../../lib/workspace/web-design-layout";
import { useAssetStore } from "../../stores/asset-store";
import { useUIStore } from "../../stores/ui-store";
import { useWorkspaceStore } from "../../stores/workspace-store";
import type { ChartAsset } from "../../types/chart";
import type { WebDesignPage } from "../../types/workspace";

const RUN_ID = "acr-test1234";
const PAGE_ID = `agent-${RUN_ID}`;

const deps: AgentCanvasOpDeps = {
  toAsset: (_rawSpec, meta): ChartAsset => ({
    id: meta.assetId,
    title: meta.title,
    chartType: "bar",
    spec: { chartType: "bar", title: meta.title, echartsOption: {} },
    sourceMeta: { sessionId: "s1", messageId: "m1", prompt: meta.title },
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
  }),
};

function wireOp(
  seq: number,
  opType: AgentCanvasWireOp["opType"],
  payload: Record<string, unknown>
): AgentCanvasWireOp {
  return { runId: RUN_ID, seq, opType, pageId: PAGE_ID, payload };
}

function blockId(seq: number): string {
  return `agent-block-${RUN_ID}-${seq}`;
}

const RUN_OPS: AgentCanvasWireOp[] = [
  wireOp(1, "create_page", { page_id: PAGE_ID, title: "销售概览" }),
  wireOp(2, "add_section", { block_id: blockId(2), title: "概览" }),
  wireOp(3, "place_chart", {
    block_id: blockId(3),
    title: "总人数",
    size_preset: "kpi",
    asset_id: "asset-1",
    spec: {},
  }),
  wireOp(4, "place_chart", {
    block_id: blockId(4),
    title: "部门人数",
    size_preset: "half",
    asset_id: "asset-2",
    spec: {},
  }),
  wireOp(5, "add_text_block", { block_id: blockId(5), style: "body", content: "说明" }),
];

const SECOND_PAGE_ID = `agent-${RUN_ID}-p4`;

function wireOpOnPage(
  seq: number,
  opType: AgentCanvasWireOp["opType"],
  pageId: string,
  payload: Record<string, unknown>
): AgentCanvasWireOp {
  return { runId: RUN_ID, seq, opType, pageId, payload };
}

/** A run that opens a second page mid-flight (one page per department). */
const MULTI_PAGE_OPS: AgentCanvasWireOp[] = [
  wireOp(1, "create_page", { page_id: PAGE_ID, parent_page_id: "", title: "总览" }),
  wireOp(2, "add_section", { block_id: blockId(2), title: "整体", level: 1 }),
  wireOp(3, "place_chart", {
    block_id: blockId(3),
    title: "总人数",
    size_preset: "kpi",
    asset_id: "asset-total",
    spec: {},
  }),
  wireOpOnPage(4, "create_page", SECOND_PAGE_ID, {
    page_id: SECOND_PAGE_ID,
    parent_page_id: PAGE_ID,
    title: "HR",
  }),
  wireOpOnPage(5, "add_section", SECOND_PAGE_ID, {
    block_id: blockId(5),
    title: "人员结构",
    level: 2,
  }),
  wireOpOnPage(6, "place_chart", SECOND_PAGE_ID, {
    block_id: blockId(6),
    title: "HR 人数",
    size_preset: "half",
    asset_id: "asset-hr",
    spec: {},
  }),
];

function runPage(): WebDesignPage {
  const page = (useWorkspaceStore.getState().webDesign.pages ?? []).find(
    (item) => item.id === PAGE_ID
  );
  if (!page) throw new Error("run page missing");
  return page;
}

function layoutFingerprint(): string {
  return pageToLayoutItems(runPage())
    .map((item) => `${item.id}:${item.kind}:${item.x},${item.y},${item.w},${item.h}`)
    .sort()
    .join("|");
}

function resetStores() {
  useWorkspaceStore.setState({
    activeWorkspaceId: "ws-1",
    nodes: [],
    edges: [],
    nodesByFormat: {},
    edgesByFormat: {},
    canvasFormat: { id: "web-design" },
    webDesign: {
      grid: { columns: 12, rowUnit: 72, rows: [] },
      zones: [],
      sidebar: [
        { id: "section-1", label: "Section 1", pageId: "section-1", anchorRowId: "row-1", children: [] },
      ],
      pages: [
        { id: "section-1", title: "Section 1", grid: { columns: 12, rowUnit: 72, rows: [] }, zones: [], textZones: [] },
      ],
      activePageId: "section-1",
      preview: false,
    },
    hasUnsavedChanges: false,
  });
  useAssetStore.setState({ assets: [] });
  useUIStore.setState({ activeAgentRun: null });
}

describe("agent canvas op application", () => {
  beforeEach(resetStores);

  it("applies a run's ops deterministically (same ops → same layout)", () => {
    for (const op of RUN_OPS) {
      expect(applyAgentCanvasWireOp(op, deps)).toBe(true);
    }
    const first = layoutFingerprint();
    expect(first).toContain(blockId(3));

    resetStores();
    for (const op of RUN_OPS) {
      applyAgentCanvasWireOp(op, deps);
    }
    expect(layoutFingerprint()).toBe(first);
  });

  it("replays idempotently: duplicate ops never duplicate blocks", () => {
    for (const op of RUN_OPS) {
      applyAgentCanvasWireOp(op, deps);
    }
    const fingerprint = layoutFingerprint();
    const zoneCount = runPage().zones.length;

    for (const op of RUN_OPS) {
      expect(applyAgentCanvasWireOp(op, deps)).toBe(false);
    }
    expect(runPage().zones.length).toBe(zoneCount);
    expect(layoutFingerprint()).toBe(fingerprint);
    // The sidebar item for the run page is created exactly once.
    const sidebarMatches = useWorkspaceStore
      .getState()
      .webDesign.sidebar.filter((item) => item.id === PAGE_ID);
    expect(sidebarMatches).toHaveLength(1);
  });

  it("archives placed charts into the asset library", () => {
    for (const op of RUN_OPS) {
      applyAgentCanvasWireOp(op, deps);
    }
    const assetIds = useAssetStore.getState().assets.map((asset) => asset.id);
    expect(assetIds).toContain("asset-1");
    expect(assetIds).toContain("asset-2");
  });

  it("replaces an error placeholder in place on successful retry", () => {
    applyAgentCanvasWireOp(RUN_OPS[0], deps);
    applyAgentCanvasWireOp(
      wireOp(2, "error_placeholder", {
        block_id: blockId(2),
        title: "坏图表",
        size_preset: "half",
        error: { code: "QUERY_EXECUTION_FAILED", message: "boom" },
      }),
      deps
    );
    const placeholderZone = runPage().zones.find((zone) => zone.id === blockId(2));
    expect(placeholderZone).toBeDefined();
    const placeholderRect = pageToLayoutItems(runPage()).find((item) => item.id === blockId(2));

    // Retry success: a place_chart op reusing the same block id swaps the node.
    const applied = applyAgentCanvasWireOp(
      wireOp(6, "place_chart", {
        block_id: blockId(2),
        title: "修复后的图表",
        size_preset: "half",
        asset_id: "asset-retry",
        spec: {},
        replaces_block_id: blockId(2),
      }),
      deps
    );
    expect(applied).toBe(true);

    const zone = runPage().zones.find((item) => item.id === blockId(2));
    expect(zone?.chartId).toBe("asset-retry");
    const rect = pageToLayoutItems(runPage()).find((item) => item.id === blockId(2));
    expect(rect).toEqual(placeholderRect);
    const node = (useWorkspaceStore.getState().nodesByFormat["web-design"] ?? []).find(
      (item) => item.id === zone?.nodeId
    );
    expect(node?.data.type).toBe("chart");
    expect((node?.data as { chartType: string }).chartType).not.toBe(AGENT_ERROR_CHART_TYPE);
  });

  it("undoAgentRun removes only the run page and its nodes", () => {
    for (const op of RUN_OPS) {
      applyAgentCanvasWireOp(op, deps);
    }
    expect((useWorkspaceStore.getState().webDesign.pages ?? []).some((p) => p.id === PAGE_ID)).toBe(true);

    useWorkspaceStore.getState().undoAgentRun(PAGE_ID);

    const state = useWorkspaceStore.getState();
    expect((state.webDesign.pages ?? []).some((p) => p.id === PAGE_ID)).toBe(false);
    expect(state.webDesign.sidebar.some((item) => item.id === PAGE_ID)).toBe(false);
    // The pre-existing page is untouched.
    expect((state.webDesign.pages ?? []).some((p) => p.id === "section-1")).toBe(true);
    // Run chart nodes are gone from the web-design bucket…
    expect(state.nodesByFormat["web-design"] ?? []).toHaveLength(0);
    // …but the chart assets remain in the library.
    const assetIds = useAssetStore.getState().assets.map((asset) => asset.id);
    expect(assetIds).toContain("asset-1");
    expect(assetIds).toContain("asset-2");
  });

  it("creates one nested sidebar page per add_page op", () => {
    for (const op of MULTI_PAGE_OPS) {
      expect(applyAgentCanvasWireOp(op, deps)).toBe(true);
    }
    const layout = useWorkspaceStore.getState().webDesign;
    const pageIds = (layout.pages ?? []).map((page) => page.id);
    expect(pageIds).toContain(PAGE_ID);
    expect(pageIds).toContain(SECOND_PAGE_ID);

    // The run's root page is a top-level sidebar entry; later pages nest under it.
    const rootItem = layout.sidebar.find((item) => item.id === PAGE_ID);
    expect(rootItem).toBeDefined();
    expect(rootItem?.children.map((child) => child.id)).toEqual([SECOND_PAGE_ID]);
    expect(rootItem?.children[0]?.label).toBe("HR");
    expect(layout.sidebar.some((item) => item.id === SECOND_PAGE_ID)).toBe(false);
    // The canvas follows the agent onto the page it is filling.
    expect(layout.activePageId).toBe(SECOND_PAGE_ID);

    // Blocks land on the page their op names, not on the run root.
    const secondPage = (layout.pages ?? []).find((page) => page.id === SECOND_PAGE_ID);
    expect(secondPage?.zones.map((zone) => zone.id)).toEqual([blockId(6)]);
    expect((secondPage?.textZones ?? []).map((zone) => zone.id)).toEqual([blockId(5)]);
    expect(runPage().zones.map((zone) => zone.id)).toEqual([blockId(3)]);
  });

  it("renders a level-2 section as a sub-heading", () => {
    for (const op of MULTI_PAGE_OPS) {
      applyAgentCanvasWireOp(op, deps);
    }
    const rootSection = (runPage().textZones ?? []).find((zone) => zone.id === blockId(2));
    expect(rootSection?.style).toBe("title");
    const secondPage = (useWorkspaceStore.getState().webDesign.pages ?? []).find(
      (page) => page.id === SECOND_PAGE_ID
    );
    const subSection = (secondPage?.textZones ?? []).find((zone) => zone.id === blockId(5));
    expect(subSection?.style).toBe("subtitle");
  });

  it("undoAgentRun removes every page of a multi-page run", () => {
    for (const op of MULTI_PAGE_OPS) {
      applyAgentCanvasWireOp(op, deps);
    }
    useWorkspaceStore.getState().undoAgentRun(PAGE_ID);

    const state = useWorkspaceStore.getState();
    const pageIds = (state.webDesign.pages ?? []).map((page) => page.id);
    expect(pageIds).not.toContain(PAGE_ID);
    expect(pageIds).not.toContain(SECOND_PAGE_ID);
    // Nodes from BOTH pages are gone; assets stay in the library.
    expect(state.nodesByFormat["web-design"] ?? []).toHaveLength(0);
    expect(useAssetStore.getState().assets.map((asset) => asset.id)).toContain("asset-hr");
  });

  it("soft lock is set per run and cleared on terminal status", () => {
    useUIStore.getState().setActiveAgentRun({ runId: RUN_ID, pageId: PAGE_ID, workspaceId: "ws-1" });
    expect(useUIStore.getState().activeAgentRun?.runId).toBe(RUN_ID);

    // Clearing a different run leaves the lock alone.
    useUIStore.getState().clearAgentRun("acr-other");
    expect(useUIStore.getState().activeAgentRun?.runId).toBe(RUN_ID);

    useUIStore.getState().clearAgentRun(RUN_ID);
    expect(useUIStore.getState().activeAgentRun).toBeNull();
  });
});
