import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SavedPromptsManager } from "../../components/chat/saved-prompts/saved-prompts-manager";
import { I18nProvider } from "../../lib/i18n/context";
import * as api from "../../lib/saved-prompts/api";
import type { SavedPrompt } from "../../lib/saved-prompts/types";

vi.mock("../../lib/saved-prompts/api", () => ({
  SavedPromptApiError: class extends Error {},
  listSavedPrompts: vi.fn(),
  archiveSavedPrompt: vi.fn(),
  createSavedPrompt: vi.fn(),
  updateSavedPrompt: vi.fn(),
  markSavedPromptUsed: vi.fn(),
}));

function makePrompt(overrides: Partial<SavedPrompt>): SavedPrompt {
  return {
    id: "p1",
    name: "Attrition review",
    body: "Analyze {department} attrition",
    variables: ["department"],
    capabilities: [],
    usageCount: 0,
    lastUsedAt: null,
    createdAt: "",
    updatedAt: "",
    archivedAt: null,
    ...overrides,
  };
}

function renderManager(props: Partial<React.ComponentProps<typeof SavedPromptsManager>> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    React.createElement(
      QueryClientProvider,
      { client: queryClient },
      React.createElement(
        I18nProvider,
        null,
        React.createElement(SavedPromptsManager, {
          open: true,
          onOpenChange: vi.fn(),
          onCreate: vi.fn(),
          onEdit: vi.fn(),
          onInsert: vi.fn(),
          ...props,
        }),
      ),
    ),
  );
}

describe("SavedPromptsManager", () => {
  beforeEach(() => {
    vi.mocked(api.listSavedPrompts).mockReset();
    vi.mocked(api.archiveSavedPrompt).mockReset();
    window.localStorage.clear();
  });

  it("shows the empty state when there are no prompts", async () => {
    vi.mocked(api.listSavedPrompts).mockResolvedValue([]);
    renderManager();
    expect(
      await screen.findByText("No saved prompts yet. Create one to reuse it from the composer."),
    ).toBeInTheDocument();
  });

  it("lists prompts and filters via the search query", async () => {
    vi.mocked(api.listSavedPrompts).mockResolvedValue([makePrompt({})]);
    const user = userEvent.setup();
    renderManager();

    expect(await screen.findByText("Attrition review")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Search saved prompts"), "attrition");
    await waitFor(() => {
      // The backend receives the query (server-side search).
      expect(api.listSavedPrompts).toHaveBeenLastCalledWith({ query: "attrition" });
    });
  });

  it("archives a prompt after delete confirmation", async () => {
    vi.mocked(api.listSavedPrompts).mockResolvedValue([makePrompt({})]);
    vi.mocked(api.archiveSavedPrompt).mockResolvedValue(makePrompt({ archivedAt: "now" }));
    const user = userEvent.setup();
    renderManager();

    await screen.findByText("Attrition review");
    await user.click(screen.getByRole("button", { name: "Delete prompt" }));
    // Confirmation row appears with a distinct "Delete" confirm button.
    await user.click(screen.getByText("Delete", { selector: "button" }));

    await waitFor(() => {
      expect(api.archiveSavedPrompt).toHaveBeenCalled();
    });
    expect(vi.mocked(api.archiveSavedPrompt).mock.calls[0][0]).toBe("p1");
  });

  it("calls onInsert when the insert action is clicked", async () => {
    vi.mocked(api.listSavedPrompts).mockResolvedValue([makePrompt({})]);
    const onInsert = vi.fn();
    const user = userEvent.setup();
    renderManager({ onInsert });

    await screen.findByText("Attrition review");
    await user.click(screen.getByRole("button", { name: "Insert" }));
    expect(onInsert).toHaveBeenCalledTimes(1);
  });
});
