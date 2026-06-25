import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatInput } from "../../components/chat/chat-input";
import { I18nProvider } from "../../lib/i18n/context";
import { useChatStore } from "../../stores/chat-store";
import { useUIStore } from "../../stores/ui-store";
import { useWorkspaceStore } from "../../stores/workspace-store";
import type { SavedPrompt } from "../../lib/saved-prompts/types";

const { sendMutate, markUsedMutate, savedPromptsRef } = vi.hoisted(() => ({
  sendMutate: vi.fn(),
  markUsedMutate: vi.fn(),
  savedPromptsRef: { current: [] as SavedPrompt[] },
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
  useSavedPrompts: () => ({ data: savedPromptsRef.current, isLoading: false, isError: false }),
  useMarkSavedPromptUsed: () => ({ mutate: markUsedMutate }),
  useCreateSavedPrompt: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateSavedPrompt: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useArchiveSavedPrompt: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

function makePrompt(overrides: Partial<SavedPrompt>): SavedPrompt {
  return {
    id: "p1",
    name: "Summary",
    body: "summarize this table",
    variables: [],
    capabilities: [],
    usageCount: 0,
    lastUsedAt: null,
    createdAt: "2026-06-01T00:00:00Z",
    updatedAt: "2026-06-01T00:00:00Z",
    archivedAt: null,
    ...overrides,
  };
}

function renderInput() {
  return render(
    React.createElement(I18nProvider, null, React.createElement(ChatInput, { sessionId: "s1" })),
  );
}

describe("ChatInput saved-prompts menu", () => {
  beforeEach(() => {
    sendMutate.mockReset();
    markUsedMutate.mockReset();
    savedPromptsRef.current = [];
    window.localStorage.clear();
    useChatStore.setState({ composerText: "", pendingIngestionBySession: {}, pendingIngestionSetupBySession: {} });
    useUIStore.setState({ isSending: false, sendingBySession: {} });
    useWorkspaceStore.setState({ activeWorkspaceId: null });
  });

  it("opens the create dialog from the menu without mutating the composer draft", async () => {
    const user = userEvent.setup();
    renderInput();

    const input = screen.getByLabelText("Chat Input");
    await user.type(input, "draft text");

    await user.click(screen.getByLabelText("Open chat actions"));
    await user.click(screen.getByRole("menuitem", { name: "Saved prompts" }));
    await user.click(screen.getByRole("menuitem", { name: "Create prompt" }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Create prompt")).toBeInTheDocument();
    // Draft is preserved.
    expect((screen.getByLabelText("Chat Input") as HTMLTextAreaElement).value).toBe("draft text");
    expect(sendMutate).not.toHaveBeenCalled();
  });

  it("opens the manage dialog from the menu", async () => {
    const user = userEvent.setup();
    renderInput();

    await user.click(screen.getByLabelText("Open chat actions"));
    await user.click(screen.getByRole("menuitem", { name: "Saved prompts" }));
    await user.click(screen.getByRole("menuitem", { name: "Manage prompts" }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Search prompts…")).toBeInTheDocument();
  });

  it("inserts a variable-free prompt at the caret without sending", async () => {
    savedPromptsRef.current = [makePrompt({ name: "Summary", body: "summarize this table" })];
    const user = userEvent.setup();
    renderInput();

    const input = screen.getByLabelText("Chat Input") as HTMLTextAreaElement;
    await user.type(input, "Please ");

    await user.click(screen.getByLabelText("Open chat actions"));
    await user.click(screen.getByRole("menuitem", { name: "Saved prompts" }));
    await user.click(screen.getByRole("menuitem", { name: "Insert saved prompt: Summary" }));

    await waitFor(() => {
      expect((screen.getByLabelText("Chat Input") as HTMLTextAreaElement).value).toBe(
        "Please summarize this table",
      );
    });
    expect(markUsedMutate).toHaveBeenCalledWith("p1");
    expect(sendMutate).not.toHaveBeenCalled();
  });

  it("opens the variable dialog for prompts with variables and inserts after confirm", async () => {
    savedPromptsRef.current = [
      makePrompt({ id: "p2", name: "Attrition", body: "Analyze {department}", variables: ["department"] }),
    ];
    const user = userEvent.setup();
    renderInput();

    await user.click(screen.getByLabelText("Open chat actions"));
    await user.click(screen.getByRole("menuitem", { name: "Saved prompts" }));
    await user.click(screen.getByRole("menuitem", { name: "Insert saved prompt: Attrition" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    // Composer unchanged until confirmation.
    expect((screen.getByLabelText("Chat Input") as HTMLTextAreaElement).value).toBe("");

    await user.type(screen.getByLabelText("department"), "Sales");
    await user.click(screen.getByRole("button", { name: "Insert prompt" }));

    await waitFor(() => {
      expect((screen.getByLabelText("Chat Input") as HTMLTextAreaElement).value).toBe("Analyze Sales");
    });
    expect(markUsedMutate).toHaveBeenCalledWith("p2");
  });
});
