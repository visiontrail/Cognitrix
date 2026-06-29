import { describe, expect, it } from "vitest";

import {
  buildActiveCanvasPublishPayload,
  buildWorkspaceSnapshotFromPublishedVersion,
} from "../../lib/workspace/publish";
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

  it("carries the fixed canvas page count into the publish payload", () => {
    const payload = buildActiveCanvasPublishPayload({
      canvasFormat: { id: "a4-portrait" },
      pageCount: 2,
      viewport: { x: 0, y: 0, zoom: 1 },
      nodes: [chartNode],
      edges: [],
      webDesign,
    });

    expect(payload.page_count).toBe(2);
    expect(payload.nodes[0]?.position).toEqual({ x: 10, y: 20 });
  });

  it("flattens grouped free-layout child nodes to absolute positions for publishing", () => {
    const groupNode: WorkspaceNode = {
      id: "group-1",
      type: "sectionNode",
      position: { x: 70, y: 80 },
      width: 500,
      height: 320,
      data: {
        type: "section",
        title: "Group",
        width: 500,
        height: 320,
      },
    };
    const groupedChartNode: WorkspaceNode = {
      ...chartNode,
      parentId: "group-1",
      extent: "parent",
      expandParent: true,
      position: { x: 30, y: 40 },
    };

    const payload = buildActiveCanvasPublishPayload({
      canvasFormat: { id: "infinite" },
      viewport: { x: 0, y: 0, zoom: 1 },
      nodes: [groupNode, groupedChartNode],
      edges: [],
      webDesign,
    });

    expect(payload.nodes.find((node) => node.id === "node-chart")).toMatchObject({
      parentId: undefined,
      extent: undefined,
      expandParent: undefined,
      position: { x: 100, y: 120 },
    });
    expect(payload.nodes.find((node) => node.id === "group-1")?.position).toEqual({ x: 70, y: 80 });
  });

  it("restores fixed canvas page counts from a published version", () => {
    const snapshot = buildWorkspaceSnapshotFromPublishedVersion({
      workspaceId: "workspace-1",
      published: {
        page_id: "page-1",
        version: 1,
        published_at: "2026-06-26T00:00:00+00:00",
        published_by: "alice",
        canvas_format_id: "a4-portrait",
        canvas_kind: "fixed_size",
        manifest: {
          schema_version: 2,
          canvas: {
            format_id: "a4-portrait",
            kind: "fixed_size",
            viewport: { x: 0, y: 0, zoom: 1 },
            page: { preset_id: "a4-portrait", width: 794, height: 1123, count: 2, gap: 48 },
          },
          content: {
            nodes: [
              chartNode,
              {
                ...otherChartNode,
                id: "page-2-chart",
                position: { x: 20, y: 1200 },
              },
            ],
            edges: [],
          },
          layout: { grid: { columns: 1, rows: [] }, zones: [] },
          sidebar: [],
          charts: [],
        },
        charts: [],
      },
      baseSnapshot: {
        workspaceId: "workspace-1",
        nodesByFormat: {},
        edgesByFormat: {},
        canvasPages: { "a4-portrait": 1 },
        viewport: { x: 0, y: 0, zoom: 1 },
        canvasFormat: { id: "a4-portrait" },
        webDesign,
      },
    });

    expect(snapshot.canvasFormat?.id).toBe("a4-portrait");
    expect(snapshot.canvasPages?.["a4-portrait"]).toBe(2);
    expect(snapshot.nodesByFormat?.["a4-portrait"]?.map((node) => node.id)).toEqual([
      "node-chart",
      "page-2-chart",
    ]);
  });
});
