"use client";

import { useMemo, useRef, useState, useEffect, type DragEvent, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import {
  AlignLeft,
  BotMessageSquare,
  Check,
  ChevronDown,
  ChevronUp,
  Eye,
  Heading1,
  Heading2,
  ImageDown,
  Minus,
  PanelLeft,
  Plus,
  Trash2,
  Type,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ChartPreview } from "@/components/charts/chart-preview";
import { cn } from "@/lib/utils";
import { canCopyPngToClipboard, copyElementAsPngToClipboard } from "@/lib/charts/copy-chart-as-png";
import { useI18n } from "@/lib/i18n/context";
import {
  getWebDesignGridTemplateColumns,
  getWebDesignGridWidth,
  normalizeWebDesignColumnWidths,
} from "@/lib/workspace/web-design-grid";
import { CollaboratorsDialog } from "@/components/sharing/share-dialog";
import { Users } from "lucide-react";
import { useWorkspaceStore } from "@/stores/workspace-store";
import type { ChartNodeData, WebDesignPage, WebDesignSidebarItem, WebDesignTextStyle, WebDesignTextZone, WebDesignZone, WorkspaceNode } from "@/types/workspace";

const WEB_DESIGN_ZONE_MIME = "application/x-web-design-zone";
const WEB_DESIGN_TEXT_ZONE_MIME = "application/x-web-design-text-zone";

export function WebDesignCanvas() {
  const { t } = useI18n();
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId);
  const nodes = useWorkspaceStore((s) => s.nodes);
  const layout = useWorkspaceStore((s) => s.webDesign);
  const setColumns = useWorkspaceStore((s) => s.setWebDesignColumns);
  const setColumnWidth = useWorkspaceStore((s) => s.setWebDesignColumnWidth);
  const addRow = useWorkspaceStore((s) => s.addWebDesignRow);
  const removeRow = useWorkspaceStore((s) => s.removeWebDesignRow);
  const setRowHeight = useWorkspaceStore((s) => s.setWebDesignRowHeight);
  const moveZone = useWorkspaceStore((s) => s.moveWebDesignZone);
  const resizeZone = useWorkspaceStore((s) => s.resizeWebDesignZone);
  const removeZone = useWorkspaceStore((s) => s.removeWebDesignZone);
  const addTextZone = useWorkspaceStore((s) => s.addWebDesignTextZone);
  const updateTextZone = useWorkspaceStore((s) => s.updateWebDesignTextZone);
  const removeTextZone = useWorkspaceStore((s) => s.removeWebDesignTextZone);
  const setPreview = useWorkspaceStore((s) => s.setWebDesignPreview);
  const activePage = getActivePage(layout);
  const [shareDialogOpen, setShareDialogOpen] = useState(false);
  const activeWorkspace = useWorkspaceStore((s) => s.workspaces.find((w) => w.id === activeWorkspaceId));
  const userWorkspaceRole = useWorkspaceStore((s) =>
    s.workspaces.find((w) => w.id === activeWorkspaceId)?.role ?? "viewer"
  );
  const canEdit = userWorkspaceRole === "owner" || userWorkspaceRole === "editor";

  const chartNodes = useMemo(
    () => nodes.filter((node): node is WorkspaceNode & { data: ChartNodeData } => node.data.type === "chart"),
    [nodes]
  );
  const pages = getPages(layout);
  const columnWidths = normalizeWebDesignColumnWidths(activePage.grid.columns, activePage.grid.columnWidths);
  const gridWidth = getWebDesignGridWidth(activePage.grid);
  const gridHeight = activePage.grid.rows.reduce((sum, row) => sum + row.height, 0);
  return (
    <div className="flex h-full min-h-0 bg-[#f7f4eb] text-[#2f332f]">
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#d8d1c1] bg-[#fffdf7] px-4 py-2">
          <div className="flex items-center gap-2">
            <PanelLeft className="h-4 w-4 text-[#996b35]" />
            <span className="text-sm font-semibold">{t("workspace.webDesign.title")}</span>
            {!layout.preview && (
              <>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    variant="outline"
                    size="icon-sm"
                    disabled={activePage.grid.columns <= 2}
                    onClick={() => setColumns(activePage.grid.columns - 1)}
                  >
                    <Minus className="h-3.5 w-3.5" />
                  </Button>
                  <span className="w-20 whitespace-nowrap text-center text-sm">
                    {t("workspace.webDesign.columnsCount", { count: activePage.grid.columns })}
                  </span>
                  <Button
                    variant="outline"
                    size="icon-sm"
                    onClick={() => {
                      if (activePage.grid.columns >= 10) {
                        toast.error(t("workspace.webDesign.maxColumns"));
                        return;
                      }
                      setColumns(activePage.grid.columns + 1);
                    }}
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </Button>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    variant="outline"
                    size="icon-sm"
                    disabled={activePage.grid.rows.length <= 1}
                    onClick={() => removeRow(activePage.grid.rows[activePage.grid.rows.length - 1].id)}
                  >
                    <Minus className="h-3.5 w-3.5" />
                  </Button>
                  <span className="w-20 whitespace-nowrap text-center text-sm">
                    {t("workspace.webDesign.rowsCount", { count: activePage.grid.rows.length })}
                  </span>
                  <Button
                    variant="outline"
                    size="icon-sm"
                    onClick={() => {
                      if (activePage.grid.rows.length >= 10) {
                        toast.error(t("workspace.webDesign.maxRows"));
                        return;
                      }
                      addRow();
                    }}
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </Button>
                </div>
                <AddTextZoneMenu onAdd={addTextZone} t={t} />
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
          <div className="overflow-auto p-5">
            <div className="relative">
              <div
                className={cn(
                  "grid rounded-md border border-[#d8d1c1] bg-white shadow-sm",
                  layout.preview && "border-transparent shadow-none"
                )}
                style={{
                  gridTemplateColumns: getWebDesignGridTemplateColumns(activePage.grid),
                  gridTemplateRows: activePage.grid.rows.map((row) => `${row.height}px`).join(" "),
                  minWidth: "100%",
                  width: gridWidth,
                }}
              >
                {activePage.grid.rows.map((row, rowIndex) =>
                  Array.from({ length: activePage.grid.columns }).map((_, columnIndex) => (
                    <GridCell
                      key={`${row.id}-${columnIndex}`}
                      rowId={row.id}
                      rowIndex={rowIndex}
                      columnIndex={columnIndex}
                      preview={layout.preview}
                      onDropZone={(zoneId) => moveZone(zoneId, columnIndex, rowIndex)}
                      onDropTextZone={(zoneId) => updateTextZone(zoneId, { column: columnIndex, row: rowIndex })}
                    />
                  ))
                )}
                {activePage.zones.map((zone) => (
                  <GridZone
                    key={zone.id}
                    zone={zone}
                    node={chartNodes.find((node) => node.id === zone.nodeId)}
                    preview={layout.preview}
                    onResize={(colSpan, rowSpan) => resizeZone(zone.id, colSpan, rowSpan)}
                    onRemove={() => removeZone(zone.id)}
                    maxColumns={activePage.grid.columns}
                    maxRows={activePage.grid.rows.length}
                  />
                ))}
                {(activePage.textZones ?? []).map((zone) => (
                  <TextGridZone
                    key={zone.id}
                    zone={zone}
                    preview={layout.preview}
                    onUpdate={(updates) => updateTextZone(zone.id, updates)}
                    onResize={(colSpan, rowSpan) => updateTextZone(zone.id, { colSpan, rowSpan })}
                    onRemove={() => removeTextZone(zone.id)}
                    maxColumns={activePage.grid.columns}
                    maxRows={activePage.grid.rows.length}
                  />
                ))}
              </div>
              {!layout.preview &&
                columnWidths.map((width, index) => {
                  const leftPx = columnWidths.slice(0, index + 1).reduce((sum, item) => sum + item, 0);
                  return (
                    <ColumnResizeHandle
                      key={`column-${index}`}
                      columnIndex={index}
                      leftPx={leftPx}
                      currentWidth={width}
                      heightPx={gridHeight}
                      onSetWidth={(nextWidth) => setColumnWidth(index, nextWidth)}
                    />
                  );
                })}
              {!layout.preview &&
                activePage.grid.rows.map((row, index) => {
                  const topPx = activePage.grid.rows
                    .slice(0, index + 1)
                    .reduce((sum, r) => sum + r.height, 0);
                  return (
                    <RowResizeHandle
                      key={row.id}
                      rowId={row.id}
                      topPx={topPx}
                      currentHeight={row.height}
                      onSetHeight={(height) => setRowHeight(row.id, height)}
                    />
                  );
                })}
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
        <div className="absolute left-0 top-full z-50 mt-1 w-52 rounded-md border border-[#d8d1c1] bg-white shadow-md">
          {options.map((opt) => (
            <button
              key={opt.style}
              type="button"
              className="flex w-full items-start gap-3 px-3 py-2.5 text-left hover:bg-[#f7f4eb]"
              onClick={() => {
                onAdd(opt.style);
                setOpen(false);
              }}
            >
              <span className="mt-0.5 text-[#996b35]">{opt.icon}</span>
              <span>
                <span className="block text-sm font-medium text-[#2f332f]">{opt.label}</span>
                <span className="block text-xs text-[#777166]">{opt.desc}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const TEXT_ZONE_STYLE_MAP: Record<
  WebDesignTextStyle,
  { className: string; placeholderKey: string }
> = {
  title: {
    className: "text-2xl font-bold leading-tight text-[#2f332f]",
    placeholderKey: "workspace.webDesign.textZone.titlePlaceholder",
  },
  subtitle: {
    className: "text-lg font-semibold leading-snug text-[#4a4842]",
    placeholderKey: "workspace.webDesign.textZone.subtitlePlaceholder",
  },
  body: {
    className: "text-sm leading-relaxed text-[#555250]",
    placeholderKey: "workspace.webDesign.textZone.bodyPlaceholder",
  },
};

function TextGridZone({
  zone,
  preview,
  onUpdate,
  onResize,
  onRemove,
  maxColumns,
  maxRows,
}: {
  zone: WebDesignTextZone;
  preview: boolean;
  onUpdate: (updates: Partial<Omit<WebDesignTextZone, "id">>) => void;
  onResize: (colSpan: number, rowSpan: number) => void;
  onRemove: () => void;
  maxColumns: number;
  maxRows: number;
}) {
  const { t } = useI18n();
  const styleConfig = TEXT_ZONE_STYLE_MAP[zone.style] ?? TEXT_ZONE_STYLE_MAP.body;

  const handleDragStart = (event: DragEvent<HTMLElement>) => {
    if (preview) {
      event.preventDefault();
      return;
    }
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData(WEB_DESIGN_TEXT_ZONE_MIME, zone.id);
    event.dataTransfer.setData("text/plain", zone.id);
  };

  return (
    <section
      aria-label={t("workspace.webDesign.aria.textZone")}
      className={cn(
        "relative z-10 overflow-hidden rounded-md border border-[#c8d8f0] bg-[#f5f9ff]",
        !preview && "ring-1 ring-[#c8d8f0]"
      )}
      style={{
        gridColumn: `${zone.column + 1} / span ${zone.colSpan}`,
        gridRow: `${zone.row + 1} / span ${zone.rowSpan}`,
      }}
    >
      {!preview && (
        <div
          draggable
          onDragStart={handleDragStart}
          className="flex cursor-grab flex-wrap items-center justify-between gap-y-1 border-b border-[#d0e4f8] bg-[#eaf3ff] px-2 py-1 active:cursor-grabbing"
        >
          <div className="flex flex-wrap items-center gap-1">
            <span className="rounded bg-[#d0e4f8] px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#3a6ea8]">
              {t(`workspace.webDesign.textZone.${zone.style}`)}
            </span>
            <div className="flex items-center gap-0.5">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="h-5 w-5"
                    onClick={() => onResize(Math.max(1, zone.colSpan - 1), zone.rowSpan)}
                    aria-label={t("workspace.webDesign.aria.decreaseColumnSpan")}
                  >
                    <Minus className="h-3 w-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("workspace.webDesign.aria.decreaseColumnSpan")}</TooltipContent>
              </Tooltip>
              <span className="text-[10px] text-[#555]">
                {t("workspace.webDesign.columnSpanLabel", { count: zone.colSpan })}
              </span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="h-5 w-5"
                    onClick={() => onResize(Math.min(maxColumns - zone.column, zone.colSpan + 1), zone.rowSpan)}
                    aria-label={t("workspace.webDesign.aria.increaseColumnSpan")}
                  >
                    <Plus className="h-3 w-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("workspace.webDesign.aria.increaseColumnSpan")}</TooltipContent>
              </Tooltip>
            </div>
            <div className="flex items-center gap-0.5">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="h-5 w-5"
                    onClick={() => onResize(zone.colSpan, Math.max(1, zone.rowSpan - 1))}
                    aria-label={t("workspace.webDesign.aria.decreaseRowSpan")}
                  >
                    <ChevronUp className="h-3 w-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("workspace.webDesign.aria.decreaseRowSpan")}</TooltipContent>
              </Tooltip>
              <span className="text-[10px] text-[#555]">
                {t("workspace.webDesign.rowSpanLabel", { count: zone.rowSpan })}
              </span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="h-5 w-5"
                    onClick={() => onResize(zone.colSpan, Math.min(maxRows - zone.row, zone.rowSpan + 1))}
                    aria-label={t("workspace.webDesign.aria.increaseRowSpan")}
                  >
                    <ChevronDown className="h-3 w-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("workspace.webDesign.aria.increaseRowSpan")}</TooltipContent>
              </Tooltip>
            </div>
          </div>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" className="h-5 w-5" onClick={onRemove}>
                <Trash2 className="h-3 w-3 text-red-400" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("workspace.webDesign.aria.removeTextZone")}</TooltipContent>
          </Tooltip>
        </div>
      )}
      <div className="h-full p-3">
        {preview ? (
          <p className={cn("whitespace-pre-wrap", styleConfig.className)}>{zone.content}</p>
        ) : (
          <Textarea
            className={cn(
              "h-full min-h-[80px] w-full resize-none border-none bg-transparent p-0 shadow-none focus-visible:ring-0",
              styleConfig.className
            )}
            placeholder={t(styleConfig.placeholderKey)}
            value={zone.content}
            onChange={(e) => onUpdate({ content: e.target.value })}
          />
        )}
      </div>
    </section>
  );
}

function GridCell({
  rowId,
  rowIndex,
  columnIndex,
  preview,
  onDropZone,
  onDropTextZone,
}: {
  rowId: string;
  rowIndex: number;
  columnIndex: number;
  preview: boolean;
  onDropZone: (zoneId: string) => void;
  onDropTextZone: (zoneId: string) => void;
}) {
  const { t } = useI18n();
  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    if (preview) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    if (preview) return;
    event.preventDefault();
    const zoneId = event.dataTransfer.getData(WEB_DESIGN_ZONE_MIME);
    if (zoneId) {
      onDropZone(zoneId);
      return;
    }
    const textZoneId = event.dataTransfer.getData(WEB_DESIGN_TEXT_ZONE_MIME);
    if (textZoneId) {
      onDropTextZone(textZoneId);
    }
  };

  return (
    <div
      id={columnIndex === 0 ? rowId : undefined}
      aria-label={t("workspace.webDesign.aria.gridCell", { row: rowIndex + 1, column: columnIndex + 1 })}
      className={cn("border border-dashed border-[#e2dccf]", preview && "border-transparent")}
      style={{ gridColumn: columnIndex + 1, gridRow: rowIndex + 1 }}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    />
  );
}

function GridZone({
  zone,
  node,
  preview,
  onResize,
  onRemove,
  maxColumns,
  maxRows,
}: {
  zone: WebDesignZone;
  node?: WorkspaceNode & { data: ChartNodeData };
  preview: boolean;
  onResize: (colSpan: number, rowSpan: number) => void;
  onRemove: () => void;
  maxColumns: number;
  maxRows: number;
}) {
  const { t } = useI18n();
  const chartCaptureRef = useRef<HTMLDivElement>(null);
  const [isCopying, setIsCopying] = useState(false);
  if (!node) return null;
  const handleDragStart = (event: DragEvent<HTMLElement>) => {
    if (preview) {
      event.preventDefault();
      return;
    }
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData(WEB_DESIGN_ZONE_MIME, zone.id);
    event.dataTransfer.setData("text/plain", zone.id);
  };
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
      className={cn(
        "relative z-10 overflow-hidden rounded-md border border-[#cfc5b2] bg-white",
      )}
      style={{
        gridColumn: `${zone.column + 1} / span ${zone.colSpan}`,
        gridRow: `${zone.row + 1} / span ${zone.rowSpan}`,
      }}
    >
      {!preview ? (
        <div
          draggable
          onDragStart={handleDragStart}
          className="flex cursor-grab flex-wrap items-center justify-between gap-y-1 border-b border-[#eee8dc] bg-[#faf8f4] px-2 py-1 active:cursor-grabbing"
        >
          <div className="flex flex-wrap items-center gap-1">
            <span className="rounded bg-[#ede8de] px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#7a6a4f] truncate max-w-[120px]">
              {node.data.title}
            </span>
            <div className="flex items-center gap-0.5">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="h-5 w-5"
                    onClick={() => onResize(Math.max(1, zone.colSpan - 1), zone.rowSpan)}
                    aria-label={t("workspace.webDesign.aria.decreaseColumnSpan")}
                  >
                    <Minus className="h-3 w-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("workspace.webDesign.aria.decreaseColumnSpan")}</TooltipContent>
              </Tooltip>
              <span className="text-[10px] text-[#555]">
                {t("workspace.webDesign.columnSpanLabel", { count: zone.colSpan })}
              </span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="h-5 w-5"
                    onClick={() => onResize(Math.min(maxColumns - zone.column, zone.colSpan + 1), zone.rowSpan)}
                    aria-label={t("workspace.webDesign.aria.increaseColumnSpan")}
                  >
                    <Plus className="h-3 w-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("workspace.webDesign.aria.increaseColumnSpan")}</TooltipContent>
              </Tooltip>
            </div>
            <div className="flex items-center gap-0.5">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="h-5 w-5"
                    onClick={() => onResize(zone.colSpan, Math.max(1, zone.rowSpan - 1))}
                    aria-label={t("workspace.webDesign.aria.decreaseRowSpan")}
                  >
                    <ChevronUp className="h-3 w-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("workspace.webDesign.aria.decreaseRowSpan")}</TooltipContent>
              </Tooltip>
              <span className="text-[10px] text-[#555]">
                {t("workspace.webDesign.rowSpanLabel", { count: zone.rowSpan })}
              </span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="h-5 w-5"
                    onClick={() => onResize(zone.colSpan, Math.min(maxRows - zone.row, zone.rowSpan + 1))}
                    aria-label={t("workspace.webDesign.aria.increaseRowSpan")}
                  >
                    <ChevronDown className="h-3 w-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("workspace.webDesign.aria.increaseRowSpan")}</TooltipContent>
              </Tooltip>
            </div>
          </div>
          <div className="flex items-center gap-0.5">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="h-5 w-5"
                  onClick={handleCopyAsPng}
                  disabled={isCopying}
                  aria-label={t("chat.duplicate")}
                >
                  <ImageDown className="h-3 w-3" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("chat.duplicate")}</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon-sm" className="h-5 w-5" onClick={onRemove}>
                  <Trash2 className="h-3 w-3 text-red-400" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("workspace.webDesign.aria.removeZone")}</TooltipContent>
            </Tooltip>
          </div>
        </div>
      ) : (
        <div className="border-b border-[#eee8dc] px-3 py-2 text-sm font-semibold">{node.data.title}</div>
      )}
      <div ref={chartCaptureRef} className="bg-parchment">
        <ChartPreview spec={node.data.spec} height={Math.max(180, zone.rowSpan * 260)} />
      </div>
    </section>
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
      <nav className="border-r border-[#e2dccf] bg-[#fbfaf5] p-4">
        {layout.sidebar.map((item) => (
          <div key={item.id} className="py-1">
            <button
              type="button"
              onClick={() => setActivePage(item.pageId ?? item.id)}
              className={cn(
                "block w-full rounded-md px-2 py-1 text-left text-sm font-medium",
                layout.activePageId === (item.pageId ?? item.id) && "bg-[#eadfca] text-[#6f4d24]"
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
                  "ml-4 block w-[calc(100%-1rem)] rounded-md px-2 py-1 text-left text-xs font-normal text-[#777166]",
                  layout.activePageId === (child.pageId ?? child.id) && "bg-[#eadfca] text-[#6f4d24]"
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
    <aside className="overflow-auto border-r border-[#d8d1c1] bg-[#fbfaf5] p-3">
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

function ColumnResizeHandle({
  columnIndex,
  leftPx,
  currentWidth,
  heightPx,
  onSetWidth,
}: {
  columnIndex: number;
  leftPx: number;
  currentWidth: number;
  heightPx: number;
  onSetWidth: (width: number) => void;
}) {
  const { t } = useI18n();
  const [dragging, setDragging] = useState(false);

  const handleMouseDown = (e: ReactMouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = currentWidth;
    setDragging(true);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const onMove = (ev: MouseEvent) => {
      onSetWidth(startWidth + ev.clientX - startX);
    };
    const onUp = () => {
      setDragging(false);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  return (
    <div
      aria-label={t("workspace.webDesign.aria.resizeColumn", { column: columnIndex + 1 })}
      className={cn(
        "group absolute top-0 z-30 flex w-3 cursor-col-resize select-none justify-center",
        dragging && "z-40"
      )}
      style={{ left: leftPx - 6, height: heightPx }}
      onMouseDown={handleMouseDown}
    >
      <div
        className={cn(
          "h-full w-0.5 transition-colors",
          dragging ? "bg-[#996b35]" : "bg-transparent group-hover:bg-[#d8d1c1]"
        )}
      />
    </div>
  );
}

function RowResizeHandle({
  rowId,
  topPx,
  currentHeight,
  onSetHeight,
}: {
  rowId: string;
  topPx: number;
  currentHeight: number;
  onSetHeight: (height: number) => void;
}) {
  const { t } = useI18n();
  const [dragging, setDragging] = useState(false);

  const handleMouseDown = (e: ReactMouseEvent) => {
    e.preventDefault();
    const startY = e.clientY;
    const startHeight = currentHeight;
    setDragging(true);
    document.body.style.cursor = "row-resize";
    document.body.style.userSelect = "none";

    const onMove = (ev: MouseEvent) => {
      onSetHeight(startHeight + ev.clientY - startY);
    };
    const onUp = () => {
      setDragging(false);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  return (
    <div
      aria-label={t("workspace.webDesign.aria.resizeRow", { rowId })}
      className={cn(
        "group absolute inset-x-0 z-30 flex h-3 cursor-row-resize select-none items-center",
        dragging && "z-40"
      )}
      style={{ top: topPx - 6 }}
      onMouseDown={handleMouseDown}
    >
      <div
        className={cn(
          "h-0.5 w-full transition-colors",
          dragging ? "bg-[#996b35]" : "bg-transparent group-hover:bg-[#d8d1c1]"
        )}
      />
    </div>
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
        "space-y-2 rounded-md border bg-white p-2",
        activePageId === pageId ? "border-[#ad7d3d] ring-2 ring-[#eadfca]" : "border-[#d8d1c1]"
      )}
    >
      <button
        type="button"
        className="w-full rounded-md bg-[#fbfaf5] px-2 py-1 text-left text-xs font-semibold text-[#6f4d24]"
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
            activePageId === (child.pageId ?? child.id) ? "border-[#ad7d3d]" : "border-[#d8d1c1]"
          )}
        >
          <button
            type="button"
            className="w-full rounded-md bg-[#fbfaf5] px-2 py-1 text-left text-xs font-semibold text-[#6f4d24]"
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
