import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "../../components/shared/app-shell";
import { TooltipProvider } from "../../components/ui/tooltip";
import { useChatStore } from "../../stores/chat-store";
import { useUIStore } from "../../stores/ui-store";
import { useWorkspaceStore } from "../../stores/workspace-store";
import type { ChatSession } from "../../types/chat";

const createWorkspaceMutate = vi.fn();

vi.mock("../../hooks/use-chat", () => ({
  chatSessionsQueryKey: (workspaceId: string | null | undefined) => ["chat-sessions", workspaceId ?? null],
  useChatSessions: () => ({}),
  useChatMessages: () => ({ isLoading: false }),
  useCreateSession: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteSession: () => ({ mutate: vi.fn(), isPending: false }),
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

vi.mock("../../lib/auth/use-session", () => ({
  useSession: () => ({
    user: {
      id: "user-1",
      email: "user@example.com",
      display_name: "User",
      available_workspaces: [],
    },
    isLoggedIn: true,
    isLoading: false,
    query: {},
  }),
}));

function chatSession(id: string, title: string): ChatSession {
  return {
    id,
    title,
    createdAt: "2026-05-11T00:00:00.000Z",
    updatedAt: "2026-05-11T00:00:00.000Z",
    messageCount: 0,
  };
}

function renderAppShell() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <AppShell />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

describe("AppShell workspace gate", () => {
  beforeEach(() => {
    createWorkspaceMutate.mockReset();
    window.localStorage.clear();
    useChatStore.getState().clearForUser();
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
    renderAppShell();

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

    const { container } = renderAppShell();
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

  it("reinitializes chat state when the active workspace changes", async () => {
    useWorkspaceStore.setState({
      workspaces: [
        {
          id: "ws-a",
          title: "Workspace A",
          createdAt: "2026-05-11T00:00:00.000Z",
          updatedAt: "2026-05-11T00:00:00.000Z",
          nodeCount: 0,
        },
        {
          id: "ws-b",
          title: "Workspace B",
          createdAt: "2026-05-11T00:00:00.000Z",
          updatedAt: "2026-05-11T00:00:00.000Z",
          nodeCount: 0,
        },
      ],
      activeWorkspaceId: "ws-a",
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      hasUnsavedChanges: false,
    });
    useChatStore.getState().initForWorkspace("user-1", "ws-a");
    useChatStore.getState().addSession(chatSession("session-a", "Workspace A chat"));
    useChatStore.getState().initForWorkspace("user-1", "ws-b");
    useChatStore.getState().addSession(chatSession("session-b", "Workspace B chat"));
    useChatStore.getState().initForWorkspace("user-1", null);

    renderAppShell();

    await waitFor(() => {
      expect(useChatStore.getState().sessions.map((session) => session.id)).toEqual(["session-a"]);
    });

    await userEvent.click(screen.getByText("Workspace B"));

    await waitFor(() => {
      expect(useChatStore.getState().sessions.map((session) => session.id)).toEqual(["session-b"]);
    });
  });
});
