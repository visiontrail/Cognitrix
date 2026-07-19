"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import {
  AlignLeft,
  Bot,
  Check,
  Eye,
  GripVertical,
  Heading1,
  Heading2,
  ImageDown,
  Plus,
  RotateCcw,
  Square,
  Trash2,
  TriangleAlert,
  Type,
  Users,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ChartPreview } from "@/components/charts/chart-preview";
import { cn } from "@/lib/utils";
import { canCopyPngToClipboard, copyElementAsPngToClipboard } from "@/lib/charts/copy-chart-as-png";
import { retryAgentRunItem, stopAgentRun } from "@/lib/chat/agent-canvas";
import { AGENT_ERROR_CHART_TYPE } from "@/lib/workspace/agent-canvas-layout";
import { applyAgentCanvasWireOp } from "@/lib/workspace/agent-canvas-ops";
import { toChartAsset } from "@/hooks/use-chat";
import { useUIStore } from "@/stores/ui-store";
import { useI18n } from "@/lib/i18n/context";
import {
  GRID_COLS,
  GRID_GAP,
  applyRect,
  clampRect,
  layoutBottom,
  minSizeFor,
  pageToLayoutItems,
  rowUnitOf,
  type GridRect,
  type LayoutItem,
} from "@/lib/workspace/web-design-layout";
import { CollaboratorsDialog } from "@/components/sharing/share-dialog";
import { useWorkspaceStore } from "@/stores/workspace-store";
import type {
  ChartNodeData,
  WebDesignPage,
  WebDesignSidebarItem,
  WebDesignTextStyle,
  WebDesignTextZone,
  WorkspaceNode,
} from "@/types/workspace";

const CHART_HEADER_PX = 40;
const CANVAS_MAX_WIDTH = 1120;
const FALLBACK_CANVAS_WIDTH = 960;

type DragMode = "move" | "resize-e" | "resize-s" | "resize-se";

type DragState = {
  id: string;
  mode: DragMode;
  origin: LayoutItem;
  startClientX: number;
  startClientY: number;
  /** Live pixel rect of the dragged block (follows the pointer un-snapped). */
  ghost: { left: number; top: number; width: number; height: number };
  /** Layout preview with the dragged block snapped in and neighbors pushed/compacted. */
  preview: LayoutItem[];
};

export function WebDesignCanvas() {
  const { t } = useI18n();
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId);
  const nodes = useWorkspaceStore((s) => s.nodes);
  const layout = useWorkspaceStore((s) => s.webDesign);
  const setPreview = useWorkspaceStore((s) => s.setWebDesignPreview);
  const addTextZone = useWorkspaceStore((s) => s.addWebDesignTextZone);
  const activePage = getActivePage(layout);
  const [shareDialogOpen, setShareDialogOpen] = useState(false);
  const activeWorkspace = useWorkspaceStore((s) => s.workspaces.find((w) => w.id === activeWorkspaceId));
  const userWorkspaceRole = useWorkspaceStore((s) =>
    s.workspaces.find((w) => w.id === activeWorkspaceId)?.role ?? "viewer"
  );
  const canEdit = userWorkspaceRole === "owner" || userWorkspaceRole === "editor";
  // Soft lock (agent canvas mode): while a run is building a page in this
  // workspace, user editing is disabled and a banner offers a stop control.
  const activeAgentRun = useUIStore((s) => s.activeAgentRun);
  const clearAgentRun = useUIStore((s) => s.clearAgentRun);
  const agentLocked = Boolean(activeAgentRun && activeAgentRun.workspaceId === activeWorkspaceId);
  const [stopping, setStopping] = useState(false);

  const handleStopRun = async () => {
    if (!activeAgentRun || stopping) return;
    setStopping(true);
    try {
      const status = await stopAgentRun(activeAgentRun.runId);
      // The run finalizes between tool calls; terminal statuses release the
      // lock here even when no live stream is attached to observe the final.
      if (status && status !== "running" && status !== "awaiting_approval") {
        clearAgentRun(activeAgentRun.runId);
      }
    } finally {
      setStopping(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 bg-[#f7f4eb] text-[#2f332f] dark:bg-[#111115] dark:text-white">
      <main className="flex min-w-0 flex-1 flex-col">
        {agentLocked && (
          <div
            data-testid="agent-run-banner"
            className="flex flex-wrap items-center justify-between gap-2 border-b border-[#d97757]/40 bg-[#d97757]/10 px-4 py-2"
          >
            <p className="flex items-center gap-2 text-sm font-medium text-[#8a4a2f] dark:text-[#f4c98f]">
              <Bot className="h-4 w-4 animate-pulse" />
              {t("workspace.webDesign.agentLockBanner")}
            </p>
            <Button variant="outline" size="sm" onClick={handleStopRun} disabled={stopping}>
              <Square className="h-3.5 w-3.5" />
              {t("workspace.webDesign.agentLockStop")}
            </Button>
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#d8d1c1] bg-[#fffdf7] px-4 py-2 dark:border-white/10 dark:bg-[#1c1c38]/90">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">{t("workspace.webDesign.title")}</span>
            {!layout.preview && !agentLocked && (
              <>
                <AddTextZoneMenu onAdd={addTextZone} t={t} />
                <span className="hidden text-xs text-[#8b8577] sm:inline dark:text-gray-400">
                  {t("workspace.webDesign.dragHint")}
                </span>
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => setPreview(!layout.preview)}>
              {layout.preview ? <Check className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              {layout.preview ? t("workspace.webDesign.edit") : t("workspace.webDesign.preview")}
            </Button>
            {canEdit && (
              <Button variant="outline" size="sm" onClick={() => setShareDialogOpen(true)}>
                <Users className="h-4 w-4" />
                {t("workspace.webDesign.collaborators")}
              </Button>
            )}
          </div>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-[220px_minmax(0,1fr)] overflow-hidden">
          <SidebarEditor preview={layout.preview} />
          <div className="overflow-auto px-6 py-6">
            <div
              className={cn(
                "mx-auto rounded-lg border border-[#e2dccf] bg-white px-6 py-6 shadow-sm dark:border-white/10 dark:bg-[#181820]",
                layout.preview && "border-transparent shadow-none"
              )}
              style={{ maxWidth: CANVAS_MAX_WIDTH }}
            >
              <FluidGridEditor
                key={activePage.id}
                page={activePage}
                nodes={nodes}
                preview={layout.preview}
                locked={agentLocked}
              />
            </div>
          </div>
        </div>
      </main>

      {canEdit && (
        <CollaboratorsDialog
          open={shareDialogOpen}
          workspaceId={activeWorkspaceId ?? ""}
          workspaceName={activeWorkspace?.title ?? ""}
          onClose={() => setShareDialogOpen(false)}
        />
      )}
    </div>
  );
}

function FluidGridEditor({
  page,
  nodes,
  preview,
  locked = false,
}: {
  page: WebDesignPage;
  nodes: WorkspaceNode[];
  preview: boolean;
  /** Agent-run soft lock: render like preview (no edit affordances) but keep the editor frame. */
  locked?: boolean;
}) {
  const { t } = useI18n();
  const moveBlock = useWorkspaceStore((s) => s.moveWebDesignBlock);
  const resizeBlock = useWorkspaceStore((s) => s.resizeWebDesignBlock);
  const commitLayout = useWorkspaceStore((s) => s.commitWebDesignLayout);
  const removeZone = useWorkspaceStore((s) => s.removeWebDesignZone);
  const removeTextZone = useWorkspaceStore((s) => s.removeWebDesignTextZone);
  const updateTextZone = useWorkspaceStore((s) => s.updateWebDesignTextZone);

  const containerRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(FALLBACK_CANVAS_WIDTH);
  const [drag, setDrag] = useState<DragState | null>(null);
  const dragRef = useRef<DragState | null>(null);
  dragRef.current = drag;

  useEffect(() => {
    const element = containerRef.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width && width > 120) setContainerWidth(width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const rowUnit = rowUnitOf(page.grid);
  const colWidth = (containerWidth - GRID_GAP * (GRID_COLS - 1)) / GRID_COLS;
  const stepX = colWidth + GRID_GAP;
  const stepY = rowUnit + GRID_GAP;
  const xPx = useCallback((x: number) => x * stepX, [stepX]);
  const yPx = useCallback((y: number) => y * stepY, [stepY]);
  const wPx = useCallback((w: number) => Math.max(0, w * colWidth + (w - 1) * GRID_GAP), [colWidth]);
  const hPx = useCallback((h: number) => Math.max(0, h * rowUnit + (h - 1) * GRID_GAP), [rowUnit]);

  const chartNodes = useMemo(
    () => nodes.filter((node): node is WorkspaceNode & { data: ChartNodeData } => node.data.type === "chart"),
    [nodes]
  );
  const committedItems = useMemo(() => pageToLayoutItems(page), [page]);
  const renderedItems = drag?.preview ?? committedItems;
  const itemById = useMemo(() => new Map(renderedItems.map((item) => [item.id, item])), [renderedItems]);

  const bottomUnits = Math.max(layoutBottom(renderedItems), drag ? Math.ceil((drag.ghost.top + drag.ghost.height) / stepY) + 1 : 0);
  const contentHeight = bottomUnits > 0 ? yPx(bottomUnits) - GRID_GAP : 0;
  const canvasHeight = preview ? Math.max(contentHeight, rowUnit) : Math.max(contentHeight + stepY * 2, rowUnit * 4);

  const beginDrag = useCallback(
    (event: ReactPointerEvent<HTMLElement>, id: string, mode: DragMode) => {
      if (preview || locked) return;
      const item = committedItems.find((entry) => entry.id === id);
      if (!item) return;
      event.preventDefault();
      event.stopPropagation();
      try {
        (event.target as HTMLElement).setPointerCapture?.(event.pointerId);
      } catch {
        // Pointer capture is an optimization (keeps events flowing outside the
        // canvas); failing to acquire it must not cancel the drag.
      }
      setDrag({
        id,
        mode,
        origin: item,
        startClientX: event.clientX,
        startClientY: event.clientY,
        ghost: { left: xPx(item.x), top: yPx(item.y), width: wPx(item.w), height: hPx(item.h) },
        preview: committedItems.map((entry) => ({ ...entry })),
      });
    },
    [preview, locked, committedItems, xPx, yPx, wPx, hPx]
  );

  const onDragMove = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      const current = dragRef.current;
      if (!current) return;
      event.preventDefault();
      const dx = event.clientX - current.startClientX;
      const dy = event.clientY - current.startClientY;
      const { origin, mode } = current;
      const { minW, minH } = minSizeFor(origin.kind);

      let ghost = current.ghost;
      let target: GridRect = { ...origin };
      if (mode === "move") {
        const left = Math.min(Math.max(xPx(origin.x) + dx, 0), containerWidth - wPx(origin.w));
        const top = Math.max(yPx(origin.y) + dy, 0);
        ghost = { left, top, width: wPx(origin.w), height: hPx(origin.h) };
        target = { ...origin, x: Math.round(left / stepX), y: Math.round(top / stepY) };
      } else {
        const growX = mode === "resize-e" || mode === "resize-se";
        const growY = mode === "resize-s" || mode === "resize-se";
        const width = growX
          ? Math.min(Math.max(wPx(origin.w) + dx, wPx(minW)), containerWidth - xPx(origin.x))
          : wPx(origin.w);
        const height = growY ? Math.max(hPx(origin.h) + dy, hPx(minH)) : hPx(origin.h);
        ghost = { left: xPx(origin.x), top: yPx(origin.y), width, height };
        target = {
          ...origin,
          w: growX ? Math.round((width + GRID_GAP) / stepX) : origin.w,
          h: growY ? Math.round((height + GRID_GAP) / stepY) : origin.h,
        };
      }

      const snapped = clampRect(target, minW, minH);
      const previousTarget = current.preview.find((item) => item.id === current.id);
      const preview =
        previousTarget &&
        previousTarget.x === snapped.x &&
        previousTarget.y === snapped.y &&
        previousTarget.w === snapped.w &&
        previousTarget.h === snapped.h
          ? current.preview
          : applyRect(committedItems, current.id, snapped, minW, minH);
      setDrag({ ...current, ghost, preview });
    },
    [committedItems, containerWidth, stepX, stepY, xPx, yPx, wPx, hPx]
  );

  const endDrag = useCallback(() => {
    const current = dragRef.current;
    if (!current) return;
    const changed = current.preview.some((item) => {
      const before = committedItems.find((entry) => entry.id === item.id);
      return !before || before.x !== item.x || before.y !== item.y || before.w !== item.w || before.h !== item.h;
    });
    if (changed) commitLayout(current.preview);
    setDrag(null);
  }, [commitLayout, committedItems]);

  const handleBlockKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLElement>, item: LayoutItem) => {
      if (preview || locked || event.target !== event.currentTarget) return;
      const step = 1;
      const resizeKeys = event.shiftKey;
      let handled = true;
      if (event.key === "ArrowLeft") {
        if (resizeKeys) resizeBlock(item.id, item.w - step, item.h);
        else moveBlock(item.id, item.x - step, item.y);
      } else if (event.key === "ArrowRight") {
        if (resizeKeys) resizeBlock(item.id, item.w + step, item.h);
        else moveBlock(item.id, item.x + step, item.y);
      } else if (event.key === "ArrowUp") {
        if (resizeKeys) resizeBlock(item.id, item.w, item.h - step);
        else moveBlock(item.id, item.x, item.y - step);
      } else if (event.key === "ArrowDown") {
        if (resizeKeys) resizeBlock(item.id, item.w, item.h + step);
        else moveBlock(item.id, item.x, item.y + step);
      } else if (event.key === "Delete" || event.key === "Backspace") {
        if (item.kind === "chart") removeZone(item.id);
        else removeTextZone(item.id);
      } else {
        handled = false;
      }
      if (handled) event.preventDefault();
    },
    [preview, locked, moveBlock, resizeBlock, removeZone, removeTextZone]
  );

  const dragging = Boolean(drag);
  const activeGhostItem = drag ? itemById.get(drag.id) : undefined;
  const isEmpty = !page.zones.length && !(page.textZones ?? []).length;

  return (
    <div
      ref={containerRef}
      data-testid="web-design-grid"
      className="relative"
      style={{ height: canvasHeight }}
      onPointerMove={dragging ? onDragMove : undefined}
      onPointerUp={dragging ? endDrag : undefined}
      onPointerCancel={dragging ? endDrag : undefined}
    >
      {/* Column guides: only visible while a block is being moved or resized. */}
      <div
        aria-hidden
        className={cn(
          "pointer-events-none absolute inset-0 transition-opacity duration-150",
          dragging ? "opacity-100" : "opacity-0"
        )}
      >
        {Array.from({ length: GRID_COLS }).map((_, index) => (
          <div
            key={index}
            className="absolute inset-y-0 rounded-sm bg-[#996b35]/[0.06] dark:bg-[#d97757]/[0.08]"
            style={{ left: xPx(index), width: colWidth }}
          />
        ))}
      </div>

      {/* Snap placeholder for the dragged block. */}
      {drag && activeGhostItem && (
        <div
          aria-hidden
          className="absolute rounded-md border-2 border-dashed border-[#c89b62] bg-[#996b35]/10 transition-all duration-100 dark:border-[#d97757] dark:bg-[#d97757]/10"
          style={{
            left: xPx(activeGhostItem.x),
            top: yPx(activeGhostItem.y),
            width: wPx(activeGhostItem.w),
            height: hPx(activeGhostItem.h),
          }}
        />
      )}

      {isEmpty && !preview && (
        <div className="absolute inset-x-0 top-0 flex h-64 flex-col items-center justify-center gap-2 rounded-md border border-dashed border-[#d8d1c1] text-center dark:border-white/15">
          <p className="text-sm font-medium text-[#6f6a5d] dark:text-gray-300">
            {t("workspace.webDesign.emptyTitle")}
          </p>
          <p className="max-w-sm text-xs text-[#8b8577] dark:text-gray-400">
            {t("workspace.webDesign.emptyBody")}
          </p>
        </div>
      )}

      {page.zones.map((zone) => {
        const item = itemById.get(zone.id);
        if (!item) return null;
        const node = chartNodes.find((chartNode) => chartNode.id === zone.nodeId);
        if (!node) return null;
        const isActive = drag?.id === zone.id;
        const rectPx = isActive && drag
          ? drag.ghost
          : { left: xPx(item.x), top: yPx(item.y), width: wPx(item.w), height: hPx(item.h) };
        if (node.data.chartType === AGENT_ERROR_CHART_TYPE) {
          return (
            <AgentErrorBlock
              key={zone.id}
              node={node}
              rectPx={rectPx}
              preview={preview || locked}
              onRemove={() => removeZone(zone.id)}
            />
          );
        }
        return (
          <ChartBlock
            key={zone.id}
            item={item}
            node={node}
            preview={preview || locked}
            active={isActive}
            rectPx={rectPx}
            chartHeight={hPx(item.h) - CHART_HEADER_PX}
            onPointerDownMove={(event) => beginDrag(event, zone.id, "move")}
            onPointerDownResize={(event, mode) => beginDrag(event, zone.id, mode)}
            onKeyDown={(event) => handleBlockKeyDown(event, item)}
            onRemove={() => removeZone(zone.id)}
          />
        );
      })}

      {(page.textZones ?? []).map((zone) => {
        const item = itemById.get(zone.id);
        if (!item) return null;
        const isActive = drag?.id === zone.id;
        const rectPx = isActive && drag
          ? drag.ghost
          : { left: xPx(item.x), top: yPx(item.y), width: wPx(item.w), height: hPx(item.h) };
        return (
          <TextBlock
            key={zone.id}
            item={item}
            zone={zone}
            preview={preview || locked}
            active={isActive}
            rectPx={rectPx}
            onPointerDownMove={(event) => beginDrag(event, zone.id, "move")}
            onPointerDownResize={(event, mode) => beginDrag(event, zone.id, mode)}
            onKeyDown={(event) => handleBlockKeyDown(event, item)}
            onChange={(content) => updateTextZone(zone.id, { content })}
            onRemove={() => removeTextZone(zone.id)}
          />
        );
      })}
    </div>
  );
}

function blockPositionStyle(rectPx: { left: number; top: number; width: number; height: number }, active: boolean) {
  return {
    left: rectPx.left,
    top: rectPx.top,
    width: rectPx.width,
    height: rectPx.height,
    transition: active ? "none" : "left 180ms ease, top 180ms ease, width 180ms ease, height 180ms ease",
    zIndex: active ? 40 : 10,
  } as const;
}

function ResizeHandles({
  label,
  onPointerDown,
}: {
  label: string;
  onPointerDown: (event: ReactPointerEvent<HTMLElement>, mode: DragMode) => void;
}) {
  return (
    <>
      <div
        role="presentation"
        className="absolute inset-y-2 -right-1 w-2 cursor-ew-resize touch-none"
        onPointerDown={(event) => onPointerDown(event, "resize-e")}
      />
      <div
        role="presentation"
        className="absolute inset-x-2 -bottom-1 h-2 cursor-ns-resize touch-none"
        onPointerDown={(event) => onPointerDown(event, "resize-s")}
      />
      <button
        type="button"
        aria-label={label}
        className="absolute -bottom-0.5 -right-0.5 flex h-5 w-5 cursor-nwse-resize touch-none items-end justify-end rounded-tl opacity-0 transition-opacity focus-visible:opacity-100 group-hover:opacity-100"
        onPointerDown={(event) => onPointerDown(event, "resize-se")}
      >
        <svg width="10" height="10" viewBox="0 0 10 10" className="m-0.5 text-[#a89a7f] dark:text-white/50" aria-hidden>
          <path d="M9 1v8H1" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </button>
    </>
  );
}

function ChartBlock({
  item,
  node,
  preview,
  active,
  rectPx,
  chartHeight,
  onPointerDownMove,
  onPointerDownResize,
  onKeyDown,
  onRemove,
}: {
  item: LayoutItem;
  node: WorkspaceNode & { data: ChartNodeData };
  preview: boolean;
  active: boolean;
  rectPx: { left: number; top: number; width: number; height: number };
  chartHeight: number;
  onPointerDownMove: (event: ReactPointerEvent<HTMLElement>) => void;
  onPointerDownResize: (event: ReactPointerEvent<HTMLElement>, mode: DragMode) => void;
  onKeyDown: (event: ReactKeyboardEvent<HTMLElement>) => void;
  onRemove: () => void;
}) {
  const { t } = useI18n();
  const chartCaptureRef = useRef<HTMLDivElement>(null);
  const [isCopying, setIsCopying] = useState(false);

  const handleCopyAsPng = async () => {
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
  };

  return (
    <section
      aria-label={t("workspace.webDesign.aria.chartZone", { title: node.data.title })}
      tabIndex={preview ? undefined : 0}
      onKeyDown={onKeyDown}
      className={cn(
        "group absolute overflow-hidden rounded-md border bg-white dark:bg-[#1c1c38]",
        active
          ? "border-[#c89b62] shadow-lg dark:border-[#d97757]"
          : "border-[#e2dccf] dark:border-white/10",
        !preview &&
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#c89b62] dark:focus-visible:outline-[#d97757]"
      )}
      style={blockPositionStyle(rectPx, active)}
    >
      <div
        className={cn(
          "flex items-center justify-between gap-1 border-b border-[#eee8dc] bg-[#faf8f4] px-2 dark:border-white/10 dark:bg-[#25254d]",
          !preview && "cursor-grab touch-none active:cursor-grabbing"
        )}
        style={{ height: CHART_HEADER_PX }}
        onPointerDown={preview ? undefined : onPointerDownMove}
        aria-label={preview ? undefined : t("workspace.webDesign.aria.moveBlock", { title: node.data.title })}
      >
        <div className="flex min-w-0 items-center gap-1.5">
          {!preview && <GripVertical className="h-3.5 w-3.5 shrink-0 text-[#b3a88e] dark:text-white/40" />}
          <span className="truncate text-sm font-semibold text-[#4a4842] dark:text-gray-100">{node.data.title}</span>
        </div>
        {!preview && (
          <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="h-6 w-6"
                  onClick={handleCopyAsPng}
                  disabled={isCopying}
                  onPointerDown={(event) => event.stopPropagation()}
                  aria-label={t("chat.duplicate")}
                >
                  <ImageDown className="h-3.5 w-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("chat.duplicate")}</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="h-6 w-6"
                  onClick={onRemove}
                  onPointerDown={(event) => event.stopPropagation()}
                  aria-label={t("workspace.webDesign.aria.removeZone")}
                >
                  <Trash2 className="h-3.5 w-3.5 text-red-400" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("workspace.webDesign.aria.removeZone")}</TooltipContent>
            </Tooltip>
          </div>
        )}
      </div>
      <div ref={chartCaptureRef} className="bg-parchment dark:bg-[#111115]">
        <ChartPreview spec={node.data.spec} height={Math.max(140, chartHeight)} />
      </div>
      {!preview && (
        <ResizeHandles
          label={t("workspace.webDesign.aria.resizeBlock", { title: node.data.title })}
          onPointerDown={onPointerDownResize}
        />
      )}
    </section>
  );
}

/** Parse `agent-block-<run_id>-<seq>` back into its retry coordinates. */
function parseAgentBlockId(blockId: string): { runId: string; seq: number } | null {
  if (!blockId.startsWith("agent-block-")) return null;
  const rest = blockId.slice("agent-block-".length);
  const lastDash = rest.lastIndexOf("-");
  if (lastDash <= 0) return null;
  const runId = rest.slice(0, lastDash);
  const seq = Number(rest.slice(lastDash + 1));
  if (!runId || !Number.isFinite(seq)) return null;
  return { runId, seq };
}

/**
 * Retryable error placeholder for a failed agent-run chart item (design/spec:
 * canvas-op-streaming). Retry re-executes only that item server-side; on
 * success the returned op replaces this placeholder in place.
 */
function AgentErrorBlock({
  node,
  rectPx,
  preview,
  onRemove,
}: {
  node: WorkspaceNode & { data: ChartNodeData };
  rectPx: { left: number; top: number; width: number; height: number };
  preview: boolean;
  onRemove: () => void;
}) {
  const { t } = useI18n();
  const [retrying, setRetrying] = useState(false);
  const retryTarget = parseAgentBlockId(node.data.assetId);

  const handleRetry = async () => {
    if (!retryTarget || retrying) return;
    setRetrying(true);
    try {
      const op = await retryAgentRunItem(retryTarget.runId, retryTarget.seq);
      if (op && op.opType === "place_chart") {
        applyAgentCanvasWireOp(op, {
          toAsset: (rawSpec, meta) =>
            toChartAsset(rawSpec, {
              sessionId: "",
              messageId: retryTarget.runId,
              prompt: meta.title,
              assetId: meta.assetId,
              title: meta.title,
            }),
        });
        toast.success(t("workspace.webDesign.agentError.retrySuccess"));
      } else {
        toast.error(t("workspace.webDesign.agentError.retryFailed"));
      }
    } catch {
      toast.error(t("workspace.webDesign.agentError.retryFailed"));
    } finally {
      setRetrying(false);
    }
  };

  return (
    <section
      data-testid="agent-error-placeholder"
      aria-label={t("workspace.webDesign.agentError.aria", { title: node.data.title })}
      className="absolute overflow-hidden rounded-md border border-dashed border-red-300 bg-red-50/70 dark:border-red-500/40 dark:bg-red-950/30"
      style={blockPositionStyle(rectPx, false)}
    >
      <div className="flex h-full flex-col items-center justify-center gap-1.5 p-3 text-center">
        <TriangleAlert className="h-5 w-5 text-red-400" />
        <p className="max-w-full truncate text-sm font-medium text-red-700 dark:text-red-300">
          {node.data.title}
        </p>
        <p className="line-clamp-2 max-w-full text-xs text-red-500/90 dark:text-red-400/80">
          {node.data.spec.subtitle || t("workspace.webDesign.agentError.defaultMessage")}
        </p>
        {!preview && (
          <div className="mt-1 flex items-center gap-1.5">
            {retryTarget && (
              <Button size="sm" variant="outline" onClick={handleRetry} disabled={retrying}>
                <RotateCcw className={cn("h-3.5 w-3.5", retrying && "animate-spin")} />
                {t("workspace.webDesign.agentError.retry")}
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={onRemove}>
              <Trash2 className="h-3.5 w-3.5 text-red-400" />
            </Button>
          </div>
        )}
      </div>
    </section>
  );
}

const TEXT_ZONE_STYLE_MAP: Record<WebDesignTextStyle, { className: string; placeholderKey: string }> = {
  title: {
    className: "text-2xl font-bold leading-tight text-[#2f332f] dark:text-white",
    placeholderKey: "workspace.webDesign.textZone.titlePlaceholder",
  },
  subtitle: {
    className: "text-lg font-semibold leading-snug text-[#4a4842] dark:text-gray-100",
    placeholderKey: "workspace.webDesign.textZone.subtitlePlaceholder",
  },
  body: {
    className: "text-sm leading-relaxed text-[#555250] dark:text-gray-300",
    placeholderKey: "workspace.webDesign.textZone.bodyPlaceholder",
  },
};

function TextBlock({
  item,
  zone,
  preview,
  active,
  rectPx,
  onPointerDownMove,
  onPointerDownResize,
  onKeyDown,
  onChange,
  onRemove,
}: {
  item: LayoutItem;
  zone: WebDesignTextZone;
  preview: boolean;
  active: boolean;
  rectPx: { left: number; top: number; width: number; height: number };
  onPointerDownMove: (event: ReactPointerEvent<HTMLElement>) => void;
  onPointerDownResize: (event: ReactPointerEvent<HTMLElement>, mode: DragMode) => void;
  onKeyDown: (event: ReactKeyboardEvent<HTMLElement>) => void;
  onChange: (content: string) => void;
  onRemove: () => void;
}) {
  const { t } = useI18n();
  const styleConfig = TEXT_ZONE_STYLE_MAP[zone.style] ?? TEXT_ZONE_STYLE_MAP.body;

  if (preview) {
    return (
      <section
        aria-label={t("workspace.webDesign.aria.textZone")}
        className="absolute overflow-hidden"
        style={blockPositionStyle(rectPx, false)}
      >
        <p className={cn("whitespace-pre-wrap", styleConfig.className)}>{zone.content}</p>
      </section>
    );
  }

  return (
    <section
      aria-label={t("workspace.webDesign.aria.textZone")}
      tabIndex={0}
      onKeyDown={onKeyDown}
      className={cn(
        "group absolute overflow-hidden rounded-md border bg-transparent",
        active
          ? "border-[#c89b62] shadow-lg dark:border-[#d97757]"
          : "border-transparent hover:border-[#e2dccf] dark:hover:border-white/15",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#c89b62] dark:focus-visible:outline-[#d97757]"
      )}
      style={blockPositionStyle(rectPx, active)}
    >
      <div className="pointer-events-none absolute left-1 top-1 z-10 flex items-center gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
        <button
          type="button"
          aria-label={t("workspace.webDesign.aria.moveBlock", { title: t(`workspace.webDesign.textZone.${zone.style}`) })}
          className="pointer-events-auto flex h-6 w-6 cursor-grab touch-none items-center justify-center rounded bg-[#f3efe4] text-[#8b8577] active:cursor-grabbing dark:bg-white/10 dark:text-white/60"
          onPointerDown={onPointerDownMove}
        >
          <GripVertical className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label={t("workspace.webDesign.aria.removeTextZone")}
          className="pointer-events-auto flex h-6 w-6 items-center justify-center rounded bg-[#f3efe4] text-red-400 dark:bg-white/10"
          onClick={onRemove}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
      <Textarea
        className={cn(
          "h-full min-h-0 w-full resize-none border-none bg-transparent p-2 pl-8 shadow-none focus-visible:ring-0",
          styleConfig.className
        )}
        placeholder={t(styleConfig.placeholderKey)}
        value={zone.content}
        onChange={(event) => onChange(event.target.value)}
      />
      <ResizeHandles
        label={t("workspace.webDesign.aria.resizeBlock", { title: t(`workspace.webDesign.textZone.${zone.style}`) })}
        onPointerDown={onPointerDownResize}
      />
    </section>
  );
}

function AddTextZoneMenu({
  onAdd,
  t,
}: {
  onAdd: (style: WebDesignTextStyle) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const options: { style: WebDesignTextStyle; label: string; icon: ReactNode; desc: string }[] = [
    {
      style: "title",
      label: t("workspace.webDesign.textZone.title"),
      icon: <Heading1 className="h-4 w-4" />,
      desc: t("workspace.webDesign.textZone.titleDesc"),
    },
    {
      style: "subtitle",
      label: t("workspace.webDesign.textZone.subtitle"),
      icon: <Heading2 className="h-4 w-4" />,
      desc: t("workspace.webDesign.textZone.subtitleDesc"),
    },
    {
      style: "body",
      label: t("workspace.webDesign.textZone.body"),
      icon: <AlignLeft className="h-4 w-4" />,
      desc: t("workspace.webDesign.textZone.bodyDesc"),
    },
  ];

  return (
    <div className="relative" ref={ref}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="outline" size="sm" onClick={() => setOpen((v) => !v)}>
            <Type className="h-3.5 w-3.5" />
            {t("workspace.webDesign.addTextZone")}
          </Button>
        </TooltipTrigger>
        <TooltipContent>{t("workspace.webDesign.addTextZoneTooltip")}</TooltipContent>
      </Tooltip>
      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-52 rounded-md border border-[#d8d1c1] bg-white shadow-md dark:border-white/10 dark:bg-[#1c1c38]">
          {options.map((opt) => (
            <button
              key={opt.style}
              type="button"
              className="flex w-full items-start gap-3 px-3 py-2.5 text-left hover:bg-[#f7f4eb] dark:hover:bg-white/10"
              onClick={() => {
                onAdd(opt.style);
                setOpen(false);
              }}
            >
              <span className="mt-0.5 text-[#996b35] dark:text-[#d97757]">{opt.icon}</span>
              <span>
                <span className="block text-sm font-medium text-[#2f332f] dark:text-white">{opt.label}</span>
                <span className="block text-xs text-[#777166] dark:text-gray-400">{opt.desc}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function SidebarEditor({ preview }: { preview: boolean }) {
  const { t } = useI18n();
  const layout = useWorkspaceStore((s) => s.webDesign);
  const addItem = useWorkspaceStore((s) => s.addWebDesignSidebarItem);
  const updateItem = useWorkspaceStore((s) => s.updateWebDesignSidebarItem);
  const removeItem = useWorkspaceStore((s) => s.removeWebDesignSidebarItem);
  const setActivePage = useWorkspaceStore((s) => s.setActiveWebDesignPage);

  if (preview) {
    return (
      <nav className="border-r border-[#e2dccf] bg-[#fbfaf5] p-4 dark:border-white/10 dark:bg-[#15151b]">
        {layout.sidebar.map((item) => (
          <div key={item.id} className="py-1">
            <button
              type="button"
              onClick={() => setActivePage(item.pageId ?? item.id)}
              className={cn(
                "block w-full rounded-md px-2 py-1 text-left text-sm font-medium",
                layout.activePageId === (item.pageId ?? item.id)
                  ? "bg-[#eadfca] text-[#6f4d24] dark:bg-[#3a2f23] dark:text-[#f4c98f]"
                  : "dark:text-gray-200 dark:hover:bg-white/10"
              )}
            >
              {formatSidebarLabel(item.label, t)}
            </button>
            {item.children.map((child) => (
              <button
                key={child.id}
                type="button"
                onClick={() => setActivePage(child.pageId ?? child.id)}
                className={cn(
                  "ml-4 block w-[calc(100%-1rem)] rounded-md px-2 py-1 text-left text-xs font-normal text-[#777166] dark:text-gray-400",
                  layout.activePageId === (child.pageId ?? child.id)
                    ? "bg-[#eadfca] text-[#6f4d24] dark:bg-[#3a2f23] dark:text-[#f4c98f]"
                    : "dark:hover:bg-white/10"
                )}
              >
                {formatSidebarLabel(child.label, t)}
              </button>
            ))}
          </div>
        ))}
      </nav>
    );
  }

  return (
    <aside className="overflow-auto border-r border-[#d8d1c1] bg-[#fbfaf5] p-3 dark:border-white/10 dark:bg-[#15151b]">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm font-semibold">{t("workspace.webDesign.pageSidebar")}</span>
        <Button
          aria-label={t("workspace.webDesign.addSidebarSection")}
          variant="outline"
          size="icon-sm"
          onClick={() =>
            addItem(undefined, {
              sectionLabel: t("workspace.webDesign.defaultSection", { count: layout.sidebar.length + 1 }),
              childLabel: t("workspace.webDesign.defaultSubsection"),
            })
          }
        >
          <Plus className="h-4 w-4" />
        </Button>
      </div>
      <div className="space-y-3">
        {layout.sidebar.map((item) => (
          <SidebarItemEditor
            key={item.id}
            item={item}
            activePageId={layout.activePageId}
            onAddChild={() =>
              addItem(item.id, {
                sectionLabel: t("workspace.webDesign.defaultSection", { count: layout.sidebar.length + 1 }),
                childLabel: t("workspace.webDesign.defaultSubsection"),
              })
            }
            onUpdate={updateItem}
            onRemove={removeItem}
            onSelectPage={setActivePage}
          />
        ))}
      </div>
    </aside>
  );
}

function SidebarItemEditor({
  item,
  activePageId,
  onAddChild,
  onUpdate,
  onRemove,
  onSelectPage,
}: {
  item: WebDesignSidebarItem;
  activePageId?: string;
  onAddChild: () => void;
  onUpdate: (itemId: string, updates: Partial<Omit<WebDesignSidebarItem, "id" | "children">>) => void;
  onRemove: (itemId: string) => void;
  onSelectPage: (pageId: string) => void;
}) {
  const { t } = useI18n();
  const pageId = item.pageId ?? item.id;
  return (
    <div
      className={cn(
        "space-y-2 rounded-md border bg-white p-2 dark:bg-[#1c1c38]",
        activePageId === pageId
          ? "border-[#ad7d3d] ring-2 ring-[#eadfca] dark:border-[#d97757] dark:ring-[#d97757]/25"
          : "border-[#d8d1c1] dark:border-white/10"
      )}
    >
      <button
        type="button"
        className="w-full rounded-md bg-[#fbfaf5] px-2 py-1 text-left text-xs font-semibold text-[#6f4d24] dark:bg-white/10 dark:text-[#f4c98f]"
        onClick={() => onSelectPage(pageId)}
      >
        {t("workspace.webDesign.webPage")}
      </button>
      <Input
        aria-label={t("workspace.webDesign.aria.sidebarLabel")}
        value={formatSidebarLabel(item.label, t)}
        onChange={(event) => onUpdate(item.id, { label: event.target.value })}
        onFocus={() => onSelectPage(pageId)}
      />
      <div className="flex gap-1">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon-sm" onClick={onAddChild}>
              <Plus className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{t("workspace.webDesign.sidebarTwoLevelsOnly")}</TooltipContent>
        </Tooltip>
        <Button
          aria-label={t("workspace.webDesign.removeSidebarItem")}
          variant="ghost"
          size="icon-sm"
          onClick={() => onRemove(item.id)}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
      {item.children.map((child) => (
        <div
          key={child.id}
          className={cn(
            "ml-3 space-y-2 border-l pl-2",
            activePageId === (child.pageId ?? child.id)
              ? "border-[#ad7d3d] dark:border-[#d97757]"
              : "border-[#d8d1c1] dark:border-white/10"
          )}
        >
          <button
            type="button"
            className="w-full rounded-md bg-[#fbfaf5] px-2 py-1 text-left text-xs font-semibold text-[#6f4d24] dark:bg-white/10 dark:text-[#f4c98f]"
            onClick={() => onSelectPage(child.pageId ?? child.id)}
          >
            {t("workspace.webDesign.webPage")}
          </button>
          <Input
            aria-label={t("workspace.webDesign.aria.sidebarChildLabel")}
            value={formatSidebarLabel(child.label, t)}
            onChange={(event) => onUpdate(child.id, { label: event.target.value })}
            onFocus={() => onSelectPage(child.pageId ?? child.id)}
          />
        </div>
      ))}
    </div>
  );
}

function formatSidebarLabel(label: string, t: (key: string, params?: Record<string, string | number>) => string) {
  const sectionMatch = /^Section\s+(\d+)$/i.exec(label);
  if (sectionMatch) {
    return t("workspace.webDesign.defaultSection", { count: Number(sectionMatch[1]) });
  }
  if (label === "Sub-section") {
    return t("workspace.webDesign.defaultSubsection");
  }
  return label;
}

function getPages(layout: { grid: WebDesignPage["grid"]; zones: WebDesignPage["zones"]; pages?: WebDesignPage[] }) {
  return layout.pages?.length
    ? layout.pages
    : [{ id: "section-1", title: "Section 1", grid: layout.grid, zones: layout.zones }];
}

function getActivePage(layout: {
  grid: WebDesignPage["grid"];
  zones: WebDesignPage["zones"];
  pages?: WebDesignPage[];
  activePageId?: string;
}) {
  const pages = getPages(layout);
  return pages.find((page) => page.id === layout.activePageId) ?? pages[0];
}
