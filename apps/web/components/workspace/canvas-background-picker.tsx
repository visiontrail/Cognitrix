"use client";

import { useMemo, useState } from "react";
import { Check, Paintbrush } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useI18n } from "@/lib/i18n/context";
import { useWorkspaceStore } from "@/stores/workspace-store";
import {
  CANVAS_BACKGROUND_GROUP_ORDER,
  CANVAS_BACKGROUND_PRESETS,
  composeCanvasBackgroundStyle,
  resolveCanvasBackgroundPreset,
  type CanvasBackgroundGroup,
} from "@/lib/workspace/canvas-backgrounds";
import { cn } from "@/lib/utils";

const GROUP_LABEL_KEY: Record<CanvasBackgroundGroup, string> = {
  surface: "workspace.canvasBackground.group.surface",
  grid: "workspace.canvasBackground.group.grid",
  editorial: "workspace.canvasBackground.group.editorial",
  atmosphere: "workspace.canvasBackground.group.atmosphere",
};

export function CanvasBackgroundPicker() {
  const { t } = useI18n();
  const canvasFormat = useWorkspaceStore((s) => s.canvasFormat);
  const canvasBackgrounds = useWorkspaceStore((s) => s.canvasBackgrounds);
  const setCanvasBackground = useWorkspaceStore((s) => s.setCanvasBackground);
  const [open, setOpen] = useState(false);

  const activePreset = resolveCanvasBackgroundPreset(canvasFormat.id, canvasBackgrounds);
  const activeStyle = composeCanvasBackgroundStyle(activePreset);

  const grouped = useMemo(
    () =>
      CANVAS_BACKGROUND_GROUP_ORDER.map((group) => ({
        group,
        presets: CANVAS_BACKGROUND_PRESETS.filter((preset) => preset.group === group),
      })).filter((entry) => entry.presets.length > 0),
    []
  );

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              aria-label={t("workspace.canvasBackground.label")}
              className="gap-2"
            >
              <span
                aria-hidden="true"
                className="h-4 w-4 shrink-0 rounded-[5px] border border-black/10 shadow-inner"
                style={activeStyle}
              />
              <Paintbrush className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
        </TooltipTrigger>
        <TooltipContent>{t("workspace.canvasBackground.label")}</TooltipContent>
      </Tooltip>

      <DropdownMenuContent align="end" className="w-[332px] p-3">
        <p className="px-0.5 pb-2 font-serif text-feature text-near-black">
          {t("workspace.canvasBackground.heading")}
        </p>
        <div className="flex flex-col gap-3">
          {grouped.map(({ group, presets }) => (
            <section key={group}>
              <p className="mb-1.5 px-0.5 text-label uppercase tracking-[0.08em] text-stone-gray">
                {t(GROUP_LABEL_KEY[group])}
              </p>
              <div className="grid grid-cols-4 gap-2">
                {presets.map((preset) => {
                  const selected = preset.id === activePreset.id;
                  return (
                    <Tooltip key={preset.id}>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          aria-label={t(preset.labelKey)}
                          aria-pressed={selected}
                          onClick={() => {
                            setCanvasBackground(preset.id);
                            setOpen(false);
                          }}
                          className={cn(
                            "group relative aspect-[4/3] w-full overflow-hidden rounded-comfortable border transition",
                            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terracotta focus-visible:ring-offset-1",
                            selected
                              ? "border-terracotta ring-2 ring-terracotta/35"
                              : "border-border-cream hover:border-terracotta/60 hover:shadow-ring-warm"
                          )}
                        >
                          <span
                            aria-hidden="true"
                            className="absolute inset-0"
                            style={composeCanvasBackgroundStyle(preset)}
                          />
                          {selected && (
                            <span
                              aria-hidden="true"
                              className="absolute right-1 top-1 flex h-4 w-4 items-center justify-center rounded-full bg-terracotta text-white shadow"
                            >
                              <Check className="h-3 w-3" />
                            </span>
                          )}
                        </button>
                      </TooltipTrigger>
                      <TooltipContent>{t(preset.labelKey)}</TooltipContent>
                    </Tooltip>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
        <p className="mt-3 px-0.5 text-label text-stone-gray">
          {t("workspace.canvasBackground.perFormatHint")}
        </p>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
