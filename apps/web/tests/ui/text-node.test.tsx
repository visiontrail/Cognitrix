import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TextNode } from "../../components/workspace/nodes/text-node";
import { useWorkspaceStore } from "../../stores/workspace-store";
import type { TextNodeData, WorkspaceNode } from "../../types/workspace";

vi.mock("../../components/workspace/nodes/resizable-node", () => ({
  ResizableNode: () => <div data-testid="resize-controls" />,
}));

const textNodeData: TextNodeData = {
  type: "text",
  content: "Revenue grew steadily.",
  fontSize: 18,
  fontWeight: "normal",
  color: "#3f3d39",
  width: 480,
  height: 220,
};

function renderTextNode(selected = true, data: TextNodeData = textNodeData) {
  return render(
    <TextNode
      {...({
        id: "node-text",
        data,
        selected,
        type: "textNode",
        width: data.width,
        height: data.height,
        xPos: 0,
        yPos: 0,
        zIndex: 0,
        isConnectable: false,
        dragging: false,
      } as any)}
    />
  );
}

describe("TextNode", () => {
  beforeEach(() => {
    useWorkspaceStore.setState({
      activeWorkspaceId: "ws-test",
      nodes: [
        {
          id: "node-text",
          type: "textNode",
          position: { x: 0, y: 0 },
          width: 480,
          height: 220,
          data: textNodeData,
        },
      ] as WorkspaceNode[],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      canvasFormat: { id: "infinite" },
      canvasBackgrounds: {},
      hasUnsavedChanges: false,
    });
  });

  afterEach(() => {
    useWorkspaceStore.setState({
      workspaces: [],
      activeWorkspaceId: null,
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      canvasFormat: { id: "infinite" },
      canvasBackgrounds: {},
      hasUnsavedChanges: false,
    });
  });

  it("inverts dark text on dark canvas backgrounds", () => {
    useWorkspaceStore.setState({
      canvasFormat: { id: "infinite" },
      canvasBackgrounds: { infinite: "graphite" },
    });

    renderTextNode(false);

    expect(screen.getByText("Revenue grew steadily.")).toHaveStyle({ color: "#fffef9" });
  });

  it("keeps editing open when the text area blurs for resize handles", async () => {
    renderTextNode();

    await userEvent.click(screen.getByRole("button", { name: "Edit text block" }));
    const editor = screen.getByRole("textbox");

    fireEvent.blur(editor);

    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.getByTestId("resize-controls")).toBeInTheDocument();
  });

  it("expands the editor overlay enough to cover compact heading nodes", async () => {
    renderTextNode(true, {
      ...textNodeData,
      content: "标题",
      fontSize: 34,
      fontWeight: "bold",
      width: 620,
      height: 88,
    });

    await userEvent.click(screen.getByRole("button", { name: "Edit text block" }));

    const editor = screen.getByTestId("text-node-editor");
    expect(parseFloat(editor.style.height)).toBeGreaterThan(150);
  });
});
