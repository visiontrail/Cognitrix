import { afterEach, describe, expect, it, vi } from "vitest";

import { WORKSPACE_SELECTION_STORAGE_KEY } from "../../lib/chat/session-storage";
import type { Workspace, WorkspaceNode } from "../../types/workspace";

const workspaces: Workspace[] = [
  {
    id: "workspace-1",
    title: "Top Workspace",
    createdAt: "2026-04-24T00:00:00.000Z",
    updatedAt: "2026-04-24T00:00:00.000Z",
    nodeCount: 0,
  },
  {
    id: "workspace-2",
    title: "Selected Workspace",
    createdAt: "2026-04-25T00:00:00.000Z",
    updatedAt: "2026-04-25T00:00:00.000Z",
    nodeCount: 0,
  },
];

describe("workspace store selection persistence", () => {
  afterEach(() => {
    window.localStorage.clear();
    vi.resetModules();
  });

  it("restores the persisted active workspace instead of falling back to the first workspace", async () => {
    window.localStorage.setItem(
      WORKSPACE_SELECTION_STORAGE_KEY,
      JSON.stringify({ version: 1, activeWorkspaceId: "workspace-2" })
    );
    vi.resetModules();

    const { useWorkspaceStore } = await import("../../stores/workspace-store");

    expect(useWorkspaceStore.getState().activeWorkspaceId).toBe("workspace-2");

    useWorkspaceStore.getState().setWorkspaces(workspaces);

    expect(useWorkspaceStore.getState().activeWorkspaceId).toBe("workspace-2");
  });

  it("clears a persisted active workspace when it no longer exists", async () => {
    window.localStorage.setItem(
      WORKSPACE_SELECTION_STORAGE_KEY,
      JSON.stringify({ version: 1, activeWorkspaceId: "missing-workspace" })
    );
    vi.resetModules();

    const { useWorkspaceStore } = await import("../../stores/workspace-store");

    useWorkspaceStore.getState().setWorkspaces(workspaces);

    expect(useWorkspaceStore.getState().activeWorkspaceId).toBeNull();
  });

  it("persists changes when users select another workspace", async () => {
    vi.resetModules();

    const { useWorkspaceStore } = await import("../../stores/workspace-store");

    useWorkspaceStore.getState().setActiveWorkspace("workspace-2");

    expect(JSON.parse(window.localStorage.getItem(WORKSPACE_SELECTION_STORAGE_KEY) ?? "{}")).toEqual({
      version: 1,
      activeWorkspaceId: "workspace-2",
    });
  });

  it("removes grouped descendants and their connected edges during batch deletion", async () => {
    vi.resetModules();
    const { useWorkspaceStore } = await import("../../stores/workspace-store");
    const nodes: WorkspaceNode[] = [
      sectionNode("group-1", 10, 20, 300, 200),
      chartNode("chart-1", 24, 28, "group-1"),
      chartNode("chart-2", 500, 80),
    ];

    useWorkspaceStore.setState({
      activeWorkspaceId: "workspace-1",
      nodes,
      edges: [
        { id: "edge-1", source: "chart-1", target: "chart-2" },
        { id: "edge-2", source: "chart-2", target: "missing-node" },
      ],
      hasUnsavedChanges: false,
    });

    useWorkspaceStore.getState().removeNodes(["group-1"]);

    expect(useWorkspaceStore.getState().nodes.map((node) => node.id)).toEqual(["chart-2"]);
    expect(useWorkspaceStore.getState().edges).toEqual([
      { id: "edge-2", source: "chart-2", target: "missing-node" },
    ]);
    expect(useWorkspaceStore.getState().hasUnsavedChanges).toBe(true);
  });

  it("groups selected nodes under a section while preserving their absolute positions", async () => {
    vi.resetModules();
    const { useWorkspaceStore } = await import("../../stores/workspace-store");
    useWorkspaceStore.setState({
      activeWorkspaceId: "workspace-1",
      nodes: [chartNode("chart-1", 100, 100), chartNode("chart-2", 260, 160, undefined, 120, 90)],
      edges: [],
      hasUnsavedChanges: false,
    });

    const groupId = useWorkspaceStore.getState().groupNodes(["chart-1", "chart-2"], "Selected group");
    const state = useWorkspaceStore.getState();
    const group = state.nodes.find((node) => node.id === groupId);
    const firstChild = state.nodes.find((node) => node.id === "chart-1");
    const secondChild = state.nodes.find((node) => node.id === "chart-2");

    expect(group?.data).toMatchObject({ type: "section", title: "Selected group", width: 336, height: 206 });
    expect(group?.position).toEqual({ x: 72, y: 72 });
    expect(firstChild).toMatchObject({
      parentId: groupId,
      extent: "parent",
      position: { x: 28, y: 28 },
    });
    expect(secondChild).toMatchObject({
      parentId: groupId,
      extent: "parent",
      position: { x: 188, y: 88 },
    });
    expect(state.hasUnsavedChanges).toBe(true);
  });

  it("ungroups a section and restores child nodes to absolute canvas coordinates", async () => {
    vi.resetModules();
    const { useWorkspaceStore } = await import("../../stores/workspace-store");
    useWorkspaceStore.setState({
      activeWorkspaceId: "workspace-1",
      nodes: [
        sectionNode("group-1", 72, 72, 336, 206),
        chartNode("chart-1", 28, 28, "group-1"),
        chartNode("chart-2", 188, 88, "group-1", 120, 90),
      ],
      edges: [],
      hasUnsavedChanges: false,
    });

    useWorkspaceStore.getState().ungroupNodes(["group-1"]);

    expect(useWorkspaceStore.getState().nodes.map((node) => node.id)).toEqual(["chart-1", "chart-2"]);
    expect(useWorkspaceStore.getState().nodes[0]).toMatchObject({
      parentId: undefined,
      extent: undefined,
      position: { x: 100, y: 100 },
    });
    expect(useWorkspaceStore.getState().nodes[1]).toMatchObject({
      parentId: undefined,
      extent: undefined,
      position: { x: 260, y: 160 },
    });
    expect(useWorkspaceStore.getState().hasUnsavedChanges).toBe(true);
  });
});

function chartNode(
  id: string,
  x: number,
  y: number,
  parentId?: string,
  width = 100,
  height = 80
): WorkspaceNode {
  return {
    id,
    type: "chartNode",
    parentId,
    extent: parentId ? "parent" : undefined,
    position: { x, y },
    width,
    height,
    data: {
      type: "chart",
      assetId: id,
      title: id,
      chartType: "bar",
      width,
      height,
      spec: {
        chartType: "bar",
        title: id,
        echartsOption: { __rows__: [{ value: 1 }] },
      },
    },
  };
}

function sectionNode(id: string, x: number, y: number, width: number, height: number): WorkspaceNode {
  return {
    id,
    type: "sectionNode",
    position: { x, y },
    width,
    height,
    data: {
      type: "section",
      title: id,
      width,
      height,
    },
  };
}
