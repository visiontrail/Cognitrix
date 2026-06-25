import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SavedPromptEditorDialog } from "../../components/chat/saved-prompts/saved-prompt-editor-dialog";
import { I18nProvider } from "../../lib/i18n/context";
import * as api from "../../lib/saved-prompts/api";

vi.mock("../../lib/saved-prompts/api", () => ({
  SavedPromptApiError: class extends Error {
    code?: string;
    status: number;
    constructor(message: string, status = 400, code?: string) {
      super(message);
      this.status = status;
      this.code = code;
    }
  },
  createSavedPrompt: vi.fn(),
  updateSavedPrompt: vi.fn(),
  listSavedPrompts: vi.fn(async () => []),
  archiveSavedPrompt: vi.fn(),
  markSavedPromptUsed: vi.fn(),
}));

function renderEditor() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    React.createElement(
      QueryClientProvider,
      { client: queryClient },
      React.createElement(
        I18nProvider,
        null,
        React.createElement(SavedPromptEditorDialog, {
          open: true,
          prompt: null,
          onOpenChange: vi.fn(),
        }),
      ),
    ),
  );
}

describe("SavedPromptEditorDialog validation", () => {
  beforeEach(() => {
    vi.mocked(api.createSavedPrompt).mockReset();
    window.localStorage.clear();
  });

  it("disables save when name or body is empty", async () => {
    const user = userEvent.setup();
    renderEditor();

    const save = screen.getByRole("button", { name: "Save prompt" });
    expect(save).toBeDisabled();

    await user.type(screen.getByLabelText("Name"), "My prompt");
    expect(save).toBeDisabled();

    await user.type(screen.getByLabelText("Prompt"), "do something");
    expect(save).toBeEnabled();
  });

  it("shows an error and disables save for an invalid variable", async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.type(screen.getByLabelText("Name"), "Bad");
    // Braces collide with user-event key syntax; set the value directly.
    fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "Compare {2026_month}" } });

    expect(await screen.findByRole("alert")).toHaveTextContent("2026_month");
    expect(screen.getByRole("button", { name: "Save prompt" })).toBeDisabled();
    expect(api.createSavedPrompt).not.toHaveBeenCalled();
  });

  it("submits a valid prompt", async () => {
    vi.mocked(api.createSavedPrompt).mockResolvedValue({
      id: "p1",
      name: "Good",
      body: "Analyze {department}",
      variables: ["department"],
      capabilities: [],
      usageCount: 0,
      lastUsedAt: null,
      createdAt: "",
      updatedAt: "",
      archivedAt: null,
    });
    const user = userEvent.setup();
    renderEditor();

    await user.type(screen.getByLabelText("Name"), "Good");
    fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "Analyze {department}" } });
    await user.click(screen.getByRole("button", { name: "Save prompt" }));

    await waitFor(() => {
      expect(api.createSavedPrompt).toHaveBeenCalled();
    });
    // TanStack passes a second context arg to the mutationFn; assert the payload.
    expect(vi.mocked(api.createSavedPrompt).mock.calls[0][0]).toEqual({
      name: "Good",
      body: "Analyze {department}",
      capabilities: [],
    });
  });
});
