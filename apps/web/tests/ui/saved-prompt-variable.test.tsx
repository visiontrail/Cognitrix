import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SavedPromptVariableDialog } from "../../components/chat/saved-prompts/saved-prompt-variable-dialog";
import { I18nProvider } from "../../lib/i18n/context";
import type { SavedPrompt } from "../../lib/saved-prompts/types";

const prompt: SavedPrompt = {
  id: "p1",
  name: "Attrition",
  body: "Analyze {department} attrition in {month}",
  variables: ["department", "month"],
  capabilities: [],
  usageCount: 0,
  lastUsedAt: null,
  createdAt: "",
  updatedAt: "",
  archivedAt: null,
};

function renderDialog(onConfirm = vi.fn(), onOpenChange = vi.fn()) {
  render(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(SavedPromptVariableDialog, {
        prompt,
        open: true,
        onOpenChange,
        onConfirm,
      }),
    ),
  );
  return { onConfirm, onOpenChange };
}

describe("SavedPromptVariableDialog", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("disables insert until every variable has a value", async () => {
    const user = userEvent.setup();
    const { onConfirm } = renderDialog();

    const insert = screen.getByRole("button", { name: "Insert prompt" });
    expect(insert).toBeDisabled();

    await user.type(screen.getByLabelText("department"), "Sales");
    expect(insert).toBeDisabled();

    await user.type(screen.getByLabelText("month"), "May 2026");
    expect(insert).toBeEnabled();

    await user.click(insert);
    expect(onConfirm).toHaveBeenCalledWith("Analyze Sales attrition in May 2026");
  });

  it("does not confirm when cancelled", async () => {
    const user = userEvent.setup();
    const { onConfirm, onOpenChange } = renderDialog();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
