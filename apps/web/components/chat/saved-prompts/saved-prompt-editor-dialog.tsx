"use client";

import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useCreateSavedPrompt, useUpdateSavedPrompt } from "@/hooks/use-saved-prompts";
import { useI18n } from "@/lib/i18n/context";
import { SavedPromptApiError } from "@/lib/saved-prompts/api";
import { parseVariables } from "@/lib/saved-prompts/template";
import {
  SAVED_PROMPT_CAPABILITIES,
  type SavedPrompt,
  type SavedPromptCapability,
} from "@/lib/saved-prompts/types";
import { cn } from "@/lib/utils";

export function SavedPromptEditorDialog({
  open,
  prompt,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  prompt: SavedPrompt | null;
  onOpenChange: (open: boolean) => void;
  onSaved?: (prompt: SavedPrompt) => void;
}) {
  const { t } = useI18n();
  const createMutation = useCreateSavedPrompt();
  const updateMutation = useUpdateSavedPrompt();

  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [capabilities, setCapabilities] = useState<Set<SavedPromptCapability>>(() => new Set());
  const [serverError, setServerError] = useState<string | null>(null);

  // Reset form whenever the dialog opens (for a fresh create or a given prompt).
  useEffect(() => {
    if (!open) return;
    setName(prompt?.name ?? "");
    setBody(prompt?.body ?? "");
    setCapabilities(new Set(prompt?.capabilities ?? []));
    setServerError(null);
  }, [open, prompt]);

  const parse = useMemo(() => parseVariables(body), [body]);
  const variableError = useMemo(() => {
    if (parse.ok) return null;
    if (parse.errorCode === "PROMPT_VARIABLE_AMBIGUOUS") {
      return t("savedPrompts.editor.errorAmbiguousVariable", { token: parse.token });
    }
    return t("savedPrompts.editor.errorInvalidVariable", { token: parse.token });
  }, [parse, t]);

  const isSaving = createMutation.isPending || updateMutation.isPending;
  const canSave = name.trim().length > 0 && body.trim().length > 0 && parse.ok && !isSaving;

  const handleSave = async () => {
    if (!canSave) return;
    setServerError(null);
    const payload = {
      name: name.trim(),
      body: body.trim(),
      capabilities: Array.from(capabilities),
    };
    try {
      const saved = prompt
        ? await updateMutation.mutateAsync({ promptId: prompt.id, input: payload })
        : await createMutation.mutateAsync(payload);
      onSaved?.(saved);
      onOpenChange(false);
    } catch (error) {
      setServerError(
        error instanceof SavedPromptApiError ? error.message : String((error as Error)?.message ?? error),
      );
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>
            {prompt ? t("savedPrompts.editor.editTitle") : t("savedPrompts.editor.createTitle")}
          </DialogTitle>
          <DialogDescription>{t("savedPrompts.editor.variableHelp")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-caption font-medium text-charcoal-warm" htmlFor="saved-prompt-name">
              {t("savedPrompts.editor.nameLabel")}
            </label>
            <Input
              id="saved-prompt-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("savedPrompts.editor.namePlaceholder")}
              disabled={isSaving}
              autoFocus
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-caption font-medium text-charcoal-warm" htmlFor="saved-prompt-body">
              {t("savedPrompts.editor.bodyLabel")}
            </label>
            <Textarea
              id="saved-prompt-body"
              value={body}
              onChange={(event) => setBody(event.target.value)}
              placeholder={t("savedPrompts.editor.bodyPlaceholder")}
              disabled={isSaving}
              rows={5}
              aria-invalid={Boolean(variableError)}
            />
            {variableError ? (
              <p className="text-caption text-red-600" role="alert">
                {variableError}
              </p>
            ) : (
              <p className="text-caption text-stone-gray">
                {parse.ok && parse.variables.length > 0
                  ? t("savedPrompts.editor.variablesDetected", { variables: parse.variables.join(", ") })
                  : t("savedPrompts.editor.variablesNone")}
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <span className="text-caption font-medium text-charcoal-warm">
              {t("savedPrompts.editor.capabilitiesLabel")}
            </span>
            <div className="flex flex-wrap gap-2">
              {SAVED_PROMPT_CAPABILITIES.map((capability) => {
                const checked = capabilities.has(capability);
                return (
                  <button
                    key={capability}
                    type="button"
                    role="checkbox"
                    aria-checked={checked}
                    disabled={isSaving}
                    onClick={() =>
                      setCapabilities((current) => {
                        const next = new Set(current);
                        if (next.has(capability)) next.delete(capability);
                        else next.add(capability);
                        return next;
                      })
                    }
                    className={cn(
                      "rounded-full border px-3 py-1 text-caption font-medium transition-colors",
                      checked
                        ? "border-focus-blue/40 bg-focus-blue/10 text-focus-blue"
                        : "border-border-cream bg-parchment text-stone-gray hover:text-near-black",
                    )}
                  >
                    {t(`savedPrompts.capability.${capability}`)}
                  </button>
                );
              })}
            </div>
          </div>

          {serverError ? (
            <p className="text-caption text-red-600" role="alert">
              {serverError}
            </p>
          ) : null}
        </div>

        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSaving}>
            {t("savedPrompts.editor.cancel")}
          </Button>
          <Button type="button" onClick={handleSave} disabled={!canSave}>
            {isSaving ? t("savedPrompts.editor.saving") : t("savedPrompts.editor.save")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
