import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MessageItem } from "../../components/chat/message-item";
import { TooltipProvider } from "../../components/ui/tooltip";
import { I18nProvider } from "../../lib/i18n/context";
import type { SavedPrompt } from "../../lib/saved-prompts/types";
import type { ChatMessage } from "../../types/chat";

const { copyTextToClipboardMock, createSavedPromptMock } = vi.hoisted(() => ({
  copyTextToClipboardMock: vi.fn<(text: string) => Promise<boolean>>(),
  createSavedPromptMock: vi.fn(),
}));

vi.mock("@/lib/clipboard", () => ({
  copyTextToClipboard: (text: string) => copyTextToClipboardMock(text),
}));

vi.mock("@/lib/saved-prompts/api", () => ({
  SavedPromptApiError: class extends Error {
    code?: string;
    status: number;
    constructor(message: string, status = 400, code?: string) {
      super(message);
      this.status = status;
      this.code = code;
    }
  },
  createSavedPrompt: (...args: unknown[]) => createSavedPromptMock(...args),
  updateSavedPrompt: vi.fn(),
  listSavedPrompts: vi.fn(async () => []),
  archiveSavedPrompt: vi.fn(),
  markSavedPromptUsed: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

function renderMessage(message: ChatMessage) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <TooltipProvider>
          <MessageItem message={message} />
        </TooltipProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

function makeMessage(role: ChatMessage["role"], content: string): ChatMessage {
  return {
    id: `${role}-1`,
    sessionId: "session-1",
    role,
    content,
    timestamp: "2026-06-26T00:00:00Z",
  };
}

function makeSavedPrompt(input: { name: string; body: string }): SavedPrompt {
  return {
    id: "prompt-1",
    name: input.name,
    body: input.body,
    variables: [],
    capabilities: [],
    usageCount: 0,
    lastUsedAt: null,
    createdAt: "2026-06-26T00:00:00Z",
    updatedAt: "2026-06-26T00:00:00Z",
    archivedAt: null,
  };
}

describe("MessageItem prompt actions", () => {
  beforeEach(() => {
    copyTextToClipboardMock.mockReset().mockResolvedValue(true);
    createSavedPromptMock.mockReset();
    window.localStorage.clear();
  });

  it("opens a prefilled create dialog from a user message and saves through the saved prompt API", async () => {
    const content = "Show attrition by department";
    createSavedPromptMock.mockResolvedValue(makeSavedPrompt({ name: content, body: content }));
    const user = userEvent.setup();

    renderMessage(makeMessage("user", content));

    await user.click(screen.getByRole("button", { name: "Save this prompt" }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue(content);
    expect(screen.getByLabelText("Prompt")).toHaveValue(content);

    await user.click(screen.getByRole("button", { name: "Save prompt" }));

    await waitFor(() => expect(createSavedPromptMock).toHaveBeenCalledTimes(1));
    expect(createSavedPromptMock.mock.calls[0][0]).toEqual({
      name: content,
      body: content,
      capabilities: [],
    });
  });

  it("copies the exact user message text", async () => {
    const content = "Compare HR and PM turnover\nby month";
    const user = userEvent.setup();

    renderMessage(makeMessage("user", content));

    await user.click(screen.getByRole("button", { name: "Copy this prompt" }));

    await waitFor(() => expect(copyTextToClipboardMock).toHaveBeenCalledTimes(1));
    expect(copyTextToClipboardMock).toHaveBeenCalledWith(content);
  });

  it("does not expose prompt actions on assistant messages", () => {
    renderMessage(makeMessage("assistant", "Here is the analysis."));

    expect(screen.queryByRole("button", { name: "Save this prompt" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy this prompt" })).not.toBeInTheDocument();
  });
});
