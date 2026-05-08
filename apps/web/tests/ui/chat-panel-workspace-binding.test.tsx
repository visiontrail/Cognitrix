import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatPanel } from "../../components/chat/chat-panel";
import { useChatStore } from "../../stores/chat-store";
import { useUIStore } from "../../stores/ui-store";
import { useWorkspaceStore } from "../../stores/workspace-store";

vi.mock("../../hooks/use-chat", () => ({
  useChatMessages: () => ({ isLoading: false }),
  useCreateSession: () => ({ mutate: vi.fn(), isPending: false }),
  useSendMessage: () => ({ mutate: vi.fn() }),
  stopChatResponse: vi.fn(),
}));

describe("ChatPanel workspace binding", () => {
  beforeEach(() => {
    useChatStore.setState({
      sessions: [],
      activeSessionId: null,
      messagesBySession: {},
      isComposing: false,
      composerText: "",
    });

    useUIStore.setState({
      activePanel: "chat",
      chatSidebarOpen: true,
      workspaceSidebarOpen: false,
      isSending: false,
      sendingBySession: {},
      isSaving: false,
    });

    useWorkspaceStore.setState({
      workspaces: [
        {
          id: "ws-1",
          title: "Finance Ops",
          createdAt: "2026-04-17T00:00:00.000Z",
          updatedAt: "2026-04-17T00:00:00.000Z",
          nodeCount: 0,
        },
      ],
      activeWorkspaceId: "ws-1",
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      hasUnsavedChanges: false,
    });
  });

  it("shows active workspace in chat header", () => {
    render(React.createElement(ChatPanel));

    expect(screen.getByText("Workspace: Finance Ops")).toBeInTheDocument();
  });
});
