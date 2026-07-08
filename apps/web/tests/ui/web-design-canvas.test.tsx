import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "../../components/ui/tooltip";
import { WebDesignCanvas } from "../../components/workspace/web-design-canvas";
import { WorkspaceToolbar } from "../../components/workspace/workspace-toolbar";
import { clearInMemoryToken, setInMemoryToken } from "../../lib/auth/session";
import { DEFAULT_CANVAS_FORMAT } from "../../lib/workspace/canvas-formats";
import { CHART_DEFAULT_H, CHART_DEFAULT_W, createFluidGrid } from "../../lib/workspace/web-design-layout";
import { useWorkspaceStore } from "../../stores/workspace-store";
import type { WebDesignLayout, WorkspaceNode } from "../../types/workspace";

const toBlobMock = vi.fn();
const clipboardWriteMock = vi.fn();

vi.mock("html-to-image", () => ({
  toBlob: (...args: unknown[]) => toBlobMock(...args),
}));

vi.mock("@/components/charts/chart-preview", () => ({
  ChartPreview: () => <div data-testid="chart-preview" />,
}));

const chartNode: WorkspaceNode = {
  id: "node-chart",
  type: "chartNode",
  position: { x: 0, y: 0 },
  data: {
    type: "chart",
    assetId: "chart-1",
    title: "Headcount",
    chartType: "bar",
    width: 400,
    height: 280,
    spec: {
      chartType: "bar",
      title: "Headcount",
      echartsOption: { __rows__: [{ department: "HR", headcount: 4 }] },
    },
  },
};

function webDesignWithZone(zone: WebDesignLayout["zones"][number]): WebDesignLayout {
  const layout = emptyWebDesign();
  return {
    ...layout,
    zones: [zone],
    pages: layout.pages?.map((page) => ({ ...page, zones: [zone] })),
  };
}

function emptyWebDesign(): WebDesignLayout {
  return {
    grid: createFluidGrid(),
    zones: [],
    sidebar: [{ id: "section-1", label: "Section 1", pageId: "section-1", anchorRowId: "row-1", children: [] }],
    pages: [{ id: "section-1", title: "Section 1", grid: createFluidGrid(), zones: [], textZones: [] }],
    activePageId: "section-1",
    preview: false,
  };
}

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>{ui}</TooltipProvider>
    </QueryClientProvider>
  );
}

describe("WebDesignCanvas state", () => {
  beforeEach(() => {
    setInMemoryToken("test-token", Math.floor(Date.now() / 1000) + 3600);
    toBlobMock.mockResolvedValue(new Blob(["png"], { type: "image/png" }));
    clipboardWriteMock.mockResolvedValue(undefined);
    class ClipboardItemMock {
      constructor(public readonly items: Record<string, Blob>) {}
    }
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        write: clipboardWriteMock,
      },
    });
    Object.defineProperty(window, "ClipboardItem", {
      configurable: true,
      value: ClipboardItemMock,
    });
    Object.defineProperty(globalThis, "ClipboardItem", {
      configurable: true,
      value: ClipboardItemMock,
    });
    useWorkspaceStore.setState({
      activeWorkspaceId: "ws-test",
      nodes: [chartNode],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      canvasFormat: DEFAULT_CANVAS_FORMAT,
      webDesign: emptyWebDesign(),
      hasUnsavedChanges: false,
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    clearInMemoryToken();
    useWorkspaceStore.setState({
      workspaces: [],
      activeWorkspaceId: null,
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      canvasFormat: DEFAULT_CANVAS_FORMAT,
      webDesign: emptyWebDesign(),
      hasUnsavedChanges: false,
    });
  });

  it("adds charts on the fluid grid side by side, then wraps to the next band", () => {
    useWorkspaceStore.setState({ nodes: [] });

    useWorkspaceStore.getState().addNodeToWebDesign({ ...chartNode, id: "node-chart-a" });
    useWorkspaceStore.getState().addNodeToWebDesign({ ...chartNode, id: "node-chart-b" });
    useWorkspaceStore.getState().addNodeToWebDesign({ ...chartNode, id: "node-chart-c" });

    const state = useWorkspaceStore.getState();
    expect(state.canvasFormat.id).toBe("web-design");
    const zones = state.webDesign.zones;
    expect(zones).toHaveLength(3);
    expect(zones.map((zone) => [zone.column, zone.row])).toEqual([
      [0, 0],
      [CHART_DEFAULT_W, 0],
      [0, CHART_DEFAULT_H],
    ]);
    expect(zones.every((zone) => zone.colSpan === CHART_DEFAULT_W && zone.rowSpan === CHART_DEFAULT_H)).toBe(true);
  });

  it("pushes an occupied block down when another block moves onto it", () => {
    useWorkspaceStore.setState({ nodes: [] });
    useWorkspaceStore.getState().addNodeToWebDesign({ ...chartNode, id: "node-chart-a" });
    useWorkspaceStore.getState().addNodeToWebDesign({ ...chartNode, id: "node-chart-b" });
    const [zoneA, zoneB] = useWorkspaceStore.getState().webDesign.zones;

    useWorkspaceStore.getState().moveWebDesignBlock(zoneB.id, 0, 0);

    const zones = useWorkspaceStore.getState().webDesign.zones;
    expect(zones.find((zone) => zone.id === zoneB.id)).toMatchObject({ column: 0, row: 0 });
    expect(zones.find((zone) => zone.id === zoneA.id)).toMatchObject({ column: 0, row: CHART_DEFAULT_H });
  });

  it("clamps block resize to grid bounds and chart minimums", () => {
    useWorkspaceStore.setState({ nodes: [] });
    useWorkspaceStore.getState().addNodeToWebDesign({ ...chartNode, id: "node-chart-a" });
    const zoneId = useWorkspaceStore.getState().webDesign.zones[0].id;

    useWorkspaceStore.getState().resizeWebDesignBlock(zoneId, 40, 1);
    let zone = useWorkspaceStore.getState().webDesign.zones[0];
    expect(zone.colSpan).toBe(12);
    expect(zone.rowSpan).toBe(3);

    useWorkspaceStore.getState().resizeWebDesignBlock(zoneId, 1, 1);
    zone = useWorkspaceStore.getState().webDesign.zones[0];
    expect(zone.colSpan).toBe(3);
    expect(zone.rowSpan).toBe(3);
  });

  it("closes gaps when a block is removed", () => {
    useWorkspaceStore.setState({ nodes: [] });
    useWorkspaceStore.getState().addNodeToWebDesign({ ...chartNode, id: "node-chart-a" });
    useWorkspaceStore.getState().addNodeToWebDesign({ ...chartNode, id: "node-chart-b" });
    useWorkspaceStore.getState().addNodeToWebDesign({ ...chartNode, id: "node-chart-c" });
    const [zoneA, , zoneC] = useWorkspaceStore.getState().webDesign.zones;

    useWorkspaceStore.getState().removeWebDesignZone(zoneA.id);

    const zones = useWorkspaceStore.getState().webDesign.zones;
    expect(zones).toHaveLength(2);
    expect(zones.find((zone) => zone.id === zoneC.id)).toMatchObject({ column: 0, row: 0 });
  });

  it("migrates legacy fixed-pixel snapshots to the fluid grid on load", () => {
    useWorkspaceStore.getState().loadSnapshot({
      workspaceId: "ws-test",
      viewport: { x: 0, y: 0, zoom: 1 },
      canvasFormat: { id: "web-design" },
      webDesign: {
        grid: {
          columns: 2,
          rows: [
            { id: "row-1", height: 400 },
            { id: "row-2", height: 400 },
          ],
        },
        zones: [
          { id: "z1", nodeId: "node-chart", chartId: "chart-1", column: 1, row: 0, colSpan: 1, rowSpan: 1 },
        ],
        sidebar: [{ id: "section-1", label: "Section 1", anchorRowId: "row-1", children: [] }],
        preview: false,
      },
    });

    const layout = useWorkspaceStore.getState().webDesign;
    expect(layout.grid.columns).toBe(12);
    expect(layout.grid.rowUnit).toBeGreaterThan(0);
    const zone = layout.zones[0];
    expect(zone.column).toBe(6);
    expect(zone.colSpan).toBe(6);
    expect(zone.rowSpan).toBeGreaterThanOrEqual(3);
  });

  it("adds a full-width title text block and a half-width annotation", () => {
    const store = useWorkspaceStore.getState();
    store.addWebDesignTextZone("title");
    useWorkspaceStore.getState().addWebDesignTextZone("body");

    const textZones = useWorkspaceStore.getState().webDesign.pages?.[0].textZones ?? [];
    expect(textZones).toHaveLength(2);
    expect(textZones[0]).toMatchObject({ column: 0, row: 0, colSpan: 12 });
    expect(textZones[1]).toMatchObject({ column: 0, row: 1, colSpan: 6 });
  });

  it("moves a focused chart block with arrow keys", () => {
    useWorkspaceStore.setState({ nodes: [] });
    useWorkspaceStore.getState().addNodeToWebDesign({ ...chartNode, id: "node-chart-a" });
    renderWithProviders(<WebDesignCanvas />);

    const block = screen.getByLabelText("Chart zone Headcount");
    block.focus();
    fireEvent.keyDown(block, { key: "ArrowRight" });

    expect(useWorkspaceStore.getState().webDesign.zones[0].column).toBe(1);

    fireEvent.keyDown(block, { key: "ArrowDown", shiftKey: true });
    expect(useWorkspaceStore.getState().webDesign.zones[0].rowSpan).toBe(CHART_DEFAULT_H + 1);
  });

  it("removes a focused block with the Delete key", () => {
    useWorkspaceStore.setState({ nodes: [] });
    useWorkspaceStore.getState().addNodeToWebDesign({ ...chartNode, id: "node-chart-a" });
    renderWithProviders(<WebDesignCanvas />);

    const block = screen.getByLabelText("Chart zone Headcount");
    block.focus();
    fireEvent.keyDown(block, { key: "Delete" });

    expect(useWorkspaceStore.getState().webDesign.zones).toHaveLength(0);
  });

  it("shows an empty-state hint when the page has no blocks", () => {
    renderWithProviders(<WebDesignCanvas />);

    expect(screen.getByText("This page is empty")).toBeInTheDocument();
  });

  it("does not render legacy row/column management controls", () => {
    renderWithProviders(<WebDesignCanvas />);

    expect(screen.queryByText(/columns$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/rows$/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Resize column/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Grid cell/)).not.toBeInTheDocument();
  });

  it("copies a Web Page Design chart block to the clipboard as a PNG", async () => {
    useWorkspaceStore.setState({ nodes: [] });
    useWorkspaceStore.getState().addNodeToWebDesign({ ...chartNode, id: "node-chart" });
    renderWithProviders(<WebDesignCanvas />);

    await userEvent.click(screen.getByRole("button", { name: "Copy as PNG image" }));

    await waitFor(() => {
      expect(toBlobMock).toHaveBeenCalledWith(
        expect.any(HTMLElement),
        expect.objectContaining({
          backgroundColor: "#f5f0e8",
          pixelRatio: 2,
        })
      );
      expect(clipboardWriteMock).toHaveBeenCalledTimes(1);
    });
  });

  it("keeps sidebar nesting at two levels", () => {
    const store = useWorkspaceStore.getState();
    store.addWebDesignSidebarItem("section-1");
    const childId = useWorkspaceStore.getState().webDesign.sidebar[0].children[0].id;

    useWorkspaceStore.getState().addWebDesignSidebarItem(childId);

    const firstSection = useWorkspaceStore.getState().webDesign.sidebar[0];
    expect(firstSection.children).toHaveLength(1);
    expect(firstSection.children[0].children).toHaveLength(0);
  });

  it("allows publishing charts whose data is stored in an ECharts dataset", () => {
    useWorkspaceStore.setState({
      nodes: [
        {
          ...chartNode,
          data: {
            ...chartNode.data,
            spec: {
              ...chartNode.data.spec,
              echartsOption: {
                dataset: {
                  source: [
                    ["department", "headcount"],
                    ["HR", 4],
                  ],
                },
                xAxis: { type: "category" },
                yAxis: { type: "value" },
                series: [{ type: "bar" }],
              },
            },
          },
        },
      ],
      webDesign: webDesignWithZone({
        id: "zone-1",
        nodeId: "node-chart",
        chartId: "chart-1",
        column: 0,
        row: 0,
        colSpan: 6,
        rowSpan: 5,
      }),
    });

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ is_active: false }), { status: 200 })))
    );
    useWorkspaceStore.setState({
      workspaces: [
        {
          id: "ws-test",
          title: "Canvas",
          createdAt: "2026-04-14T00:00:00.000Z",
          updatedAt: "2026-04-14T00:00:00.000Z",
          nodeCount: 1,
          role: "owner",
        },
      ],
      canvasFormat: { id: "web-design" },
    });

    renderWithProviders(<WorkspaceToolbar />);

    expect(screen.getByRole("button", { name: /Publish/i })).toBeEnabled();
  });

  it("allows publishing existing ECharts charts that only have render series data", () => {
    useWorkspaceStore.setState({
      nodes: [
        {
          ...chartNode,
          data: {
            ...chartNode.data,
            spec: {
              ...chartNode.data.spec,
              echartsOption: {
                xAxis: { type: "category", data: ["HR"] },
                yAxis: { type: "value" },
                series: [{ name: "headcount", type: "bar", data: [4] }],
              },
            },
          },
        },
      ],
      webDesign: webDesignWithZone({
        id: "zone-1",
        nodeId: "node-chart",
        chartId: "chart-1",
        column: 0,
        row: 0,
        colSpan: 6,
        rowSpan: 5,
      }),
    });

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ is_active: false }), { status: 200 })))
    );
    useWorkspaceStore.setState({
      workspaces: [
        {
          id: "ws-test",
          title: "Canvas",
          createdAt: "2026-04-14T00:00:00.000Z",
          updatedAt: "2026-04-14T00:00:00.000Z",
          nodeCount: 1,
          role: "owner",
        },
      ],
      canvasFormat: { id: "web-design" },
    });

    renderWithProviders(<WorkspaceToolbar />);

    expect(screen.getByRole("button", { name: /Publish/i })).toBeEnabled();
  });

  it("switches to Web Page Design from the mode picker", async () => {
    useWorkspaceStore.setState({
      workspaces: [
        {
          id: "ws-test",
          title: "Original Canvas",
          createdAt: "2026-04-14T00:00:00.000Z",
          updatedAt: "2026-04-14T00:00:00.000Z",
          nodeCount: 1,
        },
      ],
    });

    renderWithProviders(<WorkspaceToolbar />);

    await userEvent.click(screen.getByRole("button", { name: "Canvas size" }));
    await userEvent.click(screen.getByText("Web Page Design"));

    await waitFor(() => {
      expect(useWorkspaceStore.getState().canvasFormat.id).toBe("web-design");
      expect(useWorkspaceStore.getState().hasUnsavedChanges).toBe(true);
    });
  });
});
