"use client";

import { type KeyboardEvent, useState } from "react";
import { ChevronLeft, ChevronRight, Database, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  useDeleteWorkspaceCatalogEntry,
  useWorkspaceCatalogDataPreview,
  useWorkspaceCatalog,
} from "@/hooks/use-workspace";
import { useI18n } from "@/lib/i18n/context";
import { cn } from "@/lib/utils";
import type { TableCatalogEntry } from "@/types/workspace";

export function WorkspaceCatalogReadonly({
  workspaceId,
  className,
  showHeader = true,
}: {
  workspaceId: string;
  className?: string;
  showHeader?: boolean;
}) {
  const { t } = useI18n();
  const [entryToDelete, setEntryToDelete] = useState<TableCatalogEntry | null>(null);
  const [selectedEntry, setSelectedEntry] = useState<TableCatalogEntry | null>(null);
  const [previewOffset, setPreviewOffset] = useState(0);
  const catalogQuery = useWorkspaceCatalog(workspaceId);
  const previewQuery = useWorkspaceCatalogDataPreview(workspaceId, selectedEntry?.id ?? null, {
    limit: PREVIEW_LIMIT,
    offset: previewOffset,
  });
  const deleteMutation = useDeleteWorkspaceCatalogEntry();

  const handleConfirmDelete = async () => {
    if (!entryToDelete) {
      return;
    }

    try {
      await deleteMutation.mutateAsync({ workspaceId, catalogId: entryToDelete.id });
      toast.success(t("workspace.catalog.deleteSuccess", { name: entryToDelete.humanLabel }));
      setEntryToDelete(null);
    } catch {
      toast.error(t("workspace.catalog.deleteFailed"));
    }
  };

  const openEntry = (entry: TableCatalogEntry) => {
    setPreviewOffset(0);
    setSelectedEntry(entry);
  };

  const handleEntryKeyDown = (event: KeyboardEvent<HTMLDivElement>, entry: TableCatalogEntry) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openEntry(entry);
    }
  };

  if (catalogQuery.isLoading) {
    return (
      <section className={cn("space-y-4", className)} data-testid="workspace-catalog-loading">
        {showHeader ? (
          <div>
            <h2 className="font-serif text-heading-sm text-near-black">
              {t("workspace.catalog.title")}
            </h2>
            <p className="text-caption text-olive-gray">{t("workspace.catalog.loadingDescription")}</p>
          </div>
        ) : null}
        <div className="space-y-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      </section>
    );
  }

  const entries = catalogQuery.data ?? [];
  const previewData = previewQuery.data;

  return (
    <section className={cn("space-y-5", className)} data-testid="workspace-catalog-readonly">
      {showHeader ? (
        <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
          <div>
            <h2 className="font-serif text-heading-sm text-near-black">
              {t("workspace.catalog.title")}
            </h2>
            <p className="text-caption text-olive-gray">
              {t("workspace.catalog.description", { count: entries.length })}
            </p>
          </div>
          <Badge variant="outline">{t("workspace.catalog.entryCount", { count: entries.length })}</Badge>
        </div>
      ) : null}

      {entries.length === 0 ? (
        <div className="rounded-comfortable border border-border-cream bg-ivory px-4 py-4">
          <p className="text-caption text-stone-gray">{t("workspace.catalog.empty")}</p>
        </div>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {entries.map((entry) => (
            <div
              key={entry.id}
              role="button"
              tabIndex={0}
              aria-label={t("workspace.catalog.openEntryData", { name: entry.humanLabel })}
              onClick={() => openEntry(entry)}
              onKeyDown={(event) => handleEntryKeyDown(event, entry)}
              className="rounded-comfortable border border-border-cream bg-ivory px-4 py-3 shadow-whisper outline-none transition hover:border-terracotta/50 hover:bg-white focus-visible:ring-2 focus-visible:ring-focus-blue focus-visible:ring-offset-2 focus-visible:ring-offset-parchment"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 space-y-1">
                  <div className="flex min-w-0 items-center gap-2">
                    <Database className="h-4 w-4 shrink-0 text-olive-gray" />
                    <p className="truncate text-body-sm font-medium text-near-black">{entry.humanLabel}</p>
                  </div>
                  <p className="text-caption text-stone-gray">
                    {entry.description || t("workspace.catalog.purposeFallback")}
                  </p>
                </div>
                <div className="flex shrink-0 items-start justify-end gap-2">
                  <div className="flex flex-wrap justify-end gap-2">
                    {entry.primaryKeys.length === 0 && entry.matchColumns.length === 0 ? (
                      <Badge variant="secondary">{t("workspace.catalog.planned")}</Badge>
                    ) : (
                      <Badge variant="outline">{t("workspace.catalog.aiManaged")}</Badge>
                    )}
                    {entry.isActiveTarget ? <Badge variant="default">{t("workspace.catalog.active")}</Badge> : null}
                  </div>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={t("workspace.catalog.deleteEntry", { name: entry.humanLabel })}
                        onClick={(event) => {
                          event.stopPropagation();
                          setEntryToDelete(entry);
                        }}
                        disabled={deleteMutation.isPending}
                        className="shrink-0 text-stone-gray hover:bg-error-crimson/10 hover:text-error-crimson"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>{t("workspace.catalog.delete")}</TooltipContent>
                  </Tooltip>
                </div>
              </div>
              <p className="pt-2 text-label text-stone-gray">{entry.tableName}</p>
            </div>
          ))}
        </div>
      )}

      <Dialog
        open={selectedEntry !== null}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedEntry(null);
            setPreviewOffset(0);
          }
        }}
      >
        <DialogContent className="max-h-[90vh] w-[min(96vw,1180px)] max-w-none gap-0 overflow-hidden p-0">
          <DialogHeader className="border-b border-border-cream px-5 py-4 pr-12">
            <DialogTitle className="flex items-center gap-2">
              <Database className="h-5 w-5 text-terracotta" />
              {selectedEntry?.humanLabel ?? t("workspace.catalog.dataPreviewTitle")}
            </DialogTitle>
            <DialogDescription className="break-all">
              {selectedEntry?.tableName ?? ""}
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-cream bg-parchment/60 px-5 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">
                {t("workspace.catalog.dataPreviewRows", {
                  count: previewData?.rowCount ?? 0,
                })}
              </Badge>
              <Badge variant="outline">
                {t("workspace.catalog.dataPreviewColumns", {
                  count: previewData?.columns.length ?? 0,
                })}
              </Badge>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={t("workspace.catalog.refreshDataPreview")}
              onClick={() => previewQuery.refetch()}
              disabled={previewQuery.isFetching}
            >
              <RefreshCw className={cn("h-4 w-4", previewQuery.isFetching && "animate-spin")} />
            </Button>
          </div>

          <div className="min-h-0 overflow-auto px-5 py-4">
            {previewQuery.isLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : previewQuery.isError ? (
              <div className="rounded-comfortable border border-border-cream bg-ivory px-4 py-6 text-body-sm text-stone-gray">
                {t("workspace.catalog.dataPreviewUnavailable")}
              </div>
            ) : previewData && previewData.columns.length > 0 ? (
              <div className="overflow-hidden rounded-comfortable border border-border-cream bg-ivory">
                <div className="max-h-[56vh] overflow-auto">
                  <table className="min-w-full border-separate border-spacing-0 text-left text-caption">
                    <thead className="sticky top-0 z-10 bg-warm-sand">
                      <tr>
                        <th className="sticky left-0 z-20 w-12 border-b border-r border-border-cream bg-warm-sand px-3 py-2 text-label text-olive-gray">
                          #
                        </th>
                        {previewData.columns.map((column) => (
                          <th
                            key={column.name}
                            className="min-w-36 whitespace-nowrap border-b border-r border-border-cream px-3 py-2 align-top"
                          >
                            <span className="block text-label font-medium text-near-black">
                              {getColumnDisplayName(column)}
                            </span>
                            <span className="block pt-0.5 text-[11px] uppercase text-stone-gray">
                              {getColumnDisplayName(column) !== column.name
                                ? `${column.name} · ${column.type || t("workspace.catalog.dataPreviewUnknownType")}`
                                : (column.type || t("workspace.catalog.dataPreviewUnknownType"))}
                            </span>
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {previewData.rows.length === 0 ? (
                        <tr>
                          <td
                            colSpan={previewData.columns.length + 1}
                            className="px-3 py-8 text-center text-stone-gray"
                          >
                            {t("workspace.catalog.dataPreviewEmptyRows")}
                          </td>
                        </tr>
                      ) : (
                        previewData.rows.map((row, rowIndex) => (
                          <tr key={`${previewOffset}-${rowIndex}`} className="odd:bg-parchment/35">
                            <td className="sticky left-0 border-b border-r border-border-cream bg-inherit px-3 py-2 text-label text-stone-gray">
                              {previewOffset + rowIndex + 1}
                            </td>
                            {previewData.columns.map((column) => (
                              <td
                                key={column.name}
                                className="max-w-72 border-b border-r border-border-cream px-3 py-2 align-top text-charcoal-warm"
                              >
                                <span className="block max-h-20 overflow-hidden text-ellipsis whitespace-pre-wrap break-words">
                                  {formatCellValue(row[column.name])}
                                </span>
                              </td>
                            ))}
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <div className="rounded-comfortable border border-border-cream bg-ivory px-4 py-6 text-body-sm text-stone-gray">
                {t("workspace.catalog.dataPreviewEmpty")}
              </div>
            )}
          </div>

          <div className="flex items-center justify-between gap-3 border-t border-border-cream px-5 py-3">
            <p className="text-label text-stone-gray">
              {t("workspace.catalog.dataPreviewPage", {
                start:
                  previewData && previewData.rowCount > 0
                    ? previewData.offset + 1
                    : 0,
                end: previewData
                  ? previewData.offset + previewData.rows.length
                  : 0,
              })}
            </p>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setPreviewOffset((value) => Math.max(0, value - PREVIEW_LIMIT))}
                disabled={previewOffset === 0 || previewQuery.isFetching}
              >
                <ChevronLeft className="h-4 w-4" />
                {t("workspace.catalog.previousPage")}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setPreviewOffset((value) => value + PREVIEW_LIMIT)}
                disabled={!previewData?.hasMore || previewQuery.isFetching}
              >
                {t("workspace.catalog.nextPage")}
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={entryToDelete !== null} onOpenChange={(open) => !open && setEntryToDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("workspace.catalog.deleteConfirmTitle")}</DialogTitle>
            <DialogDescription>
              {t("workspace.catalog.deleteConfirmDescription", {
                name: entryToDelete?.humanLabel ?? "",
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setEntryToDelete(null)}
              disabled={deleteMutation.isPending}
            >
              {t("workspace.catalog.cancelDelete")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={handleConfirmDelete}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? t("workspace.catalog.deleting") : t("workspace.catalog.confirmDelete")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}

const PREVIEW_LIMIT = 100;

function getColumnDisplayName(column: { name: string; label?: string; originalName?: string; description?: string }) {
  return column.description || column.originalName || column.label || column.name;
}

function formatCellValue(value: unknown): string {
  if (value === null || typeof value === "undefined") {
    return "NULL";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
