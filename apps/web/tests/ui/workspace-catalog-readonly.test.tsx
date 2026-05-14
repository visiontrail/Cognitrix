import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const deleteMutateAsync = vi.fn();
const refetchPreview = vi.fn();

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock("../../hooks/use-workspace", () => ({
  useWorkspaceCatalog: (workspaceId: string) => {
    if (workspaceId === "ws-empty") {
      return { isLoading: false, data: [] };
    }
    return {
      isLoading: false,
      data: [
        {
          id: "catalog-1",
          workspaceId: workspaceId,
          tableName: "employee_roster",
          humanLabel: "Employees Roster",
          businessType: "roster",
          writeMode: "new_table",
          timeGrain: "none",
          isActiveTarget: true,
          primaryKeys: [],
          matchColumns: [],
          description: "Stores employee master data.",
          createdAt: "2026-04-20T00:00:00.000Z",
          updatedAt: "2026-04-20T00:00:00.000Z",
        },
        {
          id: "catalog-2",
          workspaceId: workspaceId,
          tableName: "project_progress",
          humanLabel: "Project Progress",
          businessType: "project_progress",
          writeMode: "update_existing",
          timeGrain: "none",
          isActiveTarget: false,
          primaryKeys: ["project_id"],
          matchColumns: ["project_id"],
          description: "Tracks sprint progress uploads.",
          createdAt: "2026-04-20T00:00:00.000Z",
          updatedAt: "2026-04-20T00:00:00.000Z",
        },
      ],
    };
  },
  useWorkspaceCatalogDataPreview: (_workspaceId: string, catalogId: string | null) => {
    if (!catalogId) {
      return {
        isLoading: false,
        isFetching: false,
        isError: false,
        data: null,
        refetch: refetchPreview,
      };
    }
    return {
      isLoading: false,
      isFetching: false,
      isError: false,
      refetch: refetchPreview,
      data: {
        entry: {
          id: catalogId,
          workspaceId: "ws-1",
          tableName: "employee_roster",
          humanLabel: "Employees Roster",
          businessType: "roster",
          writeMode: "new_table",
          timeGrain: "none",
          isActiveTarget: true,
          primaryKeys: [],
          matchColumns: [],
          description: "Stores employee master data.",
          createdAt: "2026-04-20T00:00:00.000Z",
          updatedAt: "2026-04-20T00:00:00.000Z",
        },
        table: "employee_roster",
        rowCount: 1,
        limit: 100,
        offset: 0,
        hasMore: false,
        columns: [
          { name: "employee_id", type: "VARCHAR", nullable: true, primaryKey: false },
          { name: "department", type: "VARCHAR", nullable: true, primaryKey: false },
        ],
        rows: [{ employee_id: "E001", department: "HR" }],
      },
    };
  },
  useDeleteWorkspaceCatalogEntry: () => ({
    isPending: false,
    mutateAsync: deleteMutateAsync,
  }),
}));

import { WorkspaceCatalogReadonly } from "../../components/workspace/workspace-catalog-readonly";

describe("WorkspaceCatalogReadonly", () => {
  beforeEach(() => {
    deleteMutateAsync.mockReset();
    refetchPreview.mockReset();
    deleteMutateAsync.mockResolvedValue(undefined);
  });

  it("renders business-purpose catalog entries for a workspace", async () => {
    render(<WorkspaceCatalogReadonly workspaceId="ws-1" />);

    expect(await screen.findByText("Employees Roster")).toBeInTheDocument();
    expect(screen.getByText("Stores employee master data.")).toBeInTheDocument();
    expect(screen.getByText("Project Progress")).toBeInTheDocument();
    expect(screen.getByText("Tracks sprint progress uploads.")).toBeInTheDocument();
    expect(screen.getByText("Planned")).toBeInTheDocument();
    expect(screen.getByText("AI Inferred")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("deletes a catalog entry after confirmation", async () => {
    render(<WorkspaceCatalogReadonly workspaceId="ws-1" />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Delete table intent: Employees Roster" })
    );
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(deleteMutateAsync).toHaveBeenCalledWith({
        workspaceId: "ws-1",
        catalogId: "catalog-1",
      });
    });
  });

  it("opens a raw data preview when a catalog entry is clicked", async () => {
    render(<WorkspaceCatalogReadonly workspaceId="ws-1" />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Open raw data for Employees Roster" })
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("employee_id")).toBeInTheDocument();
    expect(screen.getByText("VARCHAR")).toBeInTheDocument();
    expect(screen.getByText("E001")).toBeInTheDocument();
    expect(screen.getByText("HR")).toBeInTheDocument();
  });

  it("renders empty state when workspace has no catalog entries", async () => {
    render(<WorkspaceCatalogReadonly workspaceId="ws-empty" />);

    expect(
      await screen.findByText("No table intents yet. Start by listing the business tables you expect to upload.")
    ).toBeInTheDocument();
    expect(screen.queryByText("Add Table Intent")).not.toBeInTheDocument();
  });
});
