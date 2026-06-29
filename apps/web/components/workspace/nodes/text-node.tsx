"use client";

import { memo, useState, useCallback, useEffect } from "react";
import { type NodeProps } from "@xyflow/react";
import { Bold, Check, Minus, Pencil, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useWorkspaceStore } from "@/stores/workspace-store";
import { useI18n } from "@/lib/i18n/context";
import {
  resolveCanvasBackgroundPreset,
  resolveCanvasTextColor,
} from "@/lib/workspace/canvas-backgrounds";
import { useTheme } from "@/lib/theme/context";
import type { TextNodeData } from "@/types/workspace";
import { ResizableNode } from "./resizable-node";

const DEFAULT_TEXT_NODE_WIDTH = 480;
const DEFAULT_TEXT_NODE_HEIGHT = 220;
const MIN_TEXT_NODE_WIDTH = 220;
const MIN_TEXT_NODE_HEIGHT = 140;
const DEFAULT_TEXT_FONT_SIZE = 18;
const DEFAULT_TEXT_COLOR = "#3f3d39";
const TEXT_COLORS = ["#3f3d39", "#c96442", "#3f6f5f", "#2457a6", "#7a4c9f"];
const EDITOR_CHROME_HEIGHT = 68;
const EDITOR_TEXTAREA_VERTICAL_SPACE = 44;

function getMinimumEditorHeight(fontSize: number) {
  return Math.ceil(fontSize * 1.45 + EDITOR_CHROME_HEIGHT + EDITOR_TEXTAREA_VERTICAL_SPACE);
}

function TextNodeComponent({ id, data, selected, width }: NodeProps) {
  const { t } = useI18n();
  const { resolvedTheme } = useTheme();
  const nodeData = data as unknown as TextNodeData;
  const updateNode = useWorkspaceStore((s) => s.updateNode);
  const removeNode = useWorkspaceStore((s) => s.removeNode);
  const canvasFormat = useWorkspaceStore((s) => s.canvasFormat);
  const canvasBackgrounds = useWorkspaceStore((s) => s.canvasBackgrounds);

  const [isHovered, setIsHovered] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(nodeData.content);

  useEffect(() => {
    setEditContent(nodeData.content);
  }, [nodeData.content]);

  const handleSave = useCallback(() => {
    updateNode(id, { data: { content: editContent } as any });
    setIsEditing(false);
  }, [id, editContent, updateNode]);

  useEffect(() => {
    if (!selected && isEditing) {
      handleSave();
    }
  }, [handleSave, isEditing, selected]);

  const handleStyleChange = useCallback(
    (style: Partial<TextNodeData>) => {
      updateNode(id, { data: style as any });
    },
    [id, updateNode]
  );

  const nodeWidth = width ?? nodeData.width ?? DEFAULT_TEXT_NODE_WIDTH;
  // Always derive edit-panel height from stored data, never from React Flow's measured height.
  // In view mode the node is auto-sized to text content (shorter), so NodeProps.height reflects
  // that short measurement — using it here would collapse the editing panel incorrectly.
  const nodeHeight = nodeData.height ?? DEFAULT_TEXT_NODE_HEIGHT;
  const fontSize = nodeData.fontSize ?? DEFAULT_TEXT_FONT_SIZE;
  const fontWeight = nodeData.fontWeight ?? "normal";
  const color = nodeData.color ?? DEFAULT_TEXT_COLOR;
  const backgroundPreset = resolveCanvasBackgroundPreset(canvasFormat.id, canvasBackgrounds, resolvedTheme);
  const displayColor = resolveCanvasTextColor(color, backgroundPreset);
  const editorHeight = Math.max(nodeHeight, MIN_TEXT_NODE_HEIGHT, getMinimumEditorHeight(fontSize));
  const textStyle = {
    color,
    fontSize,
    fontWeight,
    lineHeight: 1.45,
  };
  const displayTextStyle = {
    ...textStyle,
    color: displayColor,
  };

  const textLayer = (
    <p className="whitespace-pre-wrap break-words" style={displayTextStyle}>
      {nodeData.content}
    </p>
  );

  // Editing mode: the edit panel is rendered as an absolute overlay so React Flow only ever
  // measures the invisible text placeholder beneath it — the same footprint as view mode.
  // This keeps the MiniMap size consistent (it always shows the text content dimensions,
  // not the editing UI dimensions) regardless of whether the node is being edited.
  if (isEditing) {
    return (
      <div className="relative" style={{ width: nodeWidth }}>
        {/* Invisible text placeholder: React Flow's ResizeObserver measures this element,
            so the MiniMap and node bounds always reflect the actual text content size. */}
        <p
          className="whitespace-pre-wrap break-words pointer-events-none select-none"
          style={{ ...textStyle, visibility: "hidden" }}
          aria-hidden="true"
        >
          {nodeData.content || "\u00A0"}
        </p>

        {/* Editing overlay: absolute-positioned so its height does NOT feed back into
            React Flow's measured node dimensions. */}
        <div
          data-testid="text-node-editor"
          className="absolute left-0 top-0 flex flex-col bg-ivory rounded-comfortable border border-terracotta shadow-[0px_0px_0px_2px_#c96442]"
          style={{ width: nodeWidth, height: editorHeight, zIndex: 10 }}
        >
          <ResizableNode
            id={id}
            selected={selected}
            minWidth={MIN_TEXT_NODE_WIDTH}
            minHeight={MIN_TEXT_NODE_HEIGHT}
          />

          <div className="text-node-drag-handle flex items-center gap-2 border-b border-border-cream bg-ivory px-3 py-1.5 cursor-grab active:cursor-grabbing">
            <span className="flex-1 text-label text-stone-gray">{t("workspace.textBlock")}</span>
            <div className="flex items-center gap-0.5 shrink-0">
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("workspace.textBlock.done")}
                onMouseDown={(e) => e.preventDefault()}
                onClick={handleSave}
              >
                <Check className="h-3 w-3 text-terracotta" />
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("workspace.textBlock.delete")}
                onClick={() => removeNode(id)}
                className="hover:text-error-crimson"
              >
                <Trash2 className="h-3 w-3" />
              </Button>
            </div>
          </div>

          <div
            className="nodrag flex items-center gap-1 border-b border-border-cream bg-parchment/70 px-3 py-1.5"
            onMouseDown={(e) => e.preventDefault()}
          >
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t("workspace.textBlock.decreaseTextSize")}
              onClick={() => handleStyleChange({ fontSize: Math.max(12, fontSize - 2) })}
            >
              <Minus className="h-3 w-3" />
            </Button>
            <span className="w-8 text-center text-label text-stone-gray">{fontSize}</span>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t("workspace.textBlock.increaseTextSize")}
              onClick={() => handleStyleChange({ fontSize: Math.min(48, fontSize + 2) })}
            >
              <Plus className="h-3 w-3" />
            </Button>
            <Button
              variant={fontWeight === "bold" ? "secondary" : "ghost"}
              size="icon-sm"
              aria-label={t("workspace.textBlock.toggleBold")}
              onClick={() =>
                handleStyleChange({ fontWeight: fontWeight === "bold" ? "normal" : "bold" })
              }
            >
              <Bold className="h-3.5 w-3.5" />
            </Button>
            <div className="ml-1 flex items-center gap-1">
              {TEXT_COLORS.map((item) => (
                <button
                  key={item}
                  type="button"
                  aria-label={t("workspace.textBlock.setTextColor", { color: item })}
                  className={`h-5 w-5 rounded-full border ${
                    color === item ? "border-near-black ring-2 ring-focus-blue" : "border-border-cream"
                  }`}
                  style={{ backgroundColor: item }}
                  onClick={() => handleStyleChange({ color: item })}
                />
              ))}
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-auto px-4 py-3">
            <textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              className="h-full min-h-[92px] w-full resize-none rounded-subtle border border-border-cream bg-transparent p-2 focus:outline-none"
              style={textStyle}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter" && e.metaKey) handleSave();
                if (e.key === "Escape") {
                  setEditContent(nodeData.content);
                  setIsEditing(false);
                }
              }}
            />
          </div>
        </div>
      </div>
    );
  }

  // Default view: whole container is the drag handle zone; edit button opts out via nodrag.
  return (
    <div
      className={`text-node-drag-handle relative bg-transparent ${isHovered ? "cursor-grab active:cursor-grabbing" : "cursor-default"}`}
      style={{ width: nodeWidth }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {(isHovered || selected) && (
        <div className="canvas-export-ignore pointer-events-none absolute inset-y-0 left-0 flex -translate-x-full items-start pr-2 pt-1">
          <button
            type="button"
            aria-label={t("workspace.textBlock.edit")}
            className="nodrag pointer-events-auto flex h-7 w-7 items-center justify-center rounded-comfortable border border-border-cream bg-ivory text-stone-gray shadow-whisper hover:bg-warm-sand hover:text-near-black"
            onClick={() => setIsEditing(true)}
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
      {textLayer}
    </div>
  );
}

export const TextNode = memo(TextNodeComponent);
