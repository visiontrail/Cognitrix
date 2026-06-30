import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PublishedFixedCanvas, PublishedFreeCanvas } from "../../components/public/published-canvas-renderers";
import { ThemeProvider } from "../../lib/theme/context";
import { THEME_STORAGE_KEY } from "../../lib/theme/script";
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
    window.localStorage.clear();
    document.documentElement.classList.remove("dark");
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.removeAttribute("data-theme-mode");
    publicApiMock.fetchPublicChartData.mockResolvedValue({
      chart_id: "chart-1",
      spec: { chartType: "bar", title: "Published Headcount" },
      rows: [{ department: "HR", headcount: 4 }],
      data_truncated: false,
    });
  });

  afterEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove("dark");
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.removeAttribute("data-theme-mode");
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
    const publishedTextNode = screen.getByTestId("published-text-node-text-1");
    expect(publishedTextNode).not.toHaveClass("rounded-md");
    expect(publishedTextNode).not.toHaveClass("border");
    expect(publishedTextNode).not.toHaveClass("bg-white");
    expect(publishedTextNode).not.toHaveClass("p-4");
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

  it("does not pan the free-layout canvas when interacting with the portalled account menu", async () => {
    const user = userEvent.setup();
    // Regression: the account menu (and every Radix dropdown) portals its
    // content to document.body, so it is not a DOM descendant of the viewport,
    // yet React still bubbles the pointerdown up to the viewport's pan handler.
    // The handler used to start a pan-drag (preventDefault + setPointerCapture)
    // on those clicks, capturing the pointer and swallowing the menu selection —
    // which is why the published account menu's language toggle never fired on
    // the free canvas. A pointerdown originating in the menu must not pan.
    const manifest: PublishedManifest = {
      ...baseManifest,
      canvas: {
        format_id: "infinite",
        kind: "free_layout",
        bounds: { x: 0, y: 0, width: 640, height: 420 },
      },
      content: { nodes: [], edges: [] },
    };

    render(<PublishedFreeCanvas token="pub-token" manifest={manifest} />);

    const stage = screen.getByTestId("published-free-canvas-stage");
    const viewport = screen.getByTestId("published-free-canvas-viewport");
    expect(stage).toHaveStyle({ transform: "matrix(1, 0, 0, 1, 0, 0)" });

    await user.click(screen.getByRole("button", { name: "Open account menu" }));
    const languageItem = await screen.findByRole("menuitem", { name: "Language" });

    // Press inside the portalled menu item, then drag across the viewport.
    fireEvent.pointerDown(languageItem, { button: 0, pointerId: 2, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(viewport, { pointerId: 2, clientX: 220, clientY: 180 });
    fireEvent.pointerUp(viewport, { pointerId: 2, clientX: 220, clientY: 180 });

    // The canvas must stay put — the menu interaction is not a pan gesture.
    expect(stage).toHaveStyle({ transform: "matrix(1, 0, 0, 1, 0, 0)" });
    expect(viewport.className).not.toContain("cursor-grabbing");
  });

  it("themes light published free-layout backgrounds in dark mode", async () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    const manifest: PublishedManifest = {
      ...baseManifest,
      canvas: {
        format_id: "infinite",
        kind: "free_layout",
        background_preset_id: "ivory",
        bounds: { x: 0, y: 0, width: 640, height: 420 },
      },
      content: {
        nodes: [
          {
            id: "text-1",
            position: { x: 20, y: 24 },
            width: 260,
            height: 80,
            data: { type: "text", content: "Dark canvas narrative", color: "#3f3d39" },
          },
        ],
        edges: [],
      },
    };

    render(
      <ThemeProvider>
        <PublishedFreeCanvas token="pub-token" manifest={manifest} />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("published-free-canvas-viewport")).toHaveStyle({
        backgroundColor: "#13151d",
      });
    });
    expect(screen.getByTestId("published-text-node-text-1")).toHaveStyle({
      color: "#fffef9",
    });
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

  it("renders every page of a multi-page fixed-size canvas", () => {
    const manifest: PublishedManifest = {
      ...baseManifest,
      canvas: {
        format_id: "a4-portrait",
        kind: "fixed_size",
        page: { preset_id: "a4-portrait", width: 794, height: 1123, count: 2, gap: 48 },
      },
      content: {
        nodes: [
          {
            id: "page-1-note",
            position: { x: 48, y: 64 },
            width: 180,
            height: 120,
            data: { type: "stickyNote", content: "First page note", color: "yellow" },
          },
          {
            id: "page-2-note",
            // Page 2 starts at stride = 1123 + 48 = 1171.
            position: { x: 48, y: 1240 },
            width: 180,
            height: 120,
            data: { type: "stickyNote", content: "Second page note", color: "blue" },
          },
        ],
        edges: [],
      },
    };

    const { container } = render(<PublishedFixedCanvas token="pub-token" manifest={manifest} />);
    const stack = container.querySelector(".relative.origin-top");

    // Stack height = 1123 * 2 + 48 = 2294.
    expect(stack).toHaveStyle({ width: "794px", height: "2294px" });
    expect(container.querySelectorAll("[data-testid^='published-fixed-page-']")).toHaveLength(2);
    expect(screen.getByText("First page note")).toBeInTheDocument();
    expect(screen.getByText("Second page note")).toBeInTheDocument();
  });
});
