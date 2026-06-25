import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "../../components/ui/tooltip";
import { WorkspaceToolbar } from "../../components/workspace/workspace-toolbar";
import { clearInMemoryToken, setInMemoryToken } from "../../lib/auth/session";
import { DEFAULT_CANVAS_FORMAT } from "../../lib/workspace/canvas-formats";
import { useWorkspaceStore } from "../../stores/workspace-store";

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
});
