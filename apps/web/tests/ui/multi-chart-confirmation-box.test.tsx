import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MultiChartConfirmationBox } from "../../components/chat/multi-chart-confirmation-box";
import type { MultiChartConfirmation } from "../../types/chat";

const mutate = vi.fn();

vi.mock("@/hooks/use-chat", () => ({
  useSendMessage: () => ({ mutate, isPending: false }),
}));

const confirmation: MultiChartConfirmation = {
  confirmationId: "mchart-1",
  groupingDimension: "department",
  proposedCount: 3,
  maxChartCount: 2,
  reason: "One chart per department.",
  truncated: true,
  items: [
    { key: "hr", label: "HR", selected: true },
    { key: "pm", label: "PM", selected: false },
    { key: "eng", label: "ENG", selected: false },
  ],
};

describe("MultiChartConfirmationBox", () => {
  beforeEach(() => {
    mutate.mockReset();
  });

  it("submits an adjusted selected chart set", async () => {
    render(<MultiChartConfirmationBox sessionId="session-a" confirmation={confirmation} />);

    expect(screen.getByText("1 selected · max 2")).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("PM"));
    expect(screen.getByText("2 selected · max 2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Generate 2" }));

    expect(mutate).toHaveBeenCalledWith({
      sessionId: "session-a",
      content: "Generate 2 selected charts",
      multiChartConfirmation: {
        confirmationId: "mchart-1",
        action: "adjust",
        selectedItems: [
          { key: "hr", label: "HR" },
          { key: "pm", label: "PM" },
        ],
      },
    });
  });

  it("replays the captured showDataLabels flag on confirm", async () => {
    render(
      <MultiChartConfirmationBox
        sessionId="session-a"
        confirmation={{ ...confirmation, showDataLabels: true }}
      />
    );

    await userEvent.click(screen.getByLabelText("PM"));
    await userEvent.click(screen.getByRole("button", { name: "Generate 2" }));

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({ showDataLabels: true })
    );
  });

  it("blocks confirmation above the maximum and supports cancel", async () => {
    render(<MultiChartConfirmationBox sessionId="session-a" confirmation={confirmation} />);

    await userEvent.click(screen.getByLabelText("PM"));
    await userEvent.click(screen.getByLabelText("ENG"));

    expect(screen.getByRole("button", { name: "Generate 3" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(mutate).toHaveBeenCalledWith({
      sessionId: "session-a",
      content: "Cancel multi-chart generation",
      multiChartConfirmation: {
        confirmationId: "mchart-1",
        action: "cancel",
      },
    });
  });
});
