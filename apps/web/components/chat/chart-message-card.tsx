"use client";

import { useCallback, useRef, useState } from "react";
import { LayoutDashboard, Copy, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { ChartPreview } from "@/components/charts/chart-preview";
import { useAssetStore } from "@/stores/asset-store";
import { useChatStore } from "@/stores/chat-store";
import { useWorkspaceStore } from "@/stores/workspace-store";
import { useUIStore } from "@/stores/ui-store";
import { stopChatResponse } from "@/hooks/use-chat";
import { syncSessionToServer } from "@/lib/chat/server-sync";
import { API_BASE_URL } from "@/lib/api-base";
import { getActiveAuthContext, getAuthorizationHeader } from "@/lib/auth/session";
import { generateId } from "@/lib/utils";
import { useI18n } from "@/lib/i18n/context";
import { getCanvasFormatPreset, getCanvasPageCount } from "@/lib/workspace/canvas-formats";
import { findOpenCanvasPosition } from "@/lib/workspace/canvas-layout";
import { canCopyPngToClipboard, copyElementAsPngToClipboard } from "@/lib/charts/copy-chart-as-png";
import { toast } from "sonner";
import type { ChartNodeData } from "@/types/workspace";
import type { ChartAssetReference } from "@/types/chat";

const DEFAULT_CHART_NODE_WIDTH = 520;
const DEFAULT_CHART_NODE_HEIGHT = 380;
const DEFAULT_AUTH_CONTEXT = {
  userId: process.env.NEXT_PUBLIC_DEFAULT_USER_ID ?? "demo-user",
  projectId: process.env.NEXT_PUBLIC_DEFAULT_PROJECT_ID ?? "demo-project",
  role: process.env.NEXT_PUBLIC_DEFAULT_ROLE ?? "hr",
  department: process.env.NEXT_PUBLIC_DEFAULT_DEPARTMENT ?? "HR",
  clearance: Number(process.env.NEXT_PUBLIC_DEFAULT_CLEARANCE ?? 1),
};

type ChartMessageCardProps = {
  assetId: string;
  title: string;
  chartType: string;
};

export function ChartMessageCard({ assetId, title, chartType }: ChartMessageCardProps) {
  const { t } = useI18n();
  const chartCaptureRef = useRef<HTMLDivElement>(null);
  const [isCopying, setIsCopying] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const getAsset = useAssetStore((s) => s.getAsset);
  const setComposerText = useChatStore((s) => s.setComposerText);
  const resetConversation = useChatStore((s) => s.resetConversation);
  const addNode = useWorkspaceStore((s) => s.addNode);
  const addNodeToWebDesign = useWorkspaceStore((s) => s.addNodeToWebDesign);
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId);
  const nodes = useWorkspaceStore((s) => s.nodes);
  const canvasFormat = useWorkspaceStore((s) => s.canvasFormat);
  const canvasPages = useWorkspaceStore((s) => s.canvasPages);
  const setActivePanel = useUIStore((s) => s.setActivePanel);

  const asset = getAsset(assetId);
  const canvasName = t(getCanvasFormatPreset(canvasFormat.id).labelKey);

  const handleAddToCanvas = useCallback(() => {
    if (!asset) {
      toast.error(t("chat.toast.chartAssetNotFound"));
      return;
    }

    if (!activeWorkspaceId) {
      toast.error(t("chat.toast.noWorkspace"));
      return;
    }

    const position =
      canvasFormat.id === "web-design"
        ? { x: 0, y: 0 }
        : findOpenCanvasPosition(
            nodes,
            { width: DEFAULT_CHART_NODE_WIDTH, height: DEFAULT_CHART_NODE_HEIGHT },
            canvasFormat.id,
            getCanvasPageCount(canvasFormat.id, canvasPages)
          );

    const nodeData: ChartNodeData = {
      type: "chart",
      assetId: asset.id,
      title: asset.title,
      chartType: asset.chartType,
      spec: asset.spec,
      width: DEFAULT_CHART_NODE_WIDTH,
      height: DEFAULT_CHART_NODE_HEIGHT,
    };

    const node = {
      id: `node-${generateId()}`,
      type: "chartNode",
      position,
      width: DEFAULT_CHART_NODE_WIDTH,
      height: DEFAULT_CHART_NODE_HEIGHT,
      initialWidth: DEFAULT_CHART_NODE_WIDTH,
      initialHeight: DEFAULT_CHART_NODE_HEIGHT,
      data: nodeData,
    };

    if (canvasFormat.id === "web-design") {
      addNodeToWebDesign(node);
    } else {
      addNode(node);
    }

    setActivePanel("both");
    toast.success(t("chat.toast.addedToWorkspace", { title: asset.title, canvasName }));
  }, [asset, activeWorkspaceId, nodes, canvasFormat.id, canvasPages, addNode, addNodeToWebDesign, setActivePanel, t, canvasName]);

  const handleCopyAsPng = useCallback(async () => {
    if (!asset || !chartCaptureRef.current) {
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
  }, [asset, t]);

  const handleRegenerate = useCallback(async () => {
    const prompt = asset?.sourceMeta.prompt?.trim();
    const sessionId = asset?.sourceMeta.sessionId?.trim();
    if (!prompt) {
      toast.error(t("chat.toast.regeneratePromptMissing"));
      return;
    }
    if (!sessionId) {
      toast.error(t("chat.toast.regenerateSessionMissing"));
      return;
    }

    setIsRegenerating(true);
    stopChatResponse(sessionId);
    resetConversation(sessionId);
    if (activeWorkspaceId) {
      void syncSessionToServer(activeWorkspaceId, sessionId);
    }
    try {
      await resetBackendConversation({
        conversationId: sessionId,
        workspaceId: activeWorkspaceId,
      });
      toast.success(t("chat.toast.regenerateReady"));
    } catch {
      toast.error(t("chat.toast.regenerateContextResetFailed"));
    } finally {
      setComposerText(prompt);
      requestAnimationFrame(() => {
        const composer = document.querySelector<HTMLTextAreaElement>("[data-chat-composer='true']");
        composer?.focus();
        composer?.setSelectionRange(prompt.length, prompt.length);
      });
      setIsRegenerating(false);
    }
  }, [activeWorkspaceId, asset, resetConversation, setComposerText, t]);

  return (
    <Card className="w-full max-w-lg overflow-hidden animate-fade-in">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-body font-sans font-semibold">{title}</CardTitle>
          <Badge variant="secondary">{chartType}</Badge>
        </div>
      </CardHeader>

      <CardContent className="pb-3">
        {asset ? (
          <div
            ref={chartCaptureRef}
            className="rounded-comfortable overflow-hidden border border-border-cream bg-parchment"
          >
            <ChartPreview spec={asset.spec} height={220} />
          </div>
        ) : (
          <div className="h-[220px] rounded-comfortable bg-warm-sand flex items-center justify-center">
            <p className="text-caption text-stone-gray">{t("chat.chartPreviewUnavailable")}</p>
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex items-center gap-2 mt-3">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="default" size="sm" onClick={handleAddToCanvas}>
                <LayoutDashboard className="w-3.5 h-3.5" />
                {t("chat.addToCanvas", { canvasName })}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("chat.addToCanvasTooltip", { canvasName })}</TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={handleCopyAsPng}
                disabled={!asset || isCopying}
                aria-label={t("chat.duplicate")}
              >
                <Copy className="w-3.5 h-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("chat.duplicate")}</TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={handleRegenerate}
                disabled={!asset || isRegenerating}
                aria-label={t("chat.regenerate")}
              >
                <RefreshCw className="w-3.5 h-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("chat.regenerate")}</TooltipContent>
          </Tooltip>
        </div>
      </CardContent>
    </Card>
  );
}

export function MultiChartMessageGroup({ assets }: { assets: ChartAssetReference[] }) {
  const { t } = useI18n();
  const getAsset = useAssetStore((s) => s.getAsset);
  const addNode = useWorkspaceStore((s) => s.addNode);
  const addNodeToWebDesign = useWorkspaceStore((s) => s.addNodeToWebDesign);
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId);
  const nodes = useWorkspaceStore((s) => s.nodes);
  const canvasFormat = useWorkspaceStore((s) => s.canvasFormat);
  const canvasPages = useWorkspaceStore((s) => s.canvasPages);
  const setActivePanel = useUIStore((s) => s.setActivePanel);
  const canvasName = t(getCanvasFormatPreset(canvasFormat.id).labelKey);

  const handleAddAllToCanvas = useCallback(() => {
    if (!activeWorkspaceId) {
      toast.error(t("chat.toast.noWorkspace"));
      return;
    }

    const resolvedAssets = assets
      .map((asset) => getAsset(asset.assetId))
      .filter((asset): asset is NonNullable<ReturnType<typeof getAsset>> => Boolean(asset));
    if (!resolvedAssets.length) {
      toast.error(t("chat.toast.chartAssetNotFound"));
      return;
    }

    // Track nodes placed in this batch so each new chart avoids both existing
    // canvas nodes and siblings added earlier in the same loop.
    const placedNodes = [...nodes];

    resolvedAssets.forEach((asset) => {
      const nodeData: ChartNodeData = {
        type: "chart",
        assetId: asset.id,
        title: asset.title,
        chartType: asset.chartType,
        spec: asset.spec,
        width: DEFAULT_CHART_NODE_WIDTH,
        height: DEFAULT_CHART_NODE_HEIGHT,
      };
      const position =
        canvasFormat.id === "web-design"
          ? { x: 0, y: 0 }
          : findOpenCanvasPosition(
              placedNodes,
              { width: DEFAULT_CHART_NODE_WIDTH, height: DEFAULT_CHART_NODE_HEIGHT },
              canvasFormat.id,
              getCanvasPageCount(canvasFormat.id, canvasPages)
            );
      const node = {
        id: `node-${generateId()}`,
        type: "chartNode",
        position,
        width: DEFAULT_CHART_NODE_WIDTH,
        height: DEFAULT_CHART_NODE_HEIGHT,
        initialWidth: DEFAULT_CHART_NODE_WIDTH,
        initialHeight: DEFAULT_CHART_NODE_HEIGHT,
        data: nodeData,
      };
      if (canvasFormat.id === "web-design") {
        addNodeToWebDesign(node);
      } else {
        placedNodes.push(node as (typeof placedNodes)[number]);
        addNode(node);
      }
    });

    setActivePanel("both");
    toast.success(t("chat.multiChart.addedAll", { count: resolvedAssets.length, canvasName }));
  }, [
    activeWorkspaceId,
    addNode,
    addNodeToWebDesign,
    assets,
    canvasFormat.id,
    canvasPages,
    canvasName,
    getAsset,
    nodes,
    setActivePanel,
    t,
  ]);

  return (
    <div className="w-full max-w-2xl space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Badge variant="secondary">{t("chat.multiChart.generatedCount", { count: assets.length })}</Badge>
        <Button size="sm" variant="outline" onClick={handleAddAllToCanvas}>
          <LayoutDashboard className="h-3.5 w-3.5" />
          {t("chat.multiChart.addAllToCanvas", { canvasName })}
        </Button>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {assets.map((asset) => (
          <ChartMessageCard
            key={asset.assetId}
            assetId={asset.assetId}
            title={asset.title}
            chartType={asset.chartType}
          />
        ))}
      </div>
    </div>
  );
}

async function resetBackendConversation({
  conversationId,
  workspaceId,
}: {
  conversationId: string;
  workspaceId: string | null;
}): Promise<void> {
  const authContext = getActiveAuthContext(DEFAULT_AUTH_CONTEXT);
  const authorizationHeader = await getAuthorizationHeader(API_BASE_URL, authContext);
  const response = await fetch(`${API_BASE_URL}/chat/session/reset`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authorizationHeader,
    },
    body: JSON.stringify({
      user_id: authContext.userId,
      project_id: authContext.projectId,
      workspace_id: workspaceId,
      conversation_id: conversationId,
    }),
  });
  if (!response.ok) {
    throw new Error(`chat_session_reset_failed_${response.status}`);
  }
}
