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

function renderInput() {
  return render(
    React.createElement(I18nProvider, null, React.createElement(ChatInput, { sessionId: "s1" })),
  );
}

describe("ChatInput agent-canvas option", () => {
  beforeEach(() => {
    sendMutate.mockReset();
    window.localStorage.clear();
    capabilities.agentCanvasModeEnabled = false;
    useChatStore.setState({ composerText: "", pendingIngestionBySession: {}, pendingIngestionSetupBySession: {} });
    useUIStore.setState({ isSending: false, sendingBySession: {} });
    useWorkspaceStore.setState({ activeWorkspaceId: null, canvasFormat: { id: "web-design" } });
  });

  it("hides the Agent-mode toggle when the backend flag is off", async () => {
    const user = userEvent.setup();
    renderInput();

    await user.click(screen.getByLabelText("Open chat actions"));
    expect(
      screen.queryByRole("menuitemcheckbox", { name: "Agent build dashboard" }),
    ).not.toBeInTheDocument();
  });

  it("sends agentCanvas: true when the toggle is active and the canvas is web-design", async () => {
    capabilities.agentCanvasModeEnabled = true;
    const user = userEvent.setup();
    renderInput();

    await user.click(screen.getByLabelText("Open chat actions"));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Agent build dashboard" }));
    await user.keyboard("{Escape}");
    expect(screen.getByText("Agent dashboard mode")).toBeInTheDocument();
    expect(screen.queryByTestId("agent-canvas-format-prompt")).not.toBeInTheDocument();

    const input = screen.getByLabelText("Chat Input");
    await user.type(input, "生成销售概览仪表盘{Enter}");

    expect(sendMutate).toHaveBeenCalledTimes(1);
    expect(sendMutate.mock.calls[0][0]).toMatchObject({
      sessionId: "s1",
      content: "生成销售概览仪表盘",
      agentCanvas: true,
    });
  });

  it("prompts a one-click format switch and blocks sending on other formats", async () => {
    capabilities.agentCanvasModeEnabled = true;
    useWorkspaceStore.setState({ canvasFormat: { id: "infinite" } });
    const user = userEvent.setup();
    renderInput();

    await user.click(screen.getByLabelText("Open chat actions"));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Agent build dashboard" }));
    await user.keyboard("{Escape}");

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
});
