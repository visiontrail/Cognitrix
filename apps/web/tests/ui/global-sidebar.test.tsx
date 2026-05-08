import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { TooltipProvider } from "../../components/ui/tooltip";
import { GlobalSidebar } from "../../components/shared/global-sidebar";
import { useChatStore } from "../../stores/chat-store";
import { useUIStore } from "../../stores/ui-store";
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

describe("GlobalSidebar", () => {
  beforeEach(() => {
    useChatStore.setState({
      sessions: [
        {
          id: "session-1",
          title: "Turnover Rate Investigation",
          createdAt: "2026-04-14T00:00:00.000Z",
          updatedAt: new Date().toISOString(),
          messageCount: 2,
        },
      ],
      activeSessionId: "session-1",
      messagesBySession: { "session-1": [] },
      isComposing: false,
      composerText: "",
    });

    useWorkspaceStore.setState({
      workspaces: [
        {
          id: "ws-1",
          title: "Q1 2026 HR2 Report",
          createdAt: "2026-04-14T00:00:00.000Z",
          updatedAt: "2026-04-14T00:00:00.000Z",
          nodeCount: 3,
        },
      ],
      activeWorkspaceId: "ws-1",
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      hasUnsavedChanges: false,
    });

    useUIStore.setState({
      activePanel: "both",
      chatSidebarOpen: true,
      workspaceSidebarOpen: false,
      isSending: false,
      sendingBySession: {},
      isSaving: false,
    });
  });

  afterEach(() => {
    window.localStorage.clear();
    useChatStore.setState({
      sessions: [],
      activeSessionId: null,
      messagesBySession: {},
      isComposing: false,
      composerText: "",
    });
    useWorkspaceStore.setState({
      workspaces: [],
      activeWorkspaceId: null,
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      hasUnsavedChanges: false,
    });
  });

  it("keeps add and delete actions discoverable in the sidebar", () => {
    renderWithProviders(<GlobalSidebar />);

    expect(screen.getByRole("button", { name: "New conversation" })).toHaveClass(
      "border-ring-warm",
      "text-near-black"
    );
    expect(screen.getByRole("button", { name: "New workspace" })).toHaveClass(
      "border-ring-warm",
      "text-near-black"
    );

    const deleteConversation = screen.getByRole("button", {
      name: "Delete conversation: Turnover Rate Investigation",
    });
    const deleteWorkspace = screen.getByRole("button", {
      name: "Delete workspace: Q1 2026 HR2 Report",
    });

    expect(deleteConversation).toHaveClass("opacity-100");
    expect(deleteConversation).not.toHaveClass("opacity-0");
    expect(deleteWorkspace).toHaveClass("opacity-100");
    expect(deleteWorkspace).not.toHaveClass("opacity-0");
  });

  it("keeps the delete action visible for very long conversation titles", () => {
    useChatStore.setState({
      sessions: [
        {
          id: "session-long",
          title:
            "请按组织架构层级对过去二十四个月的人效变化、离职趋势、招聘补充效率和异常波动做完整分析并指出重点部门",
          createdAt: "2026-04-14T00:00:00.000Z",
          updatedAt: new Date().toISOString(),
          messageCount: 1,
        },
      ],
      activeSessionId: "session-long",
      messagesBySession: { "session-long": [] },
      isComposing: false,
      composerText: "",
    });

    renderWithProviders(<GlobalSidebar />);

    expect(
      screen.getByRole("button", {
        name:
          "Delete conversation: 请按组织架构层级对过去二十四个月的人效变化、离职趋势、招聘补充效率和异常波动做完整分析并指出重点部门",
      })
    ).toHaveClass("opacity-100");
  });

  it("deletes a conversation from its always-visible row action", async () => {
    renderWithProviders(<GlobalSidebar />);

    await userEvent.click(
      screen.getByRole("button", {
        name: "Delete conversation: Turnover Rate Investigation",
      })
    );

    await waitFor(() => {
      expect(useChatStore.getState().sessions).toEqual([]);
    });
  });

  it("renames a conversation inline from the sidebar row", async () => {
    renderWithProviders(<GlobalSidebar />);

    await userEvent.click(
      screen.getByRole("button", {
        name: "Rename conversation: Turnover Rate Investigation",
      })
    );

    const input = screen.getByRole("textbox", { name: "Conversation name" });
    await userEvent.clear(input);
    await userEvent.type(input, "Q1 Turnover Deep Dive{Enter}");

    await waitFor(() => {
      expect(useChatStore.getState().sessions[0]?.title).toBe("Q1 Turnover Deep Dive");
    });
  });

  it("cancels an inline conversation rename via Escape", async () => {
    renderWithProviders(<GlobalSidebar />);

    await userEvent.click(
      screen.getByRole("button", {
        name: "Rename conversation: Turnover Rate Investigation",
      })
    );

    const input = screen.getByRole("textbox", { name: "Conversation name" });
    await userEvent.clear(input);
    await userEvent.type(input, "Discarded title{Escape}");

    expect(useChatStore.getState().sessions[0]?.title).toBe("Turnover Rate Investigation");
  });

  it("deletes a workspace from its always-visible row action", async () => {
    renderWithProviders(<GlobalSidebar />);

    await userEvent.click(
      screen.getByRole("button", {
        name: "Delete workspace: Q1 2026 HR2 Report",
      })
    );

    await waitFor(() => {
      expect(useWorkspaceStore.getState().workspaces).toEqual([]);
    });
  });
});
