"use client";

import { memo, useState, useCallback, useRef, type PointerEvent as ReactPointerEvent } from "react";
import { type NodeProps } from "@xyflow/react";
import { MoveHorizontal, RotateCw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useWorkspaceStore } from "@/stores/workspace-store";
import { useI18n } from "@/lib/i18n/context";
import type { DividerNodeData } from "@/types/workspace";

const DEFAULT_DIVIDER_WIDTH = 480;
const MIN_DIVIDER_WIDTH = 120;
const MAX_DIVIDER_WIDTH = 1400;
const MIN_DIVIDER_ROTATION = -180;
const MAX_DIVIDER_ROTATION = 180;

function clampNumber(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function DividerNodeComponent({ id, data, selected, width }: NodeProps) {
  const { t } = useI18n();
  const nodeData = data as unknown as DividerNodeData;
  const updateNode = useWorkspaceStore((s) => s.updateNode);
  const removeNode = useWorkspaceStore((s) => s.removeNode);
  const viewport = useWorkspaceStore((s) => s.viewport);
  const dividerRef = useRef<HTMLDivElement>(null);

  const [isEditingLabel, setIsEditingLabel] = useState(false);
  const [labelDraft, setLabelDraft] = useState(nodeData.label ?? "");
  const [isHovered, setIsHovered] = useState(false);

  const nodeWidth = width ?? nodeData.width ?? DEFAULT_DIVIDER_WIDTH;
  const rotation = nodeData.rotation ?? 0;
  const lineStyle = nodeData.lineStyle ?? "solid";
  const hasLabel = !!nodeData.label;

  const handleLabelSave = useCallback(() => {
    updateNode(id, { data: { label: labelDraft.trim() || undefined } as any });
    setIsEditingLabel(false);
  }, [id, labelDraft, updateNode]);

  const handleStyleToggle = useCallback(() => {
    updateNode(id, { data: { lineStyle: lineStyle === "solid" ? "dashed" : "solid" } as any });
  }, [id, lineStyle, updateNode]);

  const handleWidthChange = useCallback(
    (value: number) => {
      const nextWidth = clampNumber(Math.round(value), MIN_DIVIDER_WIDTH, MAX_DIVIDER_WIDTH);
      updateNode(id, { width: nextWidth, data: { width: nextWidth } as any });
    },
    [id, updateNode]
  );

  const handleRotationChange = useCallback(
    (value: number) => {
      const nextRotation = clampNumber(Math.round(value), MIN_DIVIDER_ROTATION, MAX_DIVIDER_ROTATION);
      updateNode(id, { data: { rotation: nextRotation } as any });
    },
    [id, updateNode]
  );

  const handleLengthPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLButtonElement>) => {
      if (event.pointerType === "mouse" && event.button !== 0) return;

      event.preventDefault();
      event.stopPropagation();

      const startClientX = event.clientX;
      const startClientY = event.clientY;
      const startWidth = nodeWidth;
      const zoom = viewport.zoom || 1;
      const radians = rotation * (Math.PI / 180);
      const axisX = Math.cos(radians);
      const axisY = Math.sin(radians);

      const handlePointerMove = (moveEvent: PointerEvent) => {
        const projectedDelta =
          (moveEvent.clientX - startClientX) * axisX + (moveEvent.clientY - startClientY) * axisY;
        handleWidthChange(startWidth + projectedDelta / zoom);
      };

      const handlePointerUp = () => {
        window.removeEventListener("pointermove", handlePointerMove);
        window.removeEventListener("pointerup", handlePointerUp);
        window.removeEventListener("pointercancel", handlePointerUp);
      };

      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", handlePointerUp);
      window.addEventListener("pointercancel", handlePointerUp);
    },
    [handleWidthChange, nodeWidth, rotation, viewport.zoom]
  );

  const handleRotationPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLButtonElement>) => {
      if (event.pointerType === "mouse" && event.button !== 0) return;

      event.preventDefault();
      event.stopPropagation();

      const dividerElement = dividerRef.current;
      if (!dividerElement) return;

      const rect = dividerElement.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const startPointerAngle = Math.atan2(event.clientY - centerY, event.clientX - centerX) * (180 / Math.PI);
      const rotationOffset = rotation - startPointerAngle;

      const handlePointerMove = (moveEvent: PointerEvent) => {
        const pointerAngle =
          Math.atan2(moveEvent.clientY - centerY, moveEvent.clientX - centerX) * (180 / Math.PI);
        handleRotationChange(pointerAngle + rotationOffset);
      };

      const handlePointerUp = () => {
        window.removeEventListener("pointermove", handlePointerMove);
        window.removeEventListener("pointerup", handlePointerUp);
        window.removeEventListener("pointercancel", handlePointerUp);
      };

      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", handlePointerUp);
      window.addEventListener("pointercancel", handlePointerUp);
    },
    [handleRotationChange, rotation]
  );

  return (
    <div
      ref={dividerRef}
      className="divider-node-drag-handle relative flex items-center"
      style={{
        width: nodeWidth,
        height: 24,
        cursor: "grab",
        transform: `rotate(${rotation}deg)`,
        transformOrigin: "center",
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* Left line segment */}
      <div
        className="flex-1"
        style={{
          borderTopWidth: 1.5,
          borderTopStyle: lineStyle,
          borderTopColor: "#c4c0b6",
        }}
      />

      {/* Center label / click-to-add label */}
      {isEditingLabel ? (
        <input
          value={labelDraft}
          onChange={(e) => setLabelDraft(e.target.value)}
          onBlur={handleLabelSave}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleLabelSave();
            if (e.key === "Escape") {
              setLabelDraft(nodeData.label ?? "");
              setIsEditingLabel(false);
            }
          }}
          className="nodrag mx-2 w-28 rounded border border-border-cream bg-ivory px-1 text-center text-xs text-stone-gray focus:outline-none"
          autoFocus
        />
      ) : (
        <button
          type="button"
          className="nodrag mx-2 cursor-text rounded px-2 py-0.5 text-xs text-stone-gray transition-colors hover:bg-warm-sand"
          onDoubleClick={() => setIsEditingLabel(true)}
          title={t("workspace.divider.editLabel")}
        >
          {hasLabel ? nodeData.label : (
            <span className="opacity-40">{t("workspace.divider.addLabel")}</span>
          )}
        </button>
      )}

      {/* Right line segment */}
      <div
        className="flex-1"
        style={{
          borderTopWidth: 1.5,
          borderTopStyle: lineStyle,
          borderTopColor: "#c4c0b6",
        }}
      />

      {(isHovered || selected) && (
        <>
          <div className="canvas-export-ignore nodrag pointer-events-none absolute -top-8 left-1/2 flex -translate-x-1/2 items-center gap-1.5">
            <button
              type="button"
              className="pointer-events-auto flex h-6 w-6 touch-none items-center justify-center rounded-full border border-border-cream bg-ivory/95 text-stone-gray shadow-whisper backdrop-blur transition-colors hover:border-terracotta hover:text-terracotta active:cursor-grabbing"
              aria-label={t("workspace.divider.angle")}
              title={t("workspace.divider.angle")}
              onPointerDown={handleRotationPointerDown}
            >
              <RotateCw className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
            <span className="rounded border border-border-cream bg-ivory/95 px-1.5 py-0.5 text-[10px] tabular-nums text-stone-gray shadow-whisper backdrop-blur">
              {rotation}°
            </span>
          </div>

          <button
            type="button"
            className="canvas-export-ignore nodrag absolute -right-3 top-1/2 flex h-6 w-6 -translate-y-1/2 touch-none items-center justify-center rounded-full border border-border-cream bg-ivory/95 text-stone-gray shadow-whisper backdrop-blur transition-colors hover:border-terracotta hover:text-terracotta active:cursor-grabbing"
            aria-label={t("workspace.divider.length")}
            title={t("workspace.divider.length")}
            onPointerDown={handleLengthPointerDown}
          >
            <MoveHorizontal className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
          <span className="canvas-export-ignore nodrag pointer-events-none absolute -right-4 top-full mt-1 rounded border border-border-cream bg-ivory/95 px-1.5 py-0.5 text-[10px] tabular-nums text-stone-gray shadow-whisper backdrop-blur">
            {Math.round(nodeWidth)}
          </span>

          <div
            className="canvas-export-ignore nodrag pointer-events-auto absolute -bottom-8 right-0 flex items-center gap-0.5 rounded border border-border-cream bg-ivory/95 px-1.5 py-1 shadow-whisper backdrop-blur"
            onPointerDown={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              className="rounded px-1.5 py-0.5 text-xs text-stone-gray transition-colors hover:bg-warm-sand hover:text-near-black"
              onClick={handleStyleToggle}
              title={t("workspace.divider.toggleStyle")}
            >
              {lineStyle === "solid" ? "---" : "- -"}
            </button>
            <Button
              variant="ghost"
              size="icon-sm"
              className="h-5 w-5 hover:text-error-crimson"
              aria-label={t("workspace.divider.delete")}
              onClick={() => removeNode(id)}
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

export const DividerNode = memo(DividerNodeComponent);
