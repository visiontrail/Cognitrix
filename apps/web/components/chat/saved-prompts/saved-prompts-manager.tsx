"use client";

import { useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useArchiveSavedPrompt, useSavedPrompts } from "@/hooks/use-saved-prompts";
import { useI18n } from "@/lib/i18n/context";
import type { SavedPrompt } from "@/lib/saved-prompts/types";
import { cn } from "@/lib/utils";

export function SavedPromptsManager({
  open,
  onOpenChange,
  onCreate,
  onEdit,
  onInsert,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: () => void;
  onEdit: (prompt: SavedPrompt) => void;
  onInsert: (prompt: SavedPrompt) => void;
}) {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  const query = useSavedPrompts({ query: search }, open);
  const archiveMutation = useArchiveSavedPrompt();

  const prompts = query.data ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("savedPrompts.manager.title")}</DialogTitle>
        </DialogHeader>

        <div className="flex items-center gap-2">
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("savedPrompts.manager.searchPlaceholder")}
            aria-label={t("savedPrompts.manager.searchAria")}
          />
          <Button type="button" size="sm" onClick={onCreate} className="shrink-0">
            <Plus className="h-4 w-4" />
            {t("savedPrompts.manager.create")}
          </Button>
        </div>

        <div className="max-h-[50vh] space-y-2 overflow-y-auto">
          {query.isLoading ? (
            <p className="px-1 py-6 text-center text-body-sm text-stone-gray">
              {t("savedPrompts.manager.loading")}
            </p>
          ) : query.isError ? (
            <p className="px-1 py-6 text-center text-body-sm text-red-600" role="alert">
              {t("savedPrompts.manager.error")}
            </p>
          ) : prompts.length === 0 ? (
            <p className="px-1 py-8 text-center text-body-sm text-stone-gray">
              {search.trim()
                ? t("savedPrompts.manager.emptySearch")
                : t("savedPrompts.manager.empty")}
            </p>
          ) : (
            prompts.map((prompt) => (
              <div
                key={prompt.id}
                className="rounded-comfortable border border-border-cream bg-parchment px-3 py-2.5"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-body-sm font-medium text-near-black">{prompt.name}</p>
                    <p className="mt-0.5 line-clamp-2 text-caption text-stone-gray">{prompt.body}</p>
                    {prompt.variables.length > 0 ? (
                      <p className="mt-1 text-[11px] text-terracotta">
                        {t("savedPrompts.manager.variableCount", { count: prompt.variables.length })}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => onInsert(prompt)}
                    >
                      {t("savedPrompts.manager.insert")}
                    </Button>
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      onClick={() => onEdit(prompt)}
                      aria-label={t("savedPrompts.manager.edit")}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      onClick={() => setConfirmingId(prompt.id)}
                      aria-label={t("savedPrompts.manager.delete")}
                      disabled={archiveMutation.isPending}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>

                {confirmingId === prompt.id ? (
                  <div
                    className={cn(
                      "mt-2 flex items-center justify-between gap-2 rounded-comfortable",
                      "border border-red-200 bg-red-50 px-3 py-2",
                    )}
                  >
                    <span className="text-caption text-near-black">
                      {t("savedPrompts.manager.deleteConfirm")}
                    </span>
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => setConfirmingId(null)}
                      >
                        {t("savedPrompts.manager.deleteConfirmNo")}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="destructive"
                        disabled={archiveMutation.isPending}
                        onClick={async () => {
                          await archiveMutation.mutateAsync(prompt.id);
                          setConfirmingId(null);
                        }}
                      >
                        {t("savedPrompts.manager.deleteConfirmYes")}
                      </Button>
                    </div>
                  </div>
                ) : null}
              </div>
            ))
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
