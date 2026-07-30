import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { IngestionSetupCard } from "../../components/workspace/ingestion-setup-card";
import { DEFAULT_LOCALE, DICTIONARY } from "../../lib/i18n/dictionary";

// Read the copy from the dictionary: the card is localized, and wording edits
// (e.g. "Human Label" -> "Display Name") should not break this test.
const copy = DICTIONARY[DEFAULT_LOCALE];

const DEFAULT_SEED = {
  businessType: "roster" as const,
  tableName: "employee_roster",
  humanLabel: "Employee Roster",
  writeMode: "new_table" as const,
  timeGrain: "none" as const,
  primaryKeys: [],
  matchColumns: [],
  isActiveTarget: true,
  description: "Stores employee master uploads.",
};

describe("IngestionSetupCard", () => {
  it("submits business-facing setup and preserves hidden technical defaults", async () => {
    const onConfirm = vi.fn();
    render(<IngestionSetupCard initialSeed={DEFAULT_SEED} onConfirm={onConfirm} />);

    await userEvent.clear(screen.getByLabelText(copy["ingestion.setup.humanLabel"]));
    await userEvent.type(screen.getByLabelText(copy["ingestion.setup.humanLabel"]), "  Employee Master  ");
    await userEvent.clear(screen.getByLabelText(copy["ingestion.setup.purpose"]));
    await userEvent.type(screen.getByLabelText(copy["ingestion.setup.purpose"]), "  Stores workforce master data.  ");
    await userEvent.click(screen.getByRole("button", { name: copy["ingestion.setup.apply"] }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm).toHaveBeenCalledWith(
      expect.objectContaining({
        tableName: "employee_roster",
        humanLabel: "Employee Master",
        description: "Stores workforce master data.",
        primaryKeys: [],
        matchColumns: [],
      })
    );
  });

  it("shows validation error when human label is empty", async () => {
    const onConfirm = vi.fn();
    render(
      <IngestionSetupCard
        initialSeed={{
          ...DEFAULT_SEED,
          humanLabel: "",
        }}
        onConfirm={onConfirm}
      />
    );

    await userEvent.click(screen.getByRole("button", { name: copy["ingestion.setup.apply"] }));

    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByText(copy["ingestion.setup.validation.humanLabelRequired"])).toBeInTheDocument();
  });
});
