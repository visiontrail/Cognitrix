import { describe, expect, it } from "vitest";

import { buildActiveCanvasPublishPayload } from "../../lib/workspace/publish";
import type { WebDesignLayout, WorkspaceNode } from "../../types/workspace";

const chartNode: WorkspaceNode = {
  id: "node-chart",
  type: "chartNode",
  position: { x: 10, y: 20 },
  width: 400,
  height: 280,
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

const otherChartNode: WorkspaceNode = {
  ...chartNode,
  id: "node-chart-2",
  data: {
    ...chartNode.data,
    assetId: "chart-2",
    title: "Turnover",
    spec: {
      chartType: "line",
      title: "Turnover",
      echartsOption: { dataset: { source: [{ month: "Jan", rate: 0.1 }] } },
    },
  },
};

const webDesign: WebDesignLayout = {
  grid: { columns: 2, rows: [{ id: "row-1", height: 320 }] },
  zones: [{ id: "zone-1", nodeId: "node-chart", chartId: "chart-1", column: 0, row: 0, colSpan: 1, rowSpan: 1 }],
  sidebar: [{ id: "section-1", label: "Section 1", pageId: "section-1", anchorRowId: "row-1", children: [] }],
  pages: [
    {
      id: "section-1",
      title: "Section 1",
      grid: { columns: 2, rows: [{ id: "row-1", height: 320 }] },
      zones: [{ id: "zone-1", nodeId: "node-chart", chartId: "chart-1", column: 0, row: 0, colSpan: 1, rowSpan: 1 }],
      textZones: [{ id: "text-1", column: 1, row: 0, colSpan: 1, rowSpan: 1, content: "Notes", style: "body" }],
    },
  ],
  activePageId: "section-1",
  preview: false,
};

describe("buildActiveCanvasPublishPayload", () => {
  it("serializes only chart zones referenced by the active web-design layout", () => {
    const payload = buildActiveCanvasPublishPayload({
      canvasFormat: { id: "web-design" },
      viewport: { x: 1, y: 2, zoom: 1 },
      nodes: [chartNode, otherChartNode],
      edges: [],
      webDesign,
    });

    expect(payload.canvas_format.id).toBe("web-design");
    expect(payload.web_design?.layout.pages[0].textZones?.[0].content).toBe("Notes");
    expect(payload.charts.map((chart) => chart.chart_id)).toEqual(["chart-1"]);
    expect(payload.charts[0].rows).toEqual([{ department: "HR", headcount: 4 }]);
  });

  it("serializes chart nodes from the active free-layout canvas", () => {
    const payload = buildActiveCanvasPublishPayload({
      canvasFormat: { id: "infinite" },
      viewport: { x: -100, y: -50, zoom: 0.75 },
      nodes: [chartNode, otherChartNode],
      edges: [{ id: "edge-1", source: "node-chart", target: "node-chart-2" }],
      webDesign,
    });

    expect(payload.canvas_format.id).toBe("infinite");
    expect(payload.viewport).toEqual({ x: -100, y: -50, zoom: 0.75 });
    expect(payload.edges).toHaveLength(1);
    expect(payload.web_design).toBeUndefined();
    expect(payload.charts.map((chart) => chart.chart_id)).toEqual(["chart-1", "chart-2"]);
    expect(payload.charts[1].rows).toEqual([{ month: "Jan", rate: 0.1 }]);
  });
});
