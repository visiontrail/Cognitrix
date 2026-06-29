"use client";

import { memo } from "react";
import { type NodeProps } from "@xyflow/react";
import { Layers, Trash2, Ungroup } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useI18n } from "@/lib/i18n/context";
import { useWorkspaceStore } from "@/stores/workspace-store";
import type { SectionNodeData } from "@/types/workspace";
import { ResizableNode } from "./resizable-node";

const MIN_SECTION_WIDTH = 180;
const MIN_SECTION_HEIGHT = 120;

function SectionNodeComponent({ id, data, selected, width, height }: NodeProps) {
  const { t } = useI18n();
  const nodeData = data as unknown as SectionNodeData;
  const removeNodes = useWorkspaceStore((s) => s.removeNodes);
  const ungroupNodes = useWorkspaceStore((s) => s.ungroupNodes);
  const nodeWidth = width ?? nodeData.width ?? 320;
  const nodeHeight = height ?? nodeData.height ?? 220;

  return (
    <section
      className={`section-node-drag-handle relative h-full rounded-md border bg-[#fffdf7]/45 shadow-[inset_0_0_0_1px_rgba(255,255,255,0.7)] dark:bg-white/[0.06] dark:shadow-[inset_0_0_0_1px_rgba(255,255,255,0.08)] ${
        selected ? "border-terracotta" : "border-dashed border-[#cfc5b2] dark:border-white/25"
      }`}
      style={{
        width: nodeWidth,
        height: nodeHeight,
      }}
    >
      <ResizableNode
        id={id}
        selected={selected}
        minWidth={MIN_SECTION_WIDTH}
        minHeight={MIN_SECTION_HEIGHT}
      />
      <div className="canvas-export-ignore pointer-events-none absolute left-2 top-2 flex items-center gap-1.5 rounded border border-[#d8d1c1] bg-ivory/95 px-2 py-1 text-[11px] font-medium text-stone-gray shadow-whisper backdrop-blur dark:border-white/10">
        <Layers className="h-3.5 w-3.5 text-terracotta" aria-hidden="true" />
        <span className="max-w-32 truncate">{nodeData.title || t("workspace.selection.defaultGroupTitle")}</span>
      </div>
      {selected && (
        <div
          className="canvas-export-ignore nodrag pointer-events-auto absolute right-2 top-2 flex items-center gap-0.5 rounded border border-border-cream bg-ivory/95 p-1 shadow-whisper backdrop-blur"
          onPointerDown={(event) => event.stopPropagation()}
        >
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                className="h-6 w-6"
                aria-label={t("workspace.selection.ungroup")}
                onClick={() => ungroupNodes([id])}
              >
                <Ungroup className="h-3.5 w-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("workspace.selection.ungroup")}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                className="h-6 w-6 hover:text-error-crimson"
                aria-label={t("workspace.selection.delete")}
                onClick={() => removeNodes([id])}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("workspace.selection.delete")}</TooltipContent>
          </Tooltip>
        </div>
      )}
    </section>
  );
}

export const SectionNode = memo(SectionNodeComponent);
