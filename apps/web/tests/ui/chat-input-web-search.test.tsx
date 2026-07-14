import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatInput } from "../../components/chat/chat-input";
import { I18nProvider } from "../../lib/i18n/context";
import { useChatStore } from "../../stores/chat-store";
import { useUIStore } from "../../stores/ui-store";
import { useWorkspaceStore } from "../../stores/workspace-store";

const { sendMutate } = vi.hoisted(() => ({
  sendMutate: vi.fn(),
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

function renderInput() {
  return render(
    React.createElement(I18nProvider, null, React.createElement(ChatInput, { sessionId: "s1" })),
  );
}

describe("ChatInput web-search option", () => {
  beforeEach(() => {
    sendMutate.mockReset();
    window.localStorage.clear();
    useChatStore.setState({ composerText: "", pendingIngestionBySession: {}, pendingIngestionSetupBySession: {} });
    useUIStore.setState({ isSending: false, sendingBySession: {} });
    useWorkspaceStore.setState({ activeWorkspaceId: null });
  });

  it("toggles web search from the + menu and sends webSearch: true", async () => {
    const user = userEvent.setup();
    renderInput();

    await user.click(screen.getByLabelText("Open chat actions"));
    const option = screen.getByRole("menuitemcheckbox", { name: "Search the web" });
    expect(option).toHaveAttribute("aria-checked", "false");
    await user.click(option);
    expect(
      screen.getByRole("menuitemcheckbox", { name: "Search the web" }),
    ).toHaveAttribute("aria-checked", "true");

    // Selected-state chip appears once the menu is dismissed.
    await user.keyboard("{Escape}");
    expect(screen.getByText("Web search on")).toBeInTheDocument();

    const input = screen.getByLabelText("Chat Input");
    await user.type(input, "各地区2024年平均工资对比{Enter}");

    expect(sendMutate).toHaveBeenCalledTimes(1);
    expect(sendMutate.mock.calls[0][0]).toMatchObject({
      sessionId: "s1",
      content: "各地区2024年平均工资对比",
      webSearch: true,
    });
  });

  it("removing the chip drops webSearch from the payload", async () => {
    const user = userEvent.setup();
    renderInput();

    await user.click(screen.getByLabelText("Open chat actions"));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Search the web" }));
    await user.keyboard("{Escape}");
    await user.click(screen.getByLabelText("Turn off web search"));
    expect(screen.queryByText("Web search on")).not.toBeInTheDocument();

    const input = screen.getByLabelText("Chat Input");
    await user.type(input, "headcount by department{Enter}");

    expect(sendMutate).toHaveBeenCalledTimes(1);
    expect(sendMutate.mock.calls[0][0].webSearch).toBeUndefined();
  });
});
