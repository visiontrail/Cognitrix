import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "../../components/ui/tooltip";
import { WorkspaceToolbar } from "../../components/workspace/workspace-toolbar";
import { clearInMemoryToken, setInMemoryToken } from "../../lib/auth/session";
import { DEFAULT_CANVAS_FORMAT } from "../../lib/workspace/canvas-formats";
import * as canvasExport from "../../lib/workspace/canvas-export";
import { useWorkspaceStore } from "../../stores/workspace-store";

vi.mock("../../lib/workspace/canvas-export", () => ({
  exportInfiniteCanvasToPng: vi.fn().mockResolvedValue(undefined),
  exportFixedCanvasToPng: vi.fn().mockResolvedValue(undefined),
  exportFixedCanvasToPdf: vi.fn().mockResolvedValue(undefined),
  printFixedCanvas: vi.fn().mockResolvedValue(undefined),
}));

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

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubWorkspaceNetwork() {
  const history = [
    {
      page_id: "page-4",
      version: 4,
      published_at: "2026-06-26T09:04:00+00:00",
      published_by: "alice",
      canvas_format_id: "infinite",
      canvas_kind: "free_layout",
    },
    {
      page_id: "page-3",
      version: 3,
      published_at: "2026-06-26T09:03:00+00:00",
      published_by: "alice",
      canvas_format_id: "a4-portrait",
      canvas_kind: "fixed_size",
    },
    {
      page_id: "page-2",
      version: 2,
      published_at: "2026-06-26T09:02:00+00:00",
      published_by: "alice",
      canvas_format_id: "web-design",
      canvas_kind: "web_page",
    },
    {
      page_id: "page-1",
      version: 1,
      published_at: "2026-06-26T09:01:00+00:00",
      published_by: "alice",
      canvas_format_id: "infinite",
      canvas_kind: "free_layout",
    },
  ];

  const snapshot = {
    page_id: "page-4",
    version: 4,
    published_at: "2026-06-26T09:04:00+00:00",
    published_by: "alice",
    canvas_format_id: "infinite",
    canvas_kind: "free_layout",
    manifest: {
      schema_version: 2,
      workspace_id: "ws-test",
      version: 4,
      published_at: "2026-06-26T09:04:00+00:00",
      canvas: {
        format_id: "infinite",
        kind: "free_layout",
        viewport: { x: 10, y: 20, zoom: 0.8 },
      },
      content: {
        nodes: [
          {
            id: "restored-note",
            type: "textNode",
            position: { x: 40, y: 60 },
            width: 240,
            height: 120,
            data: { type: "text", content: "Restored", width: 240, height: 120 },
          },
        ],
        edges: [],
      },
      layout: { grid: { columns: 3, rows: [] }, zones: [] },
      sidebar: [],
      charts: [],
    },
    charts: [],
  };

  return vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url.includes("/catalog")) {
      return Promise.resolve(jsonResponse({ entries: [] }));
    }
    if (url.includes("/published/page-4/snapshot")) {
      return Promise.resolve(jsonResponse(snapshot));
    }
    if (url.includes("/published")) {
      return Promise.resolve(jsonResponse({ count: history.length, published_pages: history }));
    }
    if (url.includes("/canvas-snapshot") && method === "PUT") {
      return Promise.resolve(jsonResponse({ ok: true }));
    }
    if (url.includes("/publish")) {
      return Promise.resolve(jsonResponse({ is_active: false, canvas_kind: "free_layout" }));
    }
    return Promise.resolve(jsonResponse({}));
  });
}

describe("WorkspaceToolbar", () => {
  beforeEach(() => {
    setInMemoryToken("test-token", Math.floor(Date.now() / 1000) + 3600);
    useWorkspaceStore.setState({
      workspaces: [
        {
          id: "ws-test",
          title: "Original Canvas",
          createdAt: "2026-04-14T00:00:00.000Z",
          updatedAt: "2026-04-14T00:00:00.000Z",
          nodeCount: 0,
        },
      ],
      activeWorkspaceId: "ws-test",
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      canvasFormat: DEFAULT_CANVAS_FORMAT,
      hasUnsavedChanges: false,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
    clearInMemoryToken();
    useWorkspaceStore.setState({
      workspaces: [],
      activeWorkspaceId: null,
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      canvasFormat: DEFAULT_CANVAS_FORMAT,
      hasUnsavedChanges: false,
    });
  });

  it("renames the active workspace from the canvas toolbar", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(new Response("{}", { status: 200 }))));
    renderWithProviders(<WorkspaceToolbar />);

    await userEvent.click(screen.getByRole("button", { name: "Rename workspace" }));
    const nameInput = screen.getByLabelText("Workspace name");

    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "Renamed Canvas");
    await userEvent.click(screen.getByRole("button", { name: "Save workspace name" }));

    await waitFor(() => {
      expect(screen.getByText("Renamed Canvas")).toBeInTheDocument();
      expect(useWorkspaceStore.getState().workspaces[0].title).toBe("Renamed Canvas");
    });
  });

  it("switches the workspace canvas format from the toolbar", async () => {
    renderWithProviders(<WorkspaceToolbar />);

    await userEvent.click(screen.getByRole("button", { name: "Canvas size" }));
    await userEvent.click(screen.getByText("A4 landscape"));

    await waitFor(() => {
      expect(screen.getByText("A4 landscape")).toBeInTheDocument();
      expect(useWorkspaceStore.getState().canvasFormat.id).toBe("a4-landscape");
      expect(useWorkspaceStore.getState().hasUnsavedChanges).toBe(true);
    });
  });

  it("does not render a manual canvas save button", () => {
    useWorkspaceStore.setState({ hasUnsavedChanges: true });

    renderWithProviders(<WorkspaceToolbar />);

    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(screen.getByText(/Unsaved changes/i)).toBeInTheDocument();
  });

  it("prints a printable paper canvas from the export menu", async () => {
    useWorkspaceStore.setState({ canvasFormat: { id: "a4-portrait" } });
    renderWithProviders(<WorkspaceToolbar />);

    await userEvent.click(screen.getByRole("button", { name: "Export" }));
    await userEvent.click(screen.getByText("Print"));

    await waitFor(() => {
      expect(canvasExport.printFixedCanvas).toHaveBeenCalledTimes(1);
    });
    expect(canvasExport.printFixedCanvas).toHaveBeenCalledWith(
      expect.objectContaining({ id: "a4-portrait", printable: true }),
      "Original Canvas",
      1
    );
  });

  it("omits the print action for non-printable fixed canvases", async () => {
    useWorkspaceStore.setState({ canvasFormat: { id: "wide-16-9" } });
    renderWithProviders(<WorkspaceToolbar />);

    await userEvent.click(screen.getByRole("button", { name: "Export" }));

    expect(screen.getByText("Export PNG")).toBeInTheDocument();
    expect(screen.queryByText("Print")).not.toBeInTheDocument();
  });

  it("labels the PDF export as a slide deck for 16:9 canvases", async () => {
    useWorkspaceStore.setState({ canvasFormat: { id: "wide-16-9" } });
    renderWithProviders(<WorkspaceToolbar />);

    await userEvent.click(screen.getByRole("button", { name: "Export" }));

    expect(screen.getByText("Export slides PDF")).toBeInTheDocument();
    expect(screen.queryByText("Export PDF")).not.toBeInTheDocument();
  });

  it("adds a page to a fixed canvas and surfaces the page count", async () => {
    useWorkspaceStore.setState({ canvasFormat: { id: "a4-portrait" }, canvasPages: {} });
    renderWithProviders(<WorkspaceToolbar />);

    expect(screen.getByText("1 pages")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add page" }));

    await waitFor(() => {
      expect(useWorkspaceStore.getState().canvasPages["a4-portrait"]).toBe(2);
    });
    expect(screen.getByText("2 pages")).toBeInTheDocument();
  });

  it("hides page controls on the infinite canvas", () => {
    useWorkspaceStore.setState({ canvasFormat: DEFAULT_CANVAS_FORMAT, canvasPages: {} });
    renderWithProviders(<WorkspaceToolbar />);

    expect(screen.queryByRole("button", { name: "Add page" })).not.toBeInTheDocument();
  });

  it("shows only the latest three published history entries with canvas type labels", async () => {
    vi.stubGlobal("fetch", stubWorkspaceNetwork());
    useWorkspaceStore.setState({
      workspaces: [
        {
          id: "ws-test",
          title: "Original Canvas",
          createdAt: "2026-04-14T00:00:00.000Z",
          updatedAt: "2026-04-14T00:00:00.000Z",
          nodeCount: 0,
          role: "editor",
        },
      ],
    });

    renderWithProviders(<WorkspaceToolbar />);

    await userEvent.click(screen.getByRole("button", { name: "History" }));

    expect(await screen.findByText("v4")).toBeInTheDocument();
    expect(screen.getByText("v3")).toBeInTheDocument();
    expect(screen.getByText("v2")).toBeInTheDocument();
    expect(screen.queryByText("v1")).not.toBeInTheDocument();
    expect(screen.getByText("Free canvas")).toBeInTheDocument();
    expect(screen.getByText("Fixed page")).toBeInTheDocument();
    expect(screen.getByText("Web page")).toBeInTheDocument();
    expect(screen.getByText("Showing latest 3 of 4. Full history is retained.")).toBeInTheDocument();
  });

  it("restores the workspace to a clicked published history version", async () => {
    const fetchMock = stubWorkspaceNetwork();
    vi.stubGlobal("fetch", fetchMock);
    useWorkspaceStore.setState({
      workspaces: [
        {
          id: "ws-test",
          title: "Original Canvas",
          createdAt: "2026-04-14T00:00:00.000Z",
          updatedAt: "2026-04-14T00:00:00.000Z",
          nodeCount: 0,
          role: "editor",
        },
      ],
    });

    renderWithProviders(<WorkspaceToolbar />);

    await userEvent.click(screen.getByRole("button", { name: "History" }));
    await userEvent.click(await screen.findByRole("button", { name: "Restore v4 · Infinite canvas" }));

    await waitFor(() => {
      const state = useWorkspaceStore.getState();
      expect(state.canvasFormat.id).toBe("infinite");
      expect(state.viewport).toEqual({ x: 10, y: 20, zoom: 0.8 });
      expect(state.nodes[0]?.id).toBe("restored-note");
      expect(state.hasUnsavedChanges).toBe(false);
    });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/workspaces/ws-test/published/page-4/snapshot"),
      expect.any(Object)
    );
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/workspaces/ws-test/canvas-snapshot"),
      expect.objectContaining({ method: "PUT" })
    );
  });
});
