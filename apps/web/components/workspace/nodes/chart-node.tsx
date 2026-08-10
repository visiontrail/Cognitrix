"use client";

import { memo, useRef, useState, useCallback } from "react";
import { type NodeProps } from "@xyflow/react";
import { Check, Copy, GripVertical, ImageDown, Pencil, RotateCcw, Trash2, TriangleAlert, WandSparkles, X } from "lucide-react";
import { ChartPreview } from "@/components/charts/chart-preview";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { canCopyPngToClipboard, copyElementAsPngToClipboard } from "@/lib/charts/copy-chart-as-png";
import { useI18n } from "@/lib/i18n/context";
import { useWorkspaceStore } from "@/stores/workspace-store";
import { useUIStore } from "@/stores/ui-store";
import { beginCanvasChartEdit } from "@/lib/chat/canvas-chart-edit";
import { retryAgentRunItem } from "@/lib/chat/agent-canvas";
import { AGENT_ERROR_CHART_TYPE, parseAgentBlockId } from "@/lib/workspace/agent-canvas-layout";
import { applyAgentCanvasWireOp } from "@/lib/workspace/agent-canvas-ops";
import { toChartAsset } from "@/hooks/use-chat";
import { generateId } from "@/lib/utils";
import { toast } from "sonner";
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
  const chartCaptureRef = useRef<HTMLDivElement>(null);
  const updateNode = useWorkspaceStore((s) => s.updateNode);
  const removeNode = useWorkspaceStore((s) => s.removeNode);
  const addNode = useWorkspaceStore((s) => s.addNode);
  const nodes = useWorkspaceStore((s) => s.nodes);
  const isAiEditTarget = useUIStore((s) => s.chartEditTarget?.nodeId === id);

  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(nodeData.title);
  const [isCopying, setIsCopying] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);

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

  const handleCopyAsPng = useCallback(async () => {
    if (!chartCaptureRef.current) {
      toast.error(t("chat.toast.chartAssetNotFound"));
      return;
    }
    if (!canCopyPngToClipboard()) {
      toast.error(t("chat.toast.clipboardImageUnsupported"));
      return;
    }

    setIsCopying(true);
    try {
      await copyElementAsPngToClipboard(chartCaptureRef.current);
      toast.success(t("chat.toast.chartCopiedAsPng"));
    } catch {
      toast.error(t("chat.toast.chartCopyFailed"));
    } finally {
      setIsCopying(false);
    }
  }, [t]);

  const handleEditWithAi = useCallback(() => {
    const result = beginCanvasChartEdit({ nodeId: id, data: nodeData });
    if (result === "no_session") {
      toast.error(t("workspace.node.aiEditNoConversation"));
      return;
    }
    if (result === "no_workspace") {
      toast.error(t("chat.toast.noWorkspace"));
      return;
    }
    toast.success(t("workspace.node.aiEditSelected", { title: nodeData.title }));
  }, [id, nodeData, t]);

  const nodeWidth = width ?? nodeData.width ?? DEFAULT_CHART_NODE_WIDTH;
  const nodeHeight = height ?? nodeData.height ?? DEFAULT_CHART_NODE_HEIGHT;
  const chartHeight = Math.max(nodeHeight - CHART_NODE_HEADER_HEIGHT, 180);
  const retryTarget = nodeData.agentBlockId ? parseAgentBlockId(nodeData.agentBlockId) : null;

  const handleRetry = useCallback(async () => {
    if (!retryTarget || isRetrying) return;
    setIsRetrying(true);
    try {
      const op = await retryAgentRunItem(retryTarget.runId, retryTarget.seq);
      const applied = op
        ? applyAgentCanvasWireOp(op, {
            toAsset: (rawSpec, meta) =>
              toChartAsset(rawSpec, {
                sessionId: "",
                messageId: retryTarget.runId,
                prompt: meta.title,
                assetId: meta.assetId,
                title: meta.title,
              }),
          })
        : false;
      if (applied) toast.success(t("workspace.webDesign.agentError.retrySuccess"));
      else toast.error(t("workspace.webDesign.agentError.retryFailed"));
    } catch {
      toast.error(t("workspace.webDesign.agentError.retryFailed"));
    } finally {
      setIsRetrying(false);
    }
  }, [isRetrying, retryTarget, t]);

  if (nodeData.chartType === AGENT_ERROR_CHART_TYPE) {
    return (
      <div
        data-testid="agent-error-placeholder"
        className="flex flex-col items-center justify-center gap-2 rounded-comfortable border border-dashed border-red-300 bg-red-50/90 p-4 text-center shadow-whisper dark:border-red-500/40 dark:bg-red-950/30"
        style={{ width: nodeWidth, height: nodeHeight }}
      >
        <TriangleAlert className="h-6 w-6 text-red-400" />
        <p className="font-medium text-red-700 dark:text-red-300">{nodeData.title}</p>
        <p className="line-clamp-3 text-xs text-red-500 dark:text-red-400">
          {nodeData.spec.subtitle || t("workspace.webDesign.agentError.defaultMessage")}
        </p>
        <div className="nodrag mt-1 flex items-center gap-2">
          {retryTarget && (
            <Button size="sm" variant="outline" onClick={handleRetry} disabled={isRetrying}>
              <RotateCcw className={`h-3.5 w-3.5 ${isRetrying ? "animate-spin" : ""}`} />
              {t("workspace.webDesign.agentError.retry")}
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => removeNode(id)}>
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`relative bg-ivory rounded-comfortable border shadow-whisper transition-shadow ${
        selected || isAiEditTarget
          ? "border-terracotta shadow-[0px_0px_0px_2px_#c96442]"
          : "border-border-cream"
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
                variant={isAiEditTarget ? "secondary" : "ghost"}
                size="icon-sm"
                onClick={handleEditWithAi}
                aria-label={t("workspace.node.editWithAIAria", { title: nodeData.title })}
              >
                <WandSparkles className="w-3 h-3" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("workspace.node.editWithAI")}</TooltipContent>
          </Tooltip>
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
                onClick={handleCopyAsPng}
                disabled={isCopying}
                aria-label={t("chat.duplicate")}
              >
                <ImageDown className="w-3 h-3" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("chat.duplicate")}</TooltipContent>
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
      <div ref={chartCaptureRef} className="p-1 bg-parchment">
        <ChartPreview
          spec={nodeData.spec}
          height={chartHeight}
        />
      </div>
    </div>
  );
}

export const ChartNode = memo(ChartNodeComponent);
