import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceCatalogPage } from "../../components/workspace/workspace-catalog-page";
import { useUIStore } from "../../stores/ui-store";
import { useWorkspaceStore } from "../../stores/workspace-store";

vi.mock("../../components/workspace/workspace-catalog-readonly", () => ({
  WorkspaceCatalogReadonly: () => <div>Catalog contents</div>,
}));

describe("WorkspaceCatalogPage", () => {
  beforeEach(() => {
    useUIStore.setState({ chatSidebarOpen: false, activePanel: "catalog" });
    useWorkspaceStore.setState({
      activeWorkspaceId: "workspace-1",
      workspaces: [
        {
          id: "workspace-1",
          title: "Employee roster analysis",
          createdAt: "2026-08-12T00:00:00.000Z",
          updatedAt: "2026-08-12T00:00:00.000Z",
          nodeCount: 0,
        },
      ],
    });
  });

  it("does not render a control that opens the global sidebar", () => {
    render(<WorkspaceCatalogPage />);

    expect(screen.getByRole("heading", { name: "Workspace Table Catalog" })).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(useUIStore.getState().chatSidebarOpen).toBe(false);
  });
});
