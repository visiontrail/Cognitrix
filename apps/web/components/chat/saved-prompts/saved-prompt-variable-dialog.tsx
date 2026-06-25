"use client";

import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/lib/i18n/context";
import { renderTemplate } from "@/lib/saved-prompts/template";
import type { SavedPrompt } from "@/lib/saved-prompts/types";

export function SavedPromptVariableDialog({
  prompt,
  open,
  onOpenChange,
  onConfirm,
}: {
  prompt: SavedPrompt | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // Called with the fully-rendered prompt text only after confirmation.
  onConfirm: (renderedText: string) => void;
}) {
  const { t } = useI18n();
  const [values, setValues] = useState<Record<string, string>>({});

  useEffect(() => {
    if (open) setValues({});
  }, [open, prompt?.id]);

  const variables = prompt?.variables ?? [];
  const allFilled = variables.every((variable) => (values[variable] ?? "").trim().length > 0);
  const preview = useMemo(() => {
    if (!prompt) return "";
    return renderTemplate(prompt.body, values);
  }, [prompt, values]);

  const handleConfirm = () => {
    if (!prompt || !allFilled) return;
    onConfirm(renderTemplate(prompt.body, values));
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("savedPrompts.variable.title")}</DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          {variables.map((variable) => (
            <div key={variable} className="space-y-1.5">
              <label
                className="text-caption font-medium text-charcoal-warm"
                htmlFor={`saved-prompt-var-${variable}`}
              >
                {variable}
              </label>
              <Input
                id={`saved-prompt-var-${variable}`}
                value={values[variable] ?? ""}
                onChange={(event) =>
                  setValues((current) => ({ ...current, [variable]: event.target.value }))
                }
                placeholder={t("savedPrompts.variable.fieldPlaceholder", { name: variable })}
              />
            </div>
          ))}

          <div className="space-y-1.5">
            <span className="text-caption font-medium text-charcoal-warm">
              {t("savedPrompts.variable.previewLabel")}
            </span>
            <p className="max-h-32 overflow-y-auto whitespace-pre-wrap rounded-generous border border-border-cream bg-parchment px-3 py-2 text-body-sm text-near-black">
              {preview}
            </p>
          </div>
        </div>

        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t("savedPrompts.variable.cancel")}
          </Button>
          <Button type="button" onClick={handleConfirm} disabled={!allFilled}>
            {t("savedPrompts.variable.insert")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
