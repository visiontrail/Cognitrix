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
import { useWorkspaceStore } from "../../stores/workspace-store";
import type { WorkspaceNode } from "../../types/workspace";

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

function createDataTransfer() {
  const data = new Map<string, string>();
  return {
    dropEffect: "",
    effectAllowed: "",
    getData: vi.fn((type: string) => data.get(type) ?? ""),
    setData: vi.fn((type: string, value: string) => data.set(type, value)),
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
      webDesign: {
        grid: {
          columns: 2,
          rows: [
            { id: "row-1", height: 400 },
            { id: "row-2", height: 400 },
          ],
        },
        zones: [],
        sidebar: [{ id: "section-1", label: "Section 1", anchorRowId: "row-1", children: [] }],
        preview: false,
      },
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
      webDesign: {
        grid: {
          columns: 2,
          rows: [
            { id: "row-1", height: 400 },
            { id: "row-2", height: 400 },
          ],
        },
        zones: [],
        sidebar: [{ id: "section-1", label: "Section 1", anchorRowId: "row-1", children: [] }],
        preview: false,
      },
      hasUnsavedChanges: false,
    });
  });

  it("clamps grid zone resize to available columns and minimum span", () => {
    const store = useWorkspaceStore.getState();
    store.placeWebDesignZone("node-chart", 1, 0);
    const zoneId = useWorkspaceStore.getState().webDesign.zones[0].id;

    useWorkspaceStore.getState().resizeWebDesignZone(zoneId, 4, 0);

    const zone = useWorkspaceStore.getState().webDesign.zones[0];
    expect(zone.colSpan).toBe(1);
    expect(zone.rowSpan).toBe(1);
  });

  it("moves chart zones between empty grid cells", () => {
    const store = useWorkspaceStore.getState();
    store.placeWebDesignZone("node-chart", 0, 0);
    const zoneId = useWorkspaceStore.getState().webDesign.zones[0].id;

    useWorkspaceStore.getState().moveWebDesignZone(zoneId, 1, 1);

    const zone = useWorkspaceStore.getState().webDesign.zones[0];
    expect(zone.column).toBe(1);
    expect(zone.row).toBe(1);
  });

  it("keeps moved chart zones from overlapping another chart area", () => {
    useWorkspaceStore.setState({
      nodes: [
        chartNode,
        {
          ...chartNode,
          id: "node-chart-2",
          data: { ...chartNode.data, assetId: "chart-2", title: "Turnover" },
        },
      ],
    });

    const store = useWorkspaceStore.getState();
    store.placeWebDesignZone("node-chart", 0, 0);
    store.placeWebDesignZone("node-chart-2", 1, 0);
    const zoneId = useWorkspaceStore.getState().webDesign.zones[0].id;

    useWorkspaceStore.getState().moveWebDesignZone(zoneId, 1, 0);

    const zone = useWorkspaceStore.getState().webDesign.zones[0];
    expect(zone.column).toBe(0);
    expect(zone.row).toBe(0);
  });

  it("supports dragging a chart zone to another grid area", () => {
    useWorkspaceStore.getState().placeWebDesignZone("node-chart", 0, 0);
    renderWithProviders(<WebDesignCanvas />);

    const dataTransfer = createDataTransfer();
    const dragHandle = screen.getByText("Headcount").closest("[draggable='true']");
    expect(dragHandle).not.toBeNull();
    fireEvent.dragStart(dragHandle!, { dataTransfer });
    fireEvent.dragOver(screen.getByLabelText("Grid cell row 2 column 2"), { dataTransfer });
    fireEvent.drop(screen.getByLabelText("Grid cell row 2 column 2"), { dataTransfer });

    const zone = useWorkspaceStore.getState().webDesign.zones[0];
    expect(zone.column).toBe(1);
    expect(zone.row).toBe(1);
  });

  it("renders a control to reduce a chart zone row span", async () => {
    useWorkspaceStore.getState().placeWebDesignZone("node-chart", 0, 0);
    const zoneId = useWorkspaceStore.getState().webDesign.zones[0].id;
    useWorkspaceStore.getState().resizeWebDesignZone(zoneId, 1, 2);
    renderWithProviders(<WebDesignCanvas />);

    await userEvent.click(screen.getByRole("button", { name: "Decrease row span" }));

    expect(useWorkspaceStore.getState().webDesign.zones[0].rowSpan).toBe(1);
  });

  it("copies a Web Page Design chart zone to the clipboard as a PNG", async () => {
    useWorkspaceStore.getState().placeWebDesignZone("node-chart", 0, 0);
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

  it("does not render the old unplaced charts tray", () => {
    renderWithProviders(<WebDesignCanvas />);

    expect(screen.queryByText("Unplaced charts")).not.toBeInTheDocument();
    expect(screen.queryByText("All charts are placed.")).not.toBeInTheDocument();
  });

  it("adds reusable chart copies directly to the Web Page Design grid", () => {
    useWorkspaceStore.setState({ nodes: [], webDesign: { ...useWorkspaceStore.getState().webDesign, zones: [] } });

    useWorkspaceStore.getState().addNodeToWebDesign({ ...chartNode, id: "node-chart-a" });
    useWorkspaceStore.getState().addNodeToWebDesign({ ...chartNode, id: "node-chart-b" });

    const state = useWorkspaceStore.getState();
    expect(state.canvasFormat.id).toBe("web-design");
    expect(state.nodes.map((node) => node.id)).toEqual(["node-chart-a", "node-chart-b"]);
    expect(state.webDesign.zones).toHaveLength(2);
    expect(state.webDesign.zones.map((zone) => zone.chartId)).toEqual(["chart-1", "chart-1"]);
    expect(state.webDesign.zones.map((zone) => [zone.column, zone.row])).toEqual([
      [0, 0],
      [1, 0],
    ]);
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
      webDesign: {
        ...useWorkspaceStore.getState().webDesign,
        zones: [
          {
            id: "zone-1",
            nodeId: "node-chart",
            chartId: "chart-1",
            column: 0,
            row: 0,
            colSpan: 1,
            rowSpan: 1,
          },
        ],
      },
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
      webDesign: {
        ...useWorkspaceStore.getState().webDesign,
        zones: [
          {
            id: "zone-1",
            nodeId: "node-chart",
            chartId: "chart-1",
            column: 0,
            row: 0,
            colSpan: 1,
            rowSpan: 1,
          },
        ],
      },
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
