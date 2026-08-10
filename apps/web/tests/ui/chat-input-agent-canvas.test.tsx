import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatInput } from "../../components/chat/chat-input";
import { I18nProvider } from "../../lib/i18n/context";
import { useChatStore } from "../../stores/chat-store";
import { useUIStore } from "../../stores/ui-store";
import { useWorkspaceStore } from "../../stores/workspace-store";

const { sendMutate, capabilities } = vi.hoisted(() => ({
  sendMutate: vi.fn(),
  capabilities: { agentCanvasModeEnabled: false, webSearchEnabled: false },
}));

vi.mock("../../hooks/use-chat", () => ({
  useSendMessage: () => ({ mutate: sendMutate }),
  stopChatResponse: vi.fn(),
  useConfirmIngestionSetup: () => ({ mutate: vi.fn() }),
}));

vi.mock("../../hooks/use-workspace-columns", () => ({
  useWorkspaceColumns: () => [],
}));

vi.mock("../../hooks/use-saved-prompts", () => ({
  useSavedPrompts: () => ({ data: [], isLoading: false, isError: false }),
  useMarkSavedPromptUsed: () => ({ mutate: vi.fn() }),
  useCreateSavedPrompt: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateSavedPrompt: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useArchiveSavedPrompt: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock("../../hooks/use-backend-capabilities", () => ({
  useBackendCapabilities: () => capabilities,
}));

vi.mock("../../components/charts/chart-preview", () => ({
  ChartPreview: ({ spec }: { spec: { title: string } }) => <div>{`Preview: ${spec.title}`}</div>,
}));

function renderInput(sessionId = "s1") {
  return render(
    React.createElement(I18nProvider, null, React.createElement(ChatInput, { sessionId })),
  );
}

describe("ChatInput agent-mode switch", () => {
  beforeEach(() => {
    sendMutate.mockReset();
    window.localStorage.clear();
    capabilities.agentCanvasModeEnabled = false;
    useChatStore.setState({
      composerText: "",
      pendingIngestionBySession: {},
      pendingIngestionSetupBySession: {},
      agentModeBySession: {},
    });
    useUIStore.setState({ isSending: false, sendingBySession: {}, chartEditTarget: null });
    useWorkspaceStore.setState({ activeWorkspaceId: null, canvasFormat: { id: "web-design" } });
  });

  it("hides the Agent-mode switch when the backend flag is off", () => {
    renderInput();
    expect(screen.queryByTestId("agent-mode-toggle")).not.toBeInTheDocument();
  });

  it("does not offer Agent mode as a row in the + menu", async () => {
    capabilities.agentCanvasModeEnabled = true;
    const user = userEvent.setup();
    renderInput();

    await user.click(screen.getByLabelText("Open chat actions"));
    expect(
      screen.queryByRole("menuitemcheckbox", { name: "Agent build dashboard" }),
    ).not.toBeInTheDocument();
  });

  it("keeps agentCanvas: true on every turn once the switch is on", async () => {
    capabilities.agentCanvasModeEnabled = true;
    const user = userEvent.setup();
    renderInput();

    const toggle = screen.getByTestId("agent-mode-toggle");
    expect(toggle).toHaveAttribute("aria-checked", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByTestId("agent-canvas-format-prompt")).not.toBeInTheDocument();

    const input = screen.getByLabelText("Chat Input");
    await user.type(input, "生成销售概览仪表盘{Enter}");
    expect(sendMutate.mock.calls[0][0]).toMatchObject({
      sessionId: "s1",
      content: "生成销售概览仪表盘",
      agentCanvas: true,
    });

    // The mode is sticky: it survives the send instead of resetting like the
    // per-message "+" options do.
    expect(screen.getByTestId("agent-mode-toggle")).toHaveAttribute("aria-checked", "true");
    await user.type(screen.getByLabelText("Chat Input"), "再加一页人力概览{Enter}");
    expect(sendMutate).toHaveBeenCalledTimes(2);
    expect(sendMutate.mock.calls[1][0]).toMatchObject({ agentCanvas: true });
  });

  it("scopes the mode to its own conversation and turns off on a second click", async () => {
    capabilities.agentCanvasModeEnabled = true;
    const user = userEvent.setup();
    const { unmount } = renderInput("s1");
    await user.click(screen.getByTestId("agent-mode-toggle"));
    unmount();

    // A different conversation starts off.
    const other = renderInput("s2");
    expect(screen.getByTestId("agent-mode-toggle")).toHaveAttribute("aria-checked", "false");
    await user.type(screen.getByLabelText("Chat Input"), "各部门人数{Enter}");
    expect(sendMutate.mock.calls[0][0]).toMatchObject({ sessionId: "s2", agentCanvas: false });
    other.unmount();

    // Back in the original conversation the mode is still on, and clicking the
    // switch again turns it off.
    renderInput("s1");
    const toggle = screen.getByTestId("agent-mode-toggle");
    expect(toggle).toHaveAttribute("aria-checked", "true");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(useChatStore.getState().agentModeBySession.s1).toBeUndefined();

    await user.type(screen.getByLabelText("Chat Input"), "各部门人数{Enter}");
    expect(sendMutate.mock.calls[1][0]).toMatchObject({ sessionId: "s1", agentCanvas: false });
  });

  it("prompts a one-click format switch and blocks sending on other formats", async () => {
    capabilities.agentCanvasModeEnabled = true;
    useWorkspaceStore.setState({ canvasFormat: { id: "infinite" } });
    const user = userEvent.setup();
    renderInput();

    await user.click(screen.getByTestId("agent-mode-toggle"));

    const prompt = screen.getByTestId("agent-canvas-format-prompt");
    expect(prompt).toBeInTheDocument();

    // Sending is blocked while the format mismatches.
    const input = screen.getByLabelText("Chat Input");
    await user.type(input, "生成销售概览仪表盘{Enter}");
    expect(sendMutate).not.toHaveBeenCalled();

    // One-click switch clears the prompt and unblocks sending.
    await user.click(screen.getByRole("button", { name: "Switch to web design" }));
    expect(useWorkspaceStore.getState().canvasFormat.id).toBe("web-design");
    expect(screen.queryByTestId("agent-canvas-format-prompt")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Chat Input"), "{Enter}");
    expect(sendMutate).toHaveBeenCalledTimes(1);
    expect(sendMutate.mock.calls[0][0]).toMatchObject({ agentCanvas: true });
  });

  it("shows the selected canvas chart and submits it as a focused edit target", async () => {
    capabilities.agentCanvasModeEnabled = true;
    useChatStore.setState({
      sessions: [
        {
          id: "s1",
          title: "Canvas edits",
          createdAt: "2026-08-10T00:00:00Z",
          updatedAt: "2026-08-10T00:00:00Z",
          messageCount: 0,
        },
      ],
      activeSessionId: "s1",
      agentModeBySession: { s1: true },
    });
    useWorkspaceStore.setState({ activeWorkspaceId: "ws-1", canvasFormat: { id: "web-design" } });
    useUIStore.setState({
      chartEditTarget: {
        sessionId: "s1",
        workspaceId: "ws-1",
        canvasFormat: "web-design",
        nodeId: "node-chart-1",
        zoneId: "zone-chart-1",
        pageId: "page-1",
        assetId: "asset-chart-1",
        title: "Department headcount",
        chartType: "bar",
        spec: {
          chartType: "bar",
          title: "Department headcount",
          echartsOption: { __rows__: [{ segment: "HR", metric_value: 24 }] },
        },
        assistantRows: [{ segment: "HR", metric_value: 24 }],
      },
    });

    const user = userEvent.setup();
    renderInput();

    expect(screen.getByTestId("chart-edit-context")).toBeInTheDocument();
    expect(screen.getByText("Preview: Department headcount")).toBeInTheDocument();
    expect(screen.getByLabelText("Chat Input")).toHaveAttribute(
      "placeholder",
      "Tell the agent how to change this chart…"
    );

    await user.type(screen.getByLabelText("Chat Input"), "Change it to a donut chart{Enter}");

    expect(sendMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "s1",
        content: "Change it to a donut chart",
        agentCanvas: true,
        chartEditTarget: expect.objectContaining({
          nodeId: "node-chart-1",
          assetId: "asset-chart-1",
        }),
      })
    );
  });
});
