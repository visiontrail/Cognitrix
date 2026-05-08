import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "../../components/shared/app-shell";
import { useUIStore } from "../../stores/ui-store";
import { useWorkspaceStore } from "../../stores/workspace-store";

const createWorkspaceMutate = vi.fn();

vi.mock("../../hooks/use-chat", () => ({
  useChatSessions: () => ({}),
  useChatMessages: () => ({ isLoading: false }),
  useCreateSession: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("../../hooks/use-chart-assets", () => ({
  useChartAssets: () => ({}),
}));

vi.mock("../../hooks/use-workspace", () => ({
  useWorkspaceList: () => ({ isLoading: false, isSuccess: true }),
  useCreateWorkspace: () => ({ mutate: createWorkspaceMutate, isPending: false }),
  useWorkspaceSnapshot: () => ({ data: null, isLoading: false }),
  useSaveWorkspace: () => ({ mutate: vi.fn(), isPending: false }),
  useRenameWorkspace: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteWorkspace: () => ({ mutate: vi.fn(), isPending: false }),
  useWorkspaceCatalog: () => ({ isLoading: false, data: [] }),
  useCreateWorkspaceCatalogFromSetup: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteWorkspaceCatalogEntry: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock("../../components/chat/chat-panel", () => ({
  ChatPanel: () => <div>Chat panel</div>,
}));

vi.mock("../../components/workspace/workspace-panel", () => ({
  WorkspacePanel: () => <div>Canvas panel</div>,
}));

describe("AppShell workspace gate", () => {
  beforeEach(() => {
    createWorkspaceMutate.mockReset();
    useWorkspaceStore.setState({
      workspaces: [],
      activeWorkspaceId: null,
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      hasUnsavedChanges: false,
    });
    useUIStore.setState({
      activePanel: "both",
      chatSidebarOpen: true,
      workspaceSidebarOpen: false,
      chatCanvasSplitRatio: 0.5,
      isSending: false,
      sendingBySession: {},
      isSaving: false,
    });
  });

  it("forces workspace creation when no workspace exists", async () => {
    render(React.createElement(AppShell));

    expect(screen.getByText("Create Your First Workspace")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Workspace Name"), "North BI");
    await userEvent.click(screen.getByRole("button", { name: "Create Workspace" }));

    expect(createWorkspaceMutate).toHaveBeenCalledWith({ title: "North BI" });
  });

  it("lets users drag the chat and canvas divider to resize the split view", () => {
    useWorkspaceStore.setState({
      workspaces: [
        {
          id: "workspace-1",
          title: "Resizable Workspace",
          createdAt: "2026-04-24T00:00:00.000Z",
          updatedAt: "2026-04-24T00:00:00.000Z",
          nodeCount: 0,
        },
      ],
      activeWorkspaceId: "workspace-1",
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      hasUnsavedChanges: false,
    });

    const { container } = render(React.createElement(AppShell));
    const splitContainer = container.querySelector(".flex.flex-1.min-w-0.overflow-hidden");
    Object.defineProperty(splitContainer, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ left: 0, width: 1000, right: 1000, top: 0, bottom: 800, height: 800 }),
    });

    const resizer = screen.getByTestId("chat-canvas-resizer");
    fireEvent.pointerDown(resizer, { button: 0, clientX: 650 });
    fireEvent.pointerMove(window, { clientX: 650 });
    fireEvent.pointerUp(window);

    expect(useUIStore.getState().chatCanvasSplitRatio).toBeCloseTo(0.65);
  });
});
