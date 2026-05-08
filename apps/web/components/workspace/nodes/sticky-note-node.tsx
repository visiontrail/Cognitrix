"use client";

import { memo, useState, useCallback, useEffect, useRef, type PointerEvent as ReactPointerEvent } from "react";
import { type NodeProps } from "@xyflow/react";
import { Check, RotateCw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useWorkspaceStore } from "@/stores/workspace-store";
import { useI18n } from "@/lib/i18n/context";
import type { StickyNoteNodeData, StickyNoteColor } from "@/types/workspace";
import { ResizableNode } from "./resizable-node";

const MIN_STICKY_WIDTH = 160;
const MIN_STICKY_HEIGHT = 120;
const DEFAULT_STICKY_WIDTH = 240;
const DEFAULT_STICKY_HEIGHT = 200;
const MIN_STICKY_ROTATION = -45;
const MAX_STICKY_ROTATION = 45;

const COLOR_MAP: Record<
  StickyNoteColor,
  { bg: string; border: string; top: string; fold: string; ink: string; shadow: string }
> = {
  yellow: { bg: "#fff2b5", border: "#e0cf7a", top: "#fff7cf", fold: "#f3df91", ink: "#3f3a25", shadow: "rgba(117, 94, 27, 0.22)" },
  blue:   { bg: "#dcecf4", border: "#9fbccc", top: "#edf7fb", fold: "#c1d9e5", ink: "#273b45", shadow: "rgba(37, 77, 96, 0.18)" },
  green:  { bg: "#e2efd7", border: "#b5cca4", top: "#f0f7e9", fold: "#cadcb9", ink: "#2f3f2a", shadow: "rgba(56, 86, 40, 0.18)" },
  pink:   { bg: "#f5dce1", border: "#d9a8b3", top: "#faedf0", fold: "#e7c1c9", ink: "#482f36", shadow: "rgba(103, 46, 60, 0.17)" },
};

const COLORS: StickyNoteColor[] = ["yellow", "blue", "green", "pink"];

function clampNumber(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function StickyNoteNodeComponent({ id, data, selected, width, height }: NodeProps) {
  const { t } = useI18n();
  const nodeData = data as unknown as StickyNoteNodeData;
  const updateNode = useWorkspaceStore((s) => s.updateNode);
  const removeNode = useWorkspaceStore((s) => s.removeNode);
  const noteRef = useRef<HTMLDivElement>(null);

  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(nodeData.content);
  const [isHovered, setIsHovered] = useState(false);

  useEffect(() => {
    setDraft(nodeData.content);
  }, [nodeData.content]);

  const handleSave = useCallback(() => {
    updateNode(id, { data: { content: draft } as any });
    setIsEditing(false);
  }, [id, draft, updateNode]);

  useEffect(() => {
    if (!selected && isEditing) handleSave();
  }, [selected, isEditing, handleSave]);

  const handleColorChange = useCallback(
    (color: StickyNoteColor) => {
      updateNode(id, { data: { color } as any });
    },
    [id, updateNode]
  );

  const handleRotationChange = useCallback(
    (value: number) => {
      const nextRotation = clampNumber(Math.round(value), MIN_STICKY_ROTATION, MAX_STICKY_ROTATION);
      updateNode(id, { data: { rotation: nextRotation } as any });
    },
    [id, updateNode]
  );

  const nodeWidth = width ?? nodeData.width ?? DEFAULT_STICKY_WIDTH;
  const nodeHeight = height ?? nodeData.height ?? DEFAULT_STICKY_HEIGHT;
  const color = nodeData.color ?? "yellow";
  const palette = COLOR_MAP[color];
  const rotation = nodeData.rotation ?? 0;

  const handleRotationPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLButtonElement>) => {
      if (event.pointerType === "mouse" && event.button !== 0) return;

      event.preventDefault();
      event.stopPropagation();

      const noteElement = noteRef.current;
      if (!noteElement) return;

      const rect = noteElement.getBoundingClientRect();
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
      ref={noteRef}
      className="relative flex flex-col rounded-[3px]"
      style={{
        width: nodeWidth,
        height: nodeHeight,
        backgroundColor: palette.bg,
        backgroundImage: `linear-gradient(180deg, rgba(255,255,255,0.55) 0%, rgba(255,255,255,0.12) 42%, rgba(255,255,255,0) 100%), radial-gradient(rgba(255,255,255,0.55) 0.65px, transparent 0.65px)`,
        backgroundSize: "100% 100%, 10px 10px",
        border: `1px solid ${palette.border}`,
        boxShadow: `0 18px 26px -22px ${palette.shadow}, 0 2px 8px -6px rgba(20,20,19,0.28), inset 0 1px 0 rgba(255,255,255,0.72), inset 0 -12px 20px rgba(0,0,0,0.035)`,
        cursor: isEditing ? "default" : "grab",
        transform: `rotate(${rotation}deg)`,
        transformOrigin: "center",
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <ResizableNode
        id={id}
        selected={selected}
        minWidth={MIN_STICKY_WIDTH}
        minHeight={MIN_STICKY_HEIGHT}
      />

      <div
        aria-hidden="true"
        className="pointer-events-none absolute right-0 top-0 h-8 w-8"
        style={{
          background: `linear-gradient(135deg, transparent 0 50%, ${palette.fold} 51% 100%)`,
          boxShadow: "-1px 1px 2px rgba(20,20,19,0.06)",
        }}
      />

      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-2 top-8 h-px"
        style={{ backgroundColor: "rgba(20,20,19,0.08)" }}
      />

      {/* Header strip */}
      <div
        className="sticky-note-drag-handle relative flex shrink-0 items-center justify-between px-2.5 py-1.5"
        style={{
          background: `linear-gradient(180deg, ${palette.top}, rgba(255,255,255,0.04))`,
          borderBottom: `1px solid rgba(20,20,19,0.06)`,
        }}
      >
        <div className="canvas-export-ignore flex items-center gap-1">
          {COLORS.map((c) => (
            <button
              key={c}
              type="button"
              className={`nodrag h-3.5 w-3.5 rounded-full border shadow-[inset_0_1px_0_rgba(255,255,255,0.55)] transition-transform hover:scale-110 ${
                color === c ? "scale-110 border-near-black/50" : "border-near-black/10"
              }`}
              style={{ backgroundColor: COLOR_MAP[c].bg }}
              aria-label={t("workspace.stickyNote.changeColor")}
              onClick={() => handleColorChange(c)}
            />
          ))}
        </div>
        <div className="canvas-export-ignore flex items-center gap-0.5">
          {isEditing && (
            <Button
              variant="ghost"
              size="icon-sm"
              className="nodrag h-5 w-5"
              aria-label={t("workspace.stickyNote.save")}
              onMouseDown={(e) => e.preventDefault()}
              onClick={handleSave}
            >
              <Check className="h-3 w-3" />
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon-sm"
            className="nodrag h-5 w-5 hover:text-error-crimson"
            aria-label={t("workspace.stickyNote.delete")}
            onClick={() => removeNode(id)}
          >
            <Trash2 className="h-3 w-3" />
          </Button>
        </div>
      </div>

      {(isHovered || selected) && (
        <div
          className="canvas-export-ignore nodrag pointer-events-none absolute -top-8 left-1/2 flex -translate-x-1/2 items-center gap-1.5"
          onPointerDown={(event) => event.stopPropagation()}
        >
          <button
            type="button"
            className="pointer-events-auto flex h-6 w-6 touch-none items-center justify-center rounded-full border border-border-cream bg-ivory/95 text-stone-gray shadow-whisper backdrop-blur transition-colors hover:border-terracotta hover:text-terracotta active:cursor-grabbing"
            aria-label={t("workspace.stickyNote.angle")}
            title={t("workspace.stickyNote.angle")}
            onPointerDown={handleRotationPointerDown}
          >
            <RotateCw className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
          <span className="rounded border border-border-cream bg-ivory/95 px-1.5 py-0.5 text-[10px] tabular-nums text-stone-gray shadow-whisper backdrop-blur">
            {rotation}°
          </span>
        </div>
      )}

      {/* Body */}
      <div className="nodrag min-h-0 flex-1 overflow-hidden px-3 py-2.5">
        {isEditing ? (
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="h-full w-full resize-none bg-transparent text-sm leading-snug focus:outline-none"
            style={{ color: palette.ink }}
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter" && e.metaKey) handleSave();
              if (e.key === "Escape") {
                setDraft(nodeData.content);
                setIsEditing(false);
              }
            }}
          />
        ) : (
          <p
            className="cursor-text whitespace-pre-wrap break-words text-sm leading-snug"
            style={{ color: palette.ink }}
            onDoubleClick={() => setIsEditing(true)}
          >
            {nodeData.content || (
              <span className="opacity-40">{t("workspace.stickyNote.placeholder")}</span>
            )}
          </p>
        )}
      </div>
    </div>
  );
}

export const StickyNoteNode = memo(StickyNoteNodeComponent);
