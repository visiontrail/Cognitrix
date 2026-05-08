"use client";

import { memo, useState, useCallback } from "react";
import { type NodeProps } from "@xyflow/react";
import { GripVertical, Trash2, Pencil, Check, X, Copy } from "lucide-react";
import { ChartPreview } from "@/components/charts/chart-preview";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useI18n } from "@/lib/i18n/context";
import { useWorkspaceStore } from "@/stores/workspace-store";
import { generateId } from "@/lib/utils";
import type { ChartNodeData } from "@/types/workspace";
import { ResizableNode } from "./resizable-node";

const DEFAULT_CHART_NODE_WIDTH = 520;
const DEFAULT_CHART_NODE_HEIGHT = 380;
const MIN_CHART_NODE_WIDTH = 320;
const MIN_CHART_NODE_HEIGHT = 260;
const CHART_NODE_HEADER_HEIGHT = 48;

function ChartNodeComponent({ id, data, selected, width, height }: NodeProps) {
  const { t } = useI18n();
  const nodeData = data as unknown as ChartNodeData;
  const updateNode = useWorkspaceStore((s) => s.updateNode);
  const removeNode = useWorkspaceStore((s) => s.removeNode);
  const addNode = useWorkspaceStore((s) => s.addNode);
  const nodes = useWorkspaceStore((s) => s.nodes);

  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(nodeData.title);

  const handleSaveTitle = useCallback(() => {
    updateNode(id, { data: { ...nodeData, title: editTitle } as any });
    setIsEditing(false);
  }, [id, nodeData, editTitle, updateNode]);

  const handleDuplicate = useCallback(() => {
    const currentNode = nodes.find((n) => n.id === id);
    if (!currentNode) return;

    const duplicateWidth =
      currentNode.width ?? currentNode.measured?.width ?? nodeData.width ?? DEFAULT_CHART_NODE_WIDTH;
    const duplicateHeight =
      currentNode.height ?? currentNode.measured?.height ?? nodeData.height ?? DEFAULT_CHART_NODE_HEIGHT;

    addNode({
      id: `node-${generateId()}`,
      type: "chartNode",
      position: { x: currentNode.position.x + 30, y: currentNode.position.y + 30 },
      width: duplicateWidth,
      height: duplicateHeight,
      initialWidth: duplicateWidth,
      initialHeight: duplicateHeight,
      data: { ...nodeData, width: duplicateWidth, height: duplicateHeight },
    });
  }, [id, nodeData, nodes, addNode]);

  const nodeWidth = width ?? nodeData.width ?? DEFAULT_CHART_NODE_WIDTH;
  const nodeHeight = height ?? nodeData.height ?? DEFAULT_CHART_NODE_HEIGHT;
  const chartHeight = Math.max(nodeHeight - CHART_NODE_HEADER_HEIGHT, 180);

  return (
    <div
      className={`relative bg-ivory rounded-comfortable border shadow-whisper transition-shadow ${
        selected ? "border-terracotta shadow-[0px_0px_0px_2px_#c96442]" : "border-border-cream"
      }`}
      style={{
        width: nodeWidth,
        height: nodeHeight,
      }}
    >
      <ResizableNode
        id={id}
        selected={selected}
        minWidth={MIN_CHART_NODE_WIDTH}
        minHeight={MIN_CHART_NODE_HEIGHT}
      />

      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border-cream bg-ivory cursor-grab">
        <GripVertical className="canvas-export-ignore w-4 h-4 text-stone-gray shrink-0" />

        {isEditing ? (
          <div className="flex items-center gap-1 flex-1 min-w-0">
            <Input
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              className="h-6 text-xs"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSaveTitle();
                if (e.key === "Escape") {
                  setEditTitle(nodeData.title);
                  setIsEditing(false);
                }
              }}
            />
            <Button variant="ghost" size="icon-sm" onClick={handleSaveTitle}>
              <Check className="w-3 h-3 text-terracotta" />
            </Button>
            <Button variant="ghost" size="icon-sm" onClick={() => {
              setEditTitle(nodeData.title);
              setIsEditing(false);
            }}>
              <X className="w-3 h-3" />
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <span className="text-caption font-medium text-near-black truncate">
              {nodeData.title}
            </span>
            <Badge variant="outline" className="shrink-0 text-[10px]">
              {nodeData.chartType}
            </Badge>
          </div>
        )}

        <div className="canvas-export-ignore nodrag flex items-center gap-0.5 shrink-0">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => setIsEditing(true)}
                aria-label={t("workspace.node.editChartTitle", { title: nodeData.title })}
              >
                <Pencil className="w-3 h-3" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("workspace.node.edit")}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={handleDuplicate}
                aria-label={t("workspace.node.duplicateChart", { title: nodeData.title })}
              >
                <Copy className="w-3 h-3" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("workspace.node.duplicate")}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => removeNode(id)}
                className="hover:text-error-crimson"
                aria-label={t(
                  nodeData.chartType === "table" ? "workspace.node.deleteTable" : "workspace.node.deleteChart",
                  { title: nodeData.title }
                )}
              >
                <Trash2 className="w-3 h-3" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("workspace.node.delete")}</TooltipContent>
          </Tooltip>
        </div>
      </div>

      {/* Chart */}
      <div className="p-1">
        <ChartPreview
          spec={nodeData.spec}
          height={chartHeight}
        />
      </div>
    </div>
  );
}

export const ChartNode = memo(ChartNodeComponent);
