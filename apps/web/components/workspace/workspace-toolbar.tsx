"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Check,
  Download,
  FileImage,
  FileText,
  LayoutTemplate,
  Loader2,
  MessageSquare,
  Heading1,
  Heading2,
  Files,
  Minus,
  NotebookPen,
  Pencil,
  Plus,
  Printer,
  RotateCcw,
  Send,
  Type,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { Separator } from "@/components/ui/separator";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useWorkspaceStore } from "@/stores/workspace-store";
import { useUIStore } from "@/stores/ui-store";
import { useRenameWorkspace, useWorkspaceCatalog } from "@/hooks/use-workspace";
import { generateId } from "@/lib/utils";
import { useI18n } from "@/lib/i18n/context";
import { toast } from "sonner";
import { saveWorkspaceSnapshot } from "@/lib/workspace/api";
import {
  CANVAS_FORMAT_PRESETS,
  MAX_CANVAS_PAGES,
  getCanvasFormatPreset,
  getCanvasPageCount,
  getCanvasPageStride,
  getMaxOccupiedCanvasPage,
  isBoundedCanvasFormat,
} from "@/lib/workspace/canvas-formats";
import { findOpenCanvasPosition } from "@/lib/workspace/canvas-layout";
import {
  exportInfiniteCanvasToPng,
  exportFixedCanvasToPng,
  exportFixedCanvasToPdf,
  printFixedCanvas,
} from "@/lib/workspace/canvas-export";
import {
  buildWorkspaceSnapshotFromPublishedVersion,
  buildActiveCanvasPublishPayload,
  cancelPublication,
  fetchPublicationStatus,
  fetchPublishHistory,
  fetchPublishedVersionSnapshot,
  publishWorkspace,
  PublishError,
  resolvePublicUrl,
  type CanvasPublishSnapshot,
  type PublicationState,
  type PublishVisibilityOptions,
  type PublishHistoryItem,
} from "@/lib/workspace/publish";
import { PublishPanel } from "@/components/workspace/publish-dialog";
import { CanvasBackgroundPicker } from "@/components/workspace/canvas-background-picker";
import type {
  DividerNodeData,
  StickyNoteNodeData,
  TextNodeData,
  WorkspaceCanvasFormatId,
} from "@/types/workspace";

const DEFAULT_TEXT_NODE_WIDTH = 480;
const DEFAULT_TEXT_NODE_HEIGHT = 220;
const PUBLISH_HISTORY_VISIBLE_LIMIT = 3;

type TextLevel = "title" | "heading" | "body";

type TextLevelPreset = {
  level: TextLevel;
  fontSize: number;
  fontWeight: "normal" | "bold";
  width: number;
  height: number;
  labelKey: string;
  contentKey: string;
};

const TEXT_LEVEL_PRESETS: Record<TextLevel, TextLevelPreset> = {
  title: {
    level: "title",
    fontSize: 34,
    fontWeight: "bold",
    width: 620,
    height: 88,
    labelKey: "workspace.addTitle",
    contentKey: "workspace.defaultTitleContent",
  },
  heading: {
    level: "heading",
    fontSize: 24,
    fontWeight: "bold",
    width: 560,
    height: 72,
    labelKey: "workspace.addHeading",
    contentKey: "workspace.defaultHeadingContent",
  },
  body: {
    level: "body",
    fontSize: 18,
    fontWeight: "normal",
    width: DEFAULT_TEXT_NODE_WIDTH,
    height: DEFAULT_TEXT_NODE_HEIGHT,
    labelKey: "workspace.addTextBlock",
    contentKey: "workspace.defaultTextContent",
  },
};

export function WorkspaceToolbar() {
  const { t } = useI18n();
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId);
  const workspaces = useWorkspaceStore((s) => s.workspaces);
  const addNode = useWorkspaceStore((s) => s.addNode);
  const hasUnsavedChanges = useWorkspaceStore((s) => s.hasUnsavedChanges);
  const nodes = useWorkspaceStore((s) => s.nodes);
  const edges = useWorkspaceStore((s) => s.edges);
  const viewport = useWorkspaceStore((s) => s.viewport);
  const canvasFormat = useWorkspaceStore((s) => s.canvasFormat);
  const canvasPages = useWorkspaceStore((s) => s.canvasPages);
  const webDesign = useWorkspaceStore((s) => s.webDesign);
  const setCanvasFormat = useWorkspaceStore((s) => s.setCanvasFormat);
  const addCanvasPage = useWorkspaceStore((s) => s.addCanvasPage);
  const removeCanvasPage = useWorkspaceStore((s) => s.removeCanvasPage);
  const loadSnapshot = useWorkspaceStore((s) => s.loadSnapshot);
  const getWorkspaceSnapshot = useWorkspaceStore((s) => s.getSnapshot);
  const setHasUnsavedChanges = useWorkspaceStore((s) => s.setHasUnsavedChanges);
  const activePanel = useUIStore((s) => s.activePanel);
  const isSaving = useUIStore((s) => s.isSaving);
  const setActivePanel = useUIStore((s) => s.setActivePanel);
  const setCatalogOverlayInWorkspace = useUIStore((s) => s.setCatalogOverlayInWorkspace);
  const renameWorkspace = useRenameWorkspace();
  const catalogQuery = useWorkspaceCatalog(activeWorkspaceId);
  const tableCount = (catalogQuery.data ?? []).length;
  const hasNoTables = !catalogQuery.isLoading && tableCount === 0;
  const hasTables = !catalogQuery.isLoading && tableCount > 0;
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [isExporting, setIsExporting] = useState(false);
  const [publishPanelOpen, setPublishPanelOpen] = useState(false);
  const [publication, setPublication] = useState<PublicationState | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<PublishHistoryItem[]>([]);
  const [restoringPageId, setRestoringPageId] = useState<string | null>(null);
  const [isPublishing, setIsPublishing] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const isChatVisible = activePanel === "both";

  const workspace = workspaces.find((w) => w.id === activeWorkspaceId);
  const activeCanvasPreset = getCanvasFormatPreset(canvasFormat.id);
  const isBoundedCanvas = isBoundedCanvasFormat(activeCanvasPreset);
  const pageCount = getCanvasPageCount(canvasFormat.id, canvasPages);
  const maxOccupiedPage = getMaxOccupiedCanvasPage(nodes, activeCanvasPreset);
  const canAddPage = isBoundedCanvas && pageCount < MAX_CANVAS_PAGES;
  const canRemovePage = isBoundedCanvas && pageCount > 1 && pageCount - 1 > maxOccupiedPage;
  const isSlideCanvas = activeCanvasPreset.printStyle === "slide";
  const canPublish = workspace?.role === "owner" || workspace?.role === "editor";
  const activePublishSnapshot = useMemo(
    () => buildActiveCanvasPublishPayload({ canvasFormat, pageCount, viewport, nodes, edges, webDesign }),
    [canvasFormat, pageCount, viewport, nodes, edges, webDesign]
  );
  const publishValidation = useMemo(
    () => validatePublishSnapshot(activePublishSnapshot),
    [activePublishSnapshot]
  );
  const visibleHistory = useMemo(
    () => history.slice(0, PUBLISH_HISTORY_VISIBLE_LIMIT),
    [history]
  );

  useEffect(() => {
    setTitleDraft(workspace?.title ?? "");
    setIsEditingTitle(false);
  }, [workspace?.id, workspace?.title]);

  useEffect(() => {
    setHistoryOpen(false);
    setHistory([]);
  }, [activeWorkspaceId]);

  useEffect(() => {
    if (!activeWorkspaceId || !canPublish) {
      setPublication(null);
      return;
    }
    // Publications are scoped per canvas type, so the displayed link/state must
    // track the active canvas format. Clear stale state before the refetch so a
    // previous canvas's link never flashes for the newly-selected one.
    let cancelled = false;
    setPublication(null);
    fetchPublicationStatus(activeWorkspaceId, canvasFormat.id)
      .then((status) => {
        if (!cancelled) setPublication(status);
      })
      .catch(() => {
        if (!cancelled) setPublication(null);
      });
    return () => {
      cancelled = true;
    };
  }, [activeWorkspaceId, canPublish, canvasFormat.id]);

  const handleRename = () => {
    if (!activeWorkspaceId) return;

    const trimmedTitle = titleDraft.trim();
    if (!trimmedTitle) {
      toast.error(t("workspace.toast.nameEmpty"));
      return;
    }

    if (trimmedTitle === workspace?.title) {
      setIsEditingTitle(false);
      return;
    }

    renameWorkspace.mutate(
      { workspaceId: activeWorkspaceId, title: trimmedTitle },
      {
        onSuccess: () => {
          setIsEditingTitle(false);
          toast.success(t("workspace.toast.renamed"));
        },
        onError: () => toast.error(t("workspace.toast.renameFailed")),
      }
    );
  };

  const handleCancelRename = () => {
    setTitleDraft(workspace?.title ?? "");
    setIsEditingTitle(false);
  };

  const workspaceTitle = workspace?.title ?? t("workspace.fallbackTitle");
  const isWebDesign = canvasFormat.id === "web-design";
  const isInfinite = canvasFormat.id === "infinite";

  const handleExportPng = async () => {
    if (isExporting) return;
    setIsExporting(true);
    try {
      if (isInfinite) {
        await exportInfiniteCanvasToPng(nodes, workspaceTitle);
      } else {
        await exportFixedCanvasToPng(activeCanvasPreset, workspaceTitle, pageCount);
      }
      toast.success(t("workspace.export.success"));
    } catch (err) {
      const msg = err instanceof Error ? err.message : "";
      if (msg === "NO_CONTENT") {
        toast.error(t("workspace.export.noContent"));
      } else {
        toast.error(t("workspace.export.error"));
      }
    } finally {
      setIsExporting(false);
    }
  };

  const handleExportPdf = async () => {
    if (isExporting) return;
    setIsExporting(true);
    try {
      await exportFixedCanvasToPdf(activeCanvasPreset, workspaceTitle, pageCount);
      toast.success(t("workspace.export.success"));
    } catch {
      toast.error(t("workspace.export.error"));
    } finally {
      setIsExporting(false);
    }
  };

  const handlePrint = async () => {
    if (isExporting) return;
    setIsExporting(true);
    try {
      await printFixedCanvas(activeCanvasPreset, workspaceTitle, pageCount);
    } catch {
      toast.error(t("workspace.print.error"));
    } finally {
      setIsExporting(false);
    }
  };

  const handlePublishConfirm = async (visibility: PublishVisibilityOptions) => {
    if (!activeWorkspaceId) return;
    setIsPublishing(true);
    try {
      const result = await publishWorkspace(activeWorkspaceId, activePublishSnapshot, visibility);
      setPublication({ ...result, is_active: true });
      if (historyOpen) {
        refreshHistory().catch(() => toast.error(t("workspace.publish.toast.historyFailed")));
      }
      toast.success(t("workspace.publish.toast.published"), {
        description: t("workspace.publish.toast.versionReady", { version: result.version }),
        action: {
          label: t("workspace.publish.viewPublishedPage"),
          onClick: () => window.open(resolvePublicUrl(result), "_blank", "noreferrer"),
        },
      });
    } catch (error) {
      toast.error(resolvePublishErrorMessage(error, t));
    } finally {
      setIsPublishing(false);
    }
  };

  const handleCancelPublication = async () => {
    if (!activeWorkspaceId) return;
    setIsCancelling(true);
    try {
      await cancelPublication(activeWorkspaceId, canvasFormat.id);
      setPublication({ is_active: false });
      toast.success(t("publish.cancelled"));
    } catch {
      toast.error(t("publish.cancelFailed"));
    } finally {
      setIsCancelling(false);
    }
  };

  const loadHistory = async () => {
    if (!activeWorkspaceId) return;
    const shouldOpen = !historyOpen;
    setHistoryOpen(shouldOpen);
    if (shouldOpen) {
      refreshHistory().catch(() => toast.error(t("workspace.publish.toast.historyFailed")));
    }
  };

  const refreshHistory = async () => {
    if (!activeWorkspaceId) return;
    setHistory(await fetchPublishHistory(activeWorkspaceId));
  };

  const handleRestorePublishedVersion = async (item: PublishHistoryItem) => {
    if (!activeWorkspaceId || restoringPageId) return;
    let restoredLocally = false;
    setRestoringPageId(item.page_id);
    try {
      const published = await fetchPublishedVersionSnapshot(activeWorkspaceId, item.page_id);
      const restoredSnapshot = buildWorkspaceSnapshotFromPublishedVersion({
        workspaceId: activeWorkspaceId,
        published,
        baseSnapshot: getWorkspaceSnapshot(),
      });
      loadSnapshot(restoredSnapshot);
      restoredLocally = true;
      await saveWorkspaceSnapshot(restoredSnapshot);
      toast.success(t("workspace.publish.toast.versionRestored", { version: item.version }));
    } catch {
      if (restoredLocally) {
        setHasUnsavedChanges(true);
      }
      toast.error(t("workspace.publish.toast.restoreFailed"));
    } finally {
      setRestoringPageId(null);
    }
  };

  const handleAddTextNode = (level: TextLevel = "body") => {
    const preset = TEXT_LEVEL_PRESETS[level];
    const nodeData: TextNodeData = {
      type: "text",
      content: t(preset.contentKey),
      fontSize: preset.fontSize,
      fontWeight: preset.fontWeight,
      color: "#3f3d39",
      width: preset.width,
      height: preset.height,
    };

    const position = findOpenCanvasPosition(
      nodes,
      { width: preset.width, height: preset.height },
      canvasFormat.id
    );

    addNode({
      id: `node-${generateId()}`,
      type: "textNode",
      position,
      dragHandle: ".text-node-drag-handle",
      width: preset.width,
      height: preset.height,
      initialWidth: preset.width,
      initialHeight: preset.height,
      data: nodeData,
    });
  };

  const handleAddStickyNote = () => {
    const rotations = [-2, 1.5, -0.8, 2.2];
    const nodeData: StickyNoteNodeData = {
      type: "stickyNote",
      content: "",
      color: (["yellow", "blue", "green", "pink"] as const)[nodes.length % 4],
      width: 240,
      height: 200,
      rotation: rotations[nodes.length % rotations.length],
    };
    const position = findOpenCanvasPosition(nodes, { width: 240, height: 200 }, canvasFormat.id);
    addNode({
      id: `node-${generateId()}`,
      type: "stickyNoteNode",
      position,
      dragHandle: ".sticky-note-drag-handle",
      width: 240,
      height: 200,
      initialWidth: 240,
      initialHeight: 200,
      data: nodeData,
    });
  };

  const handleAddDivider = () => {
    const nodeData: DividerNodeData = {
      type: "divider",
      lineStyle: "solid",
      width: 480,
      rotation: 0,
    };
    const position = findOpenCanvasPosition(nodes, { width: 480, height: 24 }, canvasFormat.id);
    addNode({
      id: `node-${generateId()}`,
      type: "dividerNode",
      position,
      dragHandle: ".divider-node-drag-handle",
      width: 480,
      height: 24,
      initialWidth: 480,
      initialHeight: 24,
      data: nodeData,
    });
  };

  return (
    <header className="flex flex-col border-b border-border-cream bg-ivory shrink-0">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2">
      <div className="flex min-w-[180px] flex-1 items-center gap-3">
        <div className="min-w-0">
          {isEditingTitle ? (
            <form
              className="flex items-center gap-1"
              onSubmit={(event) => {
                event.preventDefault();
                handleRename();
              }}
            >
              <Input
                aria-label={t("workspace.aria.workspaceName")}
                value={titleDraft}
                onChange={(event) => setTitleDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") handleCancelRename();
                }}
                className="h-8 w-64 max-w-[42vw] bg-parchment font-serif text-feature"
                autoFocus
                disabled={renameWorkspace.isPending}
              />
              <Button
                type="submit"
                variant="ghost"
                size="icon-sm"
                aria-label={t("workspace.aria.saveWorkspaceName")}
                disabled={renameWorkspace.isPending}
              >
                {renameWorkspace.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Check className="w-4 h-4" />
                )}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={t("workspace.aria.cancelWorkspaceRename")}
                onClick={handleCancelRename}
                disabled={renameWorkspace.isPending}
              >
                <X className="w-4 h-4" />
              </Button>
            </form>
          ) : (
            <div className="flex min-w-0 items-center gap-1">
              <h2 className="max-w-[220px] truncate font-serif text-feature text-near-black">
                {workspace?.title ?? t("workspace.fallbackTitle")}
              </h2>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => setIsEditingTitle(true)}
                    aria-label={t("workspace.rename")}
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("workspace.rename")}</TooltipContent>
              </Tooltip>
              {hasNoTables && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      size="sm"
                      onClick={() => setCatalogOverlayInWorkspace(true)}
                      className="ml-1 h-7 bg-red-600 px-2 text-xs text-white hover:bg-red-700 focus-visible:ring-red-500"
                    >
                      {t("workspace.catalog.noTableAlert")}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{t("workspace.catalog.noTableTooltip")}</TooltipContent>
                </Tooltip>
              )}
              {hasTables && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      size="sm"
                      onClick={() => setCatalogOverlayInWorkspace(true)}
                      className="ml-1 h-7 bg-green-600 px-2 text-xs text-white hover:bg-green-700 focus-visible:ring-green-500"
                    >
                      {t("workspace.catalog.hasTableAlert", { count: tableCount })}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{t("workspace.catalog.hasTableTooltip", { count: tableCount })}</TooltipContent>
                </Tooltip>
              )}
            </div>
          )}
          <p className="text-label text-stone-gray">
            {t("sidebar.itemCount", { count: nodes.length })}
            {(hasUnsavedChanges || isSaving) && (
              <span className="ml-1 text-terracotta">
                • {isSaving ? t("workspace.autosaving") : t("workspace.unsavedChanges")}
              </span>
            )}
          </p>
        </div>
      </div>

        <div className="flex shrink-0 flex-wrap items-center justify-end gap-1">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setActivePanel(isChatVisible ? "workspace" : "both")}
          >
            <MessageSquare className="w-4 h-4" />
            {isChatVisible ? t("workspace.hideChat") : t("workspace.showChat")}
          </Button>

          <Separator orientation="vertical" className="h-6 mx-1" />

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                aria-label={t("workspace.canvasFormat.label")}
                className="max-w-[180px]"
              >
                <LayoutTemplate className="w-4 h-4" />
                <span className="truncate">{t(activeCanvasPreset.labelKey)}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-64">
              {CANVAS_FORMAT_PRESETS.map((preset) => (
                <DropdownMenuItem
                  key={preset.id}
                  className="items-start justify-between gap-3"
                  onSelect={() => setCanvasFormat({ id: preset.id })}
                >
                  <span className="min-w-0">
                    <span className="block truncate text-body-sm font-medium">
                      {t(preset.labelKey)}
                    </span>
                    <span className="block truncate text-label text-stone-gray">
                      {t(preset.descriptionKey)}
                    </span>
                  </span>
                  {canvasFormat.id === preset.id && (
                    <Check className="mt-1 h-4 w-4 shrink-0 text-terracotta" />
                  )}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          {!isWebDesign && <CanvasBackgroundPicker />}

          {canPublish && (
            <>
              <Separator orientation="vertical" className="h-6 mx-1" />
              <div className="relative">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span>
                      <Button
                        size="sm"
                        onClick={() => setPublishPanelOpen((value) => !value)}
                        disabled={Boolean(publishValidation.reason) || isPublishing}
                      >
                        <Send className="h-4 w-4" />
                        {isPublishing ? t("workspace.publish.publishing") : t("workspace.publish.publish")}
                      </Button>
                    </span>
                  </TooltipTrigger>
                  {publishValidation.reason && (
                    <TooltipContent>{t(publishValidation.reason)}</TooltipContent>
                  )}
                </Tooltip>
                {publishPanelOpen && (
                  <PublishPanel
                    publication={publication}
                    onPublish={handlePublishConfirm}
                    onCancel={handleCancelPublication}
                    isPublishing={isPublishing}
                    isCancelling={isCancelling}
                    modeLabel={t(activeCanvasPreset.labelKey)}
                  />
                )}
              </div>
              <Button variant="ghost" size="sm" onClick={loadHistory}>
                {historyOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                {t("workspace.publish.history")}
              </Button>
            </>
          )}

          {!isWebDesign && (
            <>
              <Separator orientation="vertical" className="h-6 mx-1" />
              {isInfinite ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleExportPng}
                      disabled={isExporting}
                      aria-label={t("workspace.export.png")}
                    >
                      {isExporting ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Download className="w-4 h-4" />
                      )}
                      {isExporting ? t("workspace.export.exporting") : t("workspace.export.button")}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{t("workspace.export.png")}</TooltipContent>
                </Tooltip>
              ) : (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={isExporting}
                      aria-label={t("workspace.export.button")}
                    >
                      {isExporting ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Download className="w-4 h-4" />
                      )}
                      {isExporting ? t("workspace.export.exporting") : t("workspace.export.button")}
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-44">
                    <DropdownMenuItem onSelect={handleExportPng}>
                      <FileImage className="w-4 h-4 mr-2" />
                      {t("workspace.export.png")}
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={handleExportPdf}>
                      <FileText className="w-4 h-4 mr-2" />
                      {isSlideCanvas ? t("workspace.export.pdfSlides") : t("workspace.export.pdf")}
                    </DropdownMenuItem>
                    {activeCanvasPreset.printable && (
                      <DropdownMenuItem onSelect={handlePrint}>
                        <Printer className="w-4 h-4 mr-2" />
                        {t("workspace.print.button")}
                      </DropdownMenuItem>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </>
          )}
        </div>
      </div>

      {historyOpen && (
        <div className="border-t border-border-cream bg-[#fffaf0] px-4 py-2 text-sm">
          {history.length === 0 ? (
            <span className="text-[#777166]">{t("workspace.publish.noPublishedVersions")}</span>
          ) : (
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap gap-2">
                {visibleHistory.map((item) => {
                  const modeLabel = formatCanvasMode(item.canvas_format_id, t);
                  const restoring = restoringPageId === item.page_id;
                  return (
                    <Button
                      key={item.page_id}
                      variant="outline"
                      size="sm"
                      onClick={() => handleRestorePublishedVersion(item)}
                      disabled={Boolean(restoringPageId)}
                      aria-label={t("workspace.publish.restoreVersion", {
                        version: item.version,
                        mode: modeLabel,
                      })}
                      className="h-auto min-h-10 max-w-full justify-start gap-2 rounded-md border-[#d8d1c1] bg-white px-2 py-1 text-left hover:border-terracotta hover:bg-[#fff4ec]"
                    >
                      {restoring ? (
                        <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
                      ) : (
                        <RotateCcw className="h-3.5 w-3.5 shrink-0 text-terracotta" />
                      )}
                      <span className="flex min-w-0 flex-col items-start">
                        <span className="flex max-w-full items-center gap-1.5">
                          <span className="font-medium text-near-black">v{item.version}</span>
                          <span className="rounded border border-[#d8d1c1] bg-parchment px-1.5 py-0.5 text-xs text-[#6d6258]">
                            {formatCanvasType(item.canvas_kind, t)}
                          </span>
                        </span>
                        <span className="max-w-[280px] truncate text-xs font-normal text-[#555250]">
                          {modeLabel} · {formatHistoryTimestamp(item.published_at)}
                        </span>
                      </span>
                    </Button>
                  );
                })}
              </div>
              {history.length > visibleHistory.length && (
                <span className="text-xs text-[#777166]">
                  {t("workspace.publish.historyLimitNotice", {
                    visible: visibleHistory.length,
                    total: history.length,
                  })}
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Content palette row — only for free-canvas modes */}
      {!isWebDesign && (
        <div className="flex items-center gap-1 border-t border-border-cream bg-parchment/50 px-4 py-1">
          <span className="mr-1.5 text-label text-stone-gray shrink-0">
            {t("workspace.addContent")}
          </span>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="sm" className="h-7 gap-1.5 px-2" onClick={() => handleAddTextNode("title")}>
                <Heading1 className="w-3.5 h-3.5" />
                <span className="text-xs">{t("workspace.addTitle")}</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("workspace.addTitle")}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="sm" className="h-7 gap-1.5 px-2" onClick={() => handleAddTextNode("heading")}>
                <Heading2 className="w-3.5 h-3.5" />
                <span className="text-xs">{t("workspace.addHeading")}</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("workspace.addHeading")}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="sm" className="h-7 gap-1.5 px-2" onClick={() => handleAddTextNode("body")}>
                <Type className="w-3.5 h-3.5" />
                <span className="text-xs">{t("workspace.addTextBlock")}</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("workspace.addTextBlock")}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="sm" className="h-7 gap-1.5 px-2" onClick={handleAddStickyNote}>
                <NotebookPen className="w-3.5 h-3.5" />
                <span className="text-xs">{t("workspace.addStickyNote")}</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("workspace.addStickyNote")}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="sm" className="h-7 gap-1.5 px-2" onClick={handleAddDivider}>
                <Minus className="w-3.5 h-3.5" />
                <span className="text-xs">{t("workspace.addDivider")}</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("workspace.addDivider")}</TooltipContent>
          </Tooltip>

          {isBoundedCanvas && (
            <div className="ml-auto flex items-center gap-1 pl-2">
              <Files className="h-3.5 w-3.5 text-stone-gray" />
              <span className="mr-0.5 text-label text-stone-gray shrink-0">
                {t("workspace.pages.label")}
              </span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className="h-7 w-7"
                      onClick={removeCanvasPage}
                      disabled={!canRemovePage}
                      aria-label={t("workspace.pages.remove")}
                    >
                      <Minus className="h-3.5 w-3.5" />
                    </Button>
                  </span>
                </TooltipTrigger>
                <TooltipContent>
                  {pageCount <= 1
                    ? t("workspace.pages.remove")
                    : canRemovePage
                      ? t("workspace.pages.remove")
                      : t("workspace.pages.removeBlocked")}
                </TooltipContent>
              </Tooltip>
              <span
                className="min-w-[3.5rem] text-center text-xs tabular-nums text-near-black"
                aria-label={t("workspace.pages.count", { count: pageCount })}
              >
                {t("workspace.pages.count", { count: pageCount })}
              </span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className="h-7 w-7"
                      onClick={addCanvasPage}
                      disabled={!canAddPage}
                      aria-label={t("workspace.pages.add")}
                    >
                      <Plus className="h-3.5 w-3.5" />
                    </Button>
                  </span>
                </TooltipTrigger>
                <TooltipContent>{t("workspace.pages.add")}</TooltipContent>
              </Tooltip>
            </div>
          )}
        </div>
      )}
    </header>
  );
}

/** Map a publish failure to a localized toast message. Known server error codes
 * resolve to their i18n string; anything else falls back to a generic message so
 * users never see a raw English server string. */
function resolvePublishErrorMessage(
  error: unknown,
  t: (key: string, params?: Record<string, string | number>) => string
): string {
  const codeToKey: Record<string, string> = {
    PUBLISH_FIXED_NODE_OUT_OF_BOUNDS: "workspace.publish.outOfBounds",
    PUBLISH_CHART_DATA_REQUIRED: "workspace.publish.emptyChartData",
    PUBLISH_UNSUPPORTED_CANVAS_FORMAT: "workspace.publish.toast.publishFailed",
  };
  if (error instanceof PublishError && error.code && codeToKey[error.code]) {
    return t(codeToKey[error.code]);
  }
  return t("workspace.publish.toast.publishFailed");
}

function validatePublishSnapshot(snapshot: CanvasPublishSnapshot): { reason?: string } {
  const emptyChart = snapshot.charts.some((chart) => chart.rows.length === 0);
  if (emptyChart) {
    return { reason: "workspace.publish.emptyChartData" };
  }

  if (snapshot.canvas_format.id === "web-design") {
    const pages = snapshot.web_design?.layout.pages ?? [];
    const hasChartZone = pages.some((page) => page.zones.length > 0);
    const hasText = pages.some((page) =>
      (page.textZones ?? []).some((zone) => zone.content.trim().length > 0)
    );
    return hasChartZone || hasText ? {} : { reason: "workspace.publish.emptyCanvas" };
  }

  const publishableNodes = snapshot.nodes.filter(
    (node) =>
      !node.hidden &&
      ["chart", "text", "stickyNote", "divider", "section"].includes(node.data.type)
  );
  if (publishableNodes.length === 0) {
    return { reason: "workspace.publish.emptyCanvas" };
  }

  const preset = getCanvasFormatPreset(snapshot.canvas_format.id);
  if (preset.width && preset.height) {
    // Fixed canvases paginate: pages stack vertically with `CANVAS_PAGE_GAP`
    // between them, so a node on page 2+ legitimately sits at `y > preset.height`.
    // Resolve each node to the page it starts on and bound-check it against that
    // page's rect instead of the first page, otherwise any multi-page report is
    // wrongly flagged as out-of-bounds.
    const stride = getCanvasPageStride(preset);
    const rawPageCount = Number(snapshot.page_count);
    const pageCount = Number.isFinite(rawPageCount)
      ? Math.min(MAX_CANVAS_PAGES, Math.max(1, Math.trunc(rawPageCount)))
      : 1;
    const outOfBounds = publishableNodes.some((node) => {
      const width = Number(node.width ?? node.data.width ?? 0);
      const dataHeight = "height" in node.data ? node.data.height : 24;
      const height = Number(node.height ?? dataHeight ?? 0);
      if (node.position.x < 0 || node.position.x + width > preset.width!) return true;
      if (node.position.y < 0) return true;
      const page = Math.floor(node.position.y / stride);
      if (page >= pageCount) return true;
      const pageBottom = page * stride + preset.height!;
      return node.position.y + height > pageBottom;
    });
    if (outOfBounds) {
      return { reason: "workspace.publish.outOfBounds" };
    }
  }

  return {};
}

function formatCanvasMode(
  formatId: string | undefined,
  t: (key: string, params?: Record<string, string | number>) => string
): string {
  const ids: WorkspaceCanvasFormatId[] = [
    "infinite",
    "web-design",
    "a4-portrait",
    "a4-landscape",
    "a3-portrait",
    "letter-portrait",
    "wide-16-9",
  ];
  const id = ids.includes(formatId as WorkspaceCanvasFormatId)
    ? (formatId as WorkspaceCanvasFormatId)
    : "web-design";
  return t(getCanvasFormatPreset(id).labelKey);
}

function formatCanvasType(
  kind: PublishHistoryItem["canvas_kind"] | undefined,
  t: (key: string, params?: Record<string, string | number>) => string
): string {
  if (kind === "free_layout") return t("workspace.publish.canvasType.freeLayout");
  if (kind === "fixed_size") return t("workspace.publish.canvasType.fixedSize");
  if (kind === "web_page") return t("workspace.publish.canvasType.webPage");
  return t("workspace.publish.canvasType.unknown");
}

function formatHistoryTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
