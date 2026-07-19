import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentRunOutlineCard } from "../../components/chat/agent-run-outline-card";
import { getAutoApprovePreference } from "../../lib/chat/agent-canvas";
import { I18nProvider } from "../../lib/i18n/context";
import type { AgentRunOutline } from "../../types/chat";

const { sendMutate } = vi.hoisted(() => ({
  sendMutate: vi.fn(),
}));

vi.mock("../../hooks/use-chat", () => ({
  useSendMessage: () => ({ mutate: sendMutate, isPending: false }),
}));

function outlineFixture(overrides: Partial<AgentRunOutline> = {}): AgentRunOutline {
  return {
    confirmationId: "dash-1",
    runId: "acr-1",
    pageTitle: "销售概览",
    proposedChartCount: 2,
    maxChartCount: 12,
    sections: [
      {
        key: "s1",
        title: "概览",
        items: [
          { key: "c1", kind: "chart", title: "总人数", chartType: "single_value", sizePreset: "kpi" },
          { key: "c2", kind: "chart", title: "部门人数", chartType: "bar", sizePreset: "half" },
          { key: "t1", kind: "text", style: "body", content: "说明文字" },
        ],
      },
    ],
    ...overrides,
  };
}

function renderCard(outline: AgentRunOutline) {
  return render(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(AgentRunOutlineCard, { sessionId: "s1", outline }),
    ),
  );
}

describe("AgentRunOutlineCard", () => {
  beforeEach(() => {
    sendMutate.mockReset();
    window.localStorage.clear();
  });

  it("approves the full selection", async () => {
    const user = userEvent.setup();
    renderCard(outlineFixture());

    expect(screen.getByText("销售概览")).toBeInTheDocument();
    expect(screen.getByText("说明文字")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Generate 2 charts/ }));

    expect(sendMutate).toHaveBeenCalledTimes(1);
    expect(sendMutate.mock.calls[0][0]).toMatchObject({
      sessionId: "s1",
      agentRunConfirmation: {
        confirmationId: "dash-1",
        action: "confirm",
      },
    });
    // Full selection omits the key list (backend treats it as "all").
    expect(sendMutate.mock.calls[0][0].agentRunConfirmation.selectedItemKeys).toBeUndefined();
  });

  it("sends only the selected chart keys after deselection", async () => {
    const user = userEvent.setup();
    renderCard(outlineFixture());

    const checkboxes = screen.getAllByRole("checkbox");
    // First two checkboxes are the chart items (the third is skip-approval).
    await user.click(checkboxes[0]);
    await user.click(screen.getByRole("button", { name: /Generate 1 charts/ }));

    expect(sendMutate).toHaveBeenCalledTimes(1);
    expect(sendMutate.mock.calls[0][0].agentRunConfirmation).toMatchObject({
      confirmationId: "dash-1",
      action: "confirm",
      selectedItemKeys: ["c2"],
    });
  });

  it("cancels the outline", async () => {
    const user = userEvent.setup();
    renderCard(outlineFixture());

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(sendMutate).toHaveBeenCalledTimes(1);
    expect(sendMutate.mock.calls[0][0].agentRunConfirmation).toMatchObject({
      confirmationId: "dash-1",
      action: "cancel",
    });
  });

  it("persists the skip-approval preference on approve", async () => {
    const user = userEvent.setup();
    renderCard(outlineFixture());

    expect(getAutoApprovePreference()).toBe(false);
    await user.click(screen.getByLabelText("Skip this confirmation next time"));
    await user.click(screen.getByRole("button", { name: /Generate 2 charts/ }));
    expect(getAutoApprovePreference()).toBe(true);
  });

  it("renders an informational card without buttons when auto-approved", () => {
    renderCard(outlineFixture({ approved: true }));

    expect(screen.getByText(/auto-approved/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Generate/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });
});
