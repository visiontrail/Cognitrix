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
  PanOnScrollMode,
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
  getCanvasPageStride,
  isBoundedCanvasFormat,
} from "@/lib/workspace/canvas-formats";
import {
  composeCanvasBackgroundStyle,
  resolveCanvasBackgroundPreset,
} from "@/lib/workspace/canvas-backgrounds";
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

// On paged (A4/A3/Letter/16:9) canvases the wheel scrolls the document like
// Word/PowerPoint; zooming moves to the modifier key (⌘ on macOS, Ctrl on
// Windows/Linux) plus wheel, matching those apps.
const ZOOM_ACTIVATION_KEYS = ["Meta", "Control"];

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
  const canvasBackgrounds = useWorkspaceStore((s) => s.canvasBackgrounds);
  const setStoreNodes = useWorkspaceStore((s) => s.setNodes);
  const setViewport = useWorkspaceStore((s) => s.setViewport);
  const removeNodes = useWorkspaceStore((s) => s.removeNodes);
  const groupNodes = useWorkspaceStore((s) => s.groupNodes);
  const ungroupNodes = useWorkspaceStore((s) => s.ungroupNodes);
  const deleteCanvasPage = useWorkspaceStore((s) => s.deleteCanvasPage);

  const [nodes, setNodes] = useNodesState(normalizeWorkspaceNodes(storeNodes));
  const [edges, setEdges] = useEdgesState(storeEdges as Edge[]);
  const [selectedNodes, setSelectedNodes] = useState<Node[]>([]);
  const nodesRef = useRef<Node[]>(normalizeWorkspaceNodes(storeNodes));

  const canvasPreset = getCanvasFormatPreset(canvasFormat.id);
  const pageCount = getCanvasPageCount(canvasFormat.id, canvasPages);
  const pageRects = getCanvasPageRects(canvasPreset, pageCount);
  const isBoundedCanvas = isBoundedCanvasFormat(canvasPreset);

  // The chosen backdrop paints the page surface on bounded canvases (paper /
  // slide) and the full-bleed pane on the infinite canvas. On bounded canvases
  // the surrounding "desk" keeps the neutral ReactFlow dot grid.
  const backgroundPreset = resolveCanvasBackgroundPreset(canvasFormat.id, canvasBackgrounds);
  const backgroundStyle = composeCanvasBackgroundStyle(backgroundPreset);

  // Paper/slide canvases behave like a document: the wheel pans vertically and
  // zoom is gated behind the modifier key. The infinite canvas keeps the
  // default zoom-on-scroll behaviour.
  const scrollPanProps = isBoundedCanvas
    ? {
        zoomOnScroll: false,
        panOnScroll: true,
        panOnScrollMode: PanOnScrollMode.Vertical,
        zoomActivationKeyCode: ZOOM_ACTIVATION_KEYS,
      }
    : {};

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

  const handleDeletePage = useCallback(
    (pageIndex: number) => {
      const stride = getCanvasPageStride(canvasPreset);
      const top = pageIndex * stride;
      const bottom = top + stride;
      const hasContent = nodesRef.current.some((node) => {
        if (node.parentId) return false;
        const y = Number(node.position?.y ?? 0);
        return y >= top && y < bottom;
      });
      if (
        hasContent &&
        typeof window !== "undefined" &&
        !window.confirm(t("workspace.pages.deleteConfirm", { page: pageIndex + 1 }))
      ) {
        return;
      }
      deleteCanvasPage(pageIndex);
    },
    [canvasPreset, deleteCanvasPage, t]
  );

  if (canvasFormat.id === "web-design") {
    return <WebDesignCanvas />;
  }

  return (
    <div className="h-full w-full" style={isBoundedCanvas ? undefined : backgroundStyle}>
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
        {...scrollPanProps}
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
        {/* Bounded canvases keep a neutral "desk" grid behind the pages; the
            infinite canvas is painted full-bleed by the wrapper instead. */}
        {isBoundedCanvas && (
          <Background
            variant={BackgroundVariant.Dots}
            gap={20}
            size={1}
            color="#d1cfc5"
          />
        )}
        {pageRects.length > 0 && (
          <ViewportPortal>
            {pageRects.map((rect) => (
              <div
                key={rect.index}
                aria-hidden="true"
                className={`workspace-page-frame${
                  backgroundPreset.dark ? " workspace-page-frame--dark" : ""
                }`}
                style={{
                  left: rect.x,
                  top: rect.y,
                  width: rect.width,
                  height: rect.height,
                  ...backgroundStyle,
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
            {pageCount > 1 &&
              pageRects.map((rect) => (
                <button
                  key={`delete-${rect.index}`}
                  type="button"
                  className="workspace-page-delete canvas-export-ignore nopan nodrag"
                  style={{ left: rect.x + rect.width - 36, top: rect.y + 8 }}
                  onClick={() => handleDeletePage(rect.index)}
                  title={t("workspace.pages.delete")}
                  aria-label={t("workspace.pages.delete")}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
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
