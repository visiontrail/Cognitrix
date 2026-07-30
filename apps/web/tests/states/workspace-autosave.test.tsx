import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAutoSaveWorkspace } from "../../hooks/use-workspace";
import { DEFAULT_CANVAS_FORMAT } from "../../lib/workspace/canvas-formats";
import { useWorkspaceStore } from "../../stores/workspace-store";
import type { WorkspaceNode } from "../../types/workspace";

const WORKSPACE_SNAPSHOT_STORAGE_KEY = "cognitrix:workspace-snapshots:v1";

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
      data: [{ department: "HR", headcount: 4 }],
    },
  },
};

function AutoSaveHarness() {
  useAutoSaveWorkspace({ enabled: true });
  return null;
}

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("workspace auto-save", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Auto-save writes the local cache and then PUTs the snapshot to the API.
    // Without a stubbed fetch the PUT rejects, the mutation never reaches
    // onSuccess, and hasUnsavedChanges is never cleared.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        // Shape satisfies both the legacy /auth/login exchange and the
        // canvas-snapshot PUT.
        json: async () => ({
          access_token: "test-token",
          expires_at: Math.floor(Date.now() / 1000) + 3600,
        }),
        text: async () => "{}",
      }))
    );
    window.localStorage.clear();
    useWorkspaceStore.setState({
      workspaces: [],
      activeWorkspaceId: "ws-test",
      nodes: [chartNode],
      edges: [],
      nodesByFormat: {},
      edgesByFormat: {},
      viewport: { x: 0, y: 0, zoom: 1 },
      canvasFormat: DEFAULT_CANVAS_FORMAT,
      hasUnsavedChanges: true,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    window.localStorage.clear();
    useWorkspaceStore.setState({
      workspaces: [],
      activeWorkspaceId: null,
      nodes: [],
      edges: [],
      nodesByFormat: {},
      edgesByFormat: {},
      viewport: { x: 0, y: 0, zoom: 1 },
      canvasFormat: DEFAULT_CANVAS_FORMAT,
      hasUnsavedChanges: false,
    });
  });

  it("saves dirty workspace snapshots without a manual save action", async () => {
    renderWithProviders(<AutoSaveHarness />);

    // Still inside the auto-save debounce window (900ms): nothing written yet.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });
    expect(window.localStorage.getItem(WORKSPACE_SNAPSHOT_STORAGE_KEY)).toBeNull();

    // Move a node, then let the debounce elapse — the save must happen on its
    // own, with no manual save action.
    await act(async () => {
      useWorkspaceStore.getState().setNodes([
        {
          ...chartNode,
          position: { x: 120, y: 40 },
        },
      ]);
      await vi.advanceTimersByTimeAsync(1000);
    });

    // The act() above already flushed the debounce, the mutation and its
    // onSuccess; waitFor would only deadlock against the fake timers here.
    expect(useWorkspaceStore.getState().hasUnsavedChanges).toBe(false);

    const persisted = JSON.parse(window.localStorage.getItem(WORKSPACE_SNAPSHOT_STORAGE_KEY) ?? "{}");
    expect(persisted.snapshots["ws-test"].nodes[0].id).toBe("node-chart");
    expect(persisted.snapshots["ws-test"].nodes[0].position).toEqual({ x: 120, y: 40 });
  });
});
