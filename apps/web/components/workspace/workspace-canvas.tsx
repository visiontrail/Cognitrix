"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Panel,
  ViewportPortal,
  useNodesState,
  useEdgesState,
  applyNodeChanges,
  applyEdgeChanges,
  type NodeChange,
  type EdgeChange,
  type NodeTypes,
  type Node,
  type Edge,
  BackgroundVariant,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Layers, Trash2, Ungroup } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n/context";
import { useWorkspaceStore } from "@/stores/workspace-store";
import {
  getCanvasFormatPreset,
  getCanvasPageCount,
  getCanvasPageRects,
} from "@/lib/workspace/canvas-formats";
import { ChartNode } from "./nodes/chart-node";
import { TextNode } from "./nodes/text-node";
import { StickyNoteNode } from "./nodes/sticky-note-node";
import { DividerNode } from "./nodes/divider-node";
import { SectionNode } from "./nodes/section-node";
import { WebDesignCanvas } from "./web-design-canvas";
import type { WorkspaceNode } from "@/types/workspace";

const nodeTypes: NodeTypes = {
  chartNode: ChartNode,
  textNode: TextNode,
  stickyNoteNode: StickyNoteNode,
  dividerNode: DividerNode,
  sectionNode: SectionNode,
};

function normalizeWorkspaceNodes(nodes: WorkspaceNode[]): Node[] {
  return nodes.map((node) => {
    if (node.type === "textNode") return { ...node, dragHandle: ".text-node-drag-handle" };
    if (node.type === "stickyNoteNode") return { ...node, dragHandle: ".sticky-note-drag-handle" };
    if (node.type === "dividerNode") return { ...node, dragHandle: ".divider-node-drag-handle" };
    if (node.type === "sectionNode") return { ...node, dragHandle: ".section-node-drag-handle" };
    return node;
  }) as Node[];
}

export function WorkspaceCanvas() {
  const { t } = useI18n();
  const storeNodes = useWorkspaceStore((s) => s.nodes);
  const storeEdges = useWorkspaceStore((s) => s.edges);
  const storeViewport = useWorkspaceStore((s) => s.viewport);
  const canvasFormat = useWorkspaceStore((s) => s.canvasFormat);
  const canvasPages = useWorkspaceStore((s) => s.canvasPages);
  const setStoreNodes = useWorkspaceStore((s) => s.setNodes);
  const setViewport = useWorkspaceStore((s) => s.setViewport);
  const removeNodes = useWorkspaceStore((s) => s.removeNodes);
  const groupNodes = useWorkspaceStore((s) => s.groupNodes);
  const ungroupNodes = useWorkspaceStore((s) => s.ungroupNodes);

  const [nodes, setNodes] = useNodesState(normalizeWorkspaceNodes(storeNodes));
  const [edges, setEdges] = useEdgesState(storeEdges as Edge[]);
  const [selectedNodes, setSelectedNodes] = useState<Node[]>([]);
  const nodesRef = useRef<Node[]>(normalizeWorkspaceNodes(storeNodes));

  const canvasPreset = getCanvasFormatPreset(canvasFormat.id);
  const pageCount = getCanvasPageCount(canvasFormat.id, canvasPages);
  const pageRects = getCanvasPageRects(canvasPreset, pageCount);

  useEffect(() => {
    const nextNodes = normalizeWorkspaceNodes(storeNodes);
    nodesRef.current = nextNodes;
    setNodes(nextNodes);
  }, [storeNodes, setNodes]);

  useEffect(() => {
    setEdges(storeEdges as Edge[]);
  }, [storeEdges, setEdges]);

  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      const nextNodes = applyNodeChanges(changes, nodesRef.current);
      nodesRef.current = nextNodes;
      setNodes(nextNodes);

      const hasMeaningfulChange = changes.some(
        (c) => c.type === "position" || c.type === "remove" || c.type === "dimensions"
      );
      if (hasMeaningfulChange) {
        setStoreNodes(nextNodes as WorkspaceNode[]);
      }
    },
    [setNodes, setStoreNodes]
  );

  const handleEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      setEdges((eds) => applyEdgeChanges(changes, eds));
    },
    [setEdges]
  );

  const selectedNodeIds = selectedNodes.map((node) => node.id);
  const selectedGroupableCount = selectedNodes.filter((node) => node.data.type !== "section").length;
  const canGroupSelection = selectedGroupableCount >= 2;
  const canUngroupSelection = selectedNodes.some(
    (node) => node.data.type === "section" || Boolean(node.parentId)
  );

  const handleDeleteSelection = useCallback(() => {
    removeNodes(selectedNodeIds);
    setSelectedNodes([]);
  }, [removeNodes, selectedNodeIds]);

  const handleGroupSelection = useCallback(() => {
    const groupId = groupNodes(selectedNodeIds, t("workspace.selection.defaultGroupTitle"));
    if (groupId) setSelectedNodes([]);
  }, [groupNodes, selectedNodeIds, t]);

  const handleUngroupSelection = useCallback(() => {
    ungroupNodes(selectedNodeIds);
    setSelectedNodes([]);
  }, [selectedNodeIds, ungroupNodes]);

  if (canvasFormat.id === "web-design") {
    return <WebDesignCanvas />;
  }

  return (
    <div className="h-full w-full">
      {/* suppress ReactFlow selection outline for text nodes — editing panel provides its own indicator */}
      <style>{`.react-flow__node-textNode { outline: none !important; box-shadow: none !important; }`}</style>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={handleNodesChange}
        onEdgesChange={handleEdgesChange}
        onSelectionChange={({ nodes: nextSelectedNodes }) => setSelectedNodes(nextSelectedNodes)}
        nodeTypes={nodeTypes}
        defaultViewport={storeViewport}
        onViewportChange={setViewport}
        deleteKeyCode={["Backspace", "Delete"]}
        multiSelectionKeyCode="Shift"
        selectionOnDrag
        panOnDrag={[1, 2]}
        minZoom={0.3}
        maxZoom={2}
        snapToGrid
        snapGrid={[10, 10]}
        proOptions={{ hideAttribution: true }}
      >
        {selectedNodes.length > 1 && (
          <Panel position="top-center" className="canvas-export-ignore">
            <div className="flex items-center gap-1 rounded-md border border-border-cream bg-ivory/95 px-2 py-1.5 text-xs text-stone-gray shadow-ring-warm backdrop-blur">
              <span className="px-1.5 font-medium text-near-black">
                {t("workspace.selection.count", { count: selectedNodes.length })}
              </span>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 gap-1.5 px-2"
                disabled={!canGroupSelection}
                onClick={handleGroupSelection}
              >
                <Layers className="h-3.5 w-3.5" />
                {t("workspace.selection.group")}
              </Button>
              {canUngroupSelection && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 gap-1.5 px-2"
                  onClick={handleUngroupSelection}
                >
                  <Ungroup className="h-3.5 w-3.5" />
                  {t("workspace.selection.ungroup")}
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                className="h-7 gap-1.5 px-2 hover:text-error-crimson"
                onClick={handleDeleteSelection}
              >
                <Trash2 className="h-3.5 w-3.5" />
                {t("workspace.selection.delete")}
              </Button>
            </div>
          </Panel>
        )}
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          color="#d1cfc5"
        />
        {pageRects.length > 0 && (
          <ViewportPortal>
            {pageRects.map((rect) => (
              <div
                key={rect.index}
                aria-hidden="true"
                className="workspace-page-frame"
                style={{
                  left: rect.x,
                  top: rect.y,
                  width: rect.width,
                  height: rect.height,
                }}
              >
                {pageCount > 1 && (
                  <span className="workspace-page-number canvas-export-ignore">
                    {t("workspace.page.indicator", {
                      current: rect.index + 1,
                      total: pageCount,
                    })}
                  </span>
                )}
              </div>
            ))}
          </ViewportPortal>
        )}
        <Controls
          showInteractive={false}
        />
        <MiniMap
          nodeColor={() => "#c96442"}
          maskColor="rgba(245, 244, 237, 0.8)"
        />
      </ReactFlow>
    </div>
  );
}
