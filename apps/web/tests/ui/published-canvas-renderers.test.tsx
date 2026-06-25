import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PublishedFixedCanvas, PublishedFreeCanvas } from "../../components/public/published-canvas-renderers";
import type { PublishedManifest } from "../../lib/public/api";

const publicApiMock = vi.hoisted(() => ({
  fetchPublicChartData: vi.fn(),
}));

vi.mock("@/components/charts/chart-preview", () => ({
  ChartPreview: ({ spec }: { spec: { title?: string } }) => (
    <div data-testid="chart-preview">{spec.title}</div>
  ),
}));

vi.mock("@/lib/public/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/public/api")>();
  return {
    ...actual,
    fetchPublicChartData: publicApiMock.fetchPublicChartData,
  };
});

const baseManifest = {
  schema_version: 2,
  layout: { grid: { columns: 1, rows: [] }, zones: [] },
  sidebar: [],
  charts: [],
} satisfies PublishedManifest;

describe("published canvas renderers", () => {
  beforeEach(() => {
    publicApiMock.fetchPublicChartData.mockResolvedValue({
      chart_id: "chart-1",
      spec: { chartType: "bar", title: "Published Headcount" },
      rows: [{ department: "HR", headcount: 4 }],
      data_truncated: false,
    });
  });

  it("renders free-layout text and chart nodes without editor chrome", async () => {
    const manifest: PublishedManifest = {
      ...baseManifest,
      canvas: {
        format_id: "infinite",
        kind: "free_layout",
        bounds: { x: 0, y: 0, width: 640, height: 420 },
      },
      content: {
        nodes: [
          {
            id: "text-1",
            position: { x: 20, y: 24 },
            width: 260,
            height: 80,
            data: { type: "text", content: "Quarterly narrative", fontSize: 20 },
          },
          {
            id: "chart-node",
            position: { x: 320, y: 40 },
            width: 320,
            height: 220,
            data: { type: "chart", assetId: "chart-1", title: "Headcount", chartType: "bar" },
          },
        ],
        edges: [],
      },
    };

    render(<PublishedFreeCanvas token="pub-token" manifest={manifest} />);

    expect(screen.getByText("Quarterly narrative")).toBeInTheDocument();
    expect(screen.getByText("Headcount")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("chart-preview")).toHaveTextContent("Published Headcount"));
    expect(publicApiMock.fetchPublicChartData).toHaveBeenCalledWith("pub-token", "chart-1");
    expect(screen.queryByText("Canvas size")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Zoom in")).toBeInTheDocument();
    expect(screen.getByLabelText("Zoom out")).toBeInTheDocument();
  });

  it("supports zooming and dragging the published free-layout canvas", () => {
    const manifest: PublishedManifest = {
      ...baseManifest,
      canvas: {
        format_id: "infinite",
        kind: "free_layout",
        bounds: { x: 0, y: 0, width: 640, height: 420 },
      },
      content: {
        nodes: [
          {
            id: "text-1",
            position: { x: 20, y: 24 },
            width: 260,
            height: 80,
            data: { type: "text", content: "Movable public canvas", fontSize: 20 },
          },
        ],
        edges: [],
      },
    };

    render(<PublishedFreeCanvas token="pub-token" manifest={manifest} />);

    const viewport = screen.getByTestId("published-free-canvas-viewport");
    const stage = screen.getByTestId("published-free-canvas-stage");

    expect(stage).toHaveStyle({ transform: "matrix(1, 0, 0, 1, 0, 0)" });

    fireEvent.wheel(viewport, { deltaY: -100, clientX: 100, clientY: 100 });
    expect(stage).toHaveStyle({ transform: "matrix(1.1, 0, 0, 1.1, -10, -10)" });
    expect(screen.getByLabelText("Zoom level")).toHaveTextContent("110%");

    fireEvent.click(screen.getByLabelText("Reset view"));
    expect(stage).toHaveStyle({ transform: "matrix(1, 0, 0, 1, 0, 0)" });

    fireEvent.pointerDown(viewport, { button: 0, pointerId: 1, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(viewport, { pointerId: 1, clientX: 140, clientY: 125 });
    fireEvent.pointerUp(viewport, { pointerId: 1, clientX: 140, clientY: 125 });
    expect(stage).toHaveStyle({ transform: "matrix(1, 0, 0, 1, 40, 25)" });
  });

  it("renders fixed-size pages at the published page dimensions", () => {
    const manifest: PublishedManifest = {
      ...baseManifest,
      canvas: {
        format_id: "a4-portrait",
        kind: "fixed_size",
        page: { preset_id: "a4-portrait", width: 794, height: 1123 },
      },
      content: {
        nodes: [
          {
            id: "sticky-1",
            position: { x: 48, y: 64 },
            width: 180,
            height: 120,
            data: { type: "stickyNote", content: "Published note", color: "yellow" },
          },
        ],
        edges: [],
      },
    };

    const { container } = render(<PublishedFixedCanvas token="pub-token" manifest={manifest} />);
    const page = container.querySelector(".relative.origin-top");

    expect(screen.getByText("Published note")).toBeInTheDocument();
    expect(page).toHaveStyle({ width: "794px", height: "1123px" });
  });
});
