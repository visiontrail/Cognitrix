import { toPng } from "html-to-image";
import { getNodesBounds, getViewportForBounds } from "@xyflow/react";
import type { Node } from "@xyflow/react";
import type { CanvasFormatPreset } from "./canvas-formats";

const INFINITE_EXPORT_PADDING = 80;
const INFINITE_MIN_SIZE = 1280;

function getViewportElement(): HTMLElement | null {
  return document.querySelector(".react-flow__viewport");
}

function exportFilter(domNode: HTMLElement): boolean {
  if (domNode.classList) {
    if (domNode.classList.contains("canvas-export-ignore")) return false;
    if (domNode.classList.contains("react-flow__resize-control")) return false;
    if (domNode.classList.contains("react-flow__node-resizer")) return false;
  }
  return true;
}

async function captureViewport(
  viewportEl: HTMLElement,
  outputWidth: number,
  outputHeight: number,
  transform: { x: number; y: number; zoom: number }
): Promise<string> {
  return toPng(viewportEl, {
    backgroundColor: "#f5f4ed",
    width: outputWidth,
    height: outputHeight,
    filter: exportFilter,
    style: {
      width: `${outputWidth}px`,
      height: `${outputHeight}px`,
      transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.zoom})`,
    },
  });
}

function downloadFile(dataUrl: string, filename: string) {
  const link = document.createElement("a");
  link.href = dataUrl;
  link.download = filename;
  link.click();
}

export async function exportInfiniteCanvasToPng(
  nodes: Node[],
  workspaceTitle: string
): Promise<void> {
  const viewportEl = getViewportElement();
  if (!viewportEl) throw new Error("ReactFlow viewport element not found");

  if (nodes.length === 0) {
    throw new Error("NO_CONTENT");
  }

  const bounds = getNodesBounds(nodes);
  const paddedBounds = {
    x: bounds.x - INFINITE_EXPORT_PADDING,
    y: bounds.y - INFINITE_EXPORT_PADDING,
    width: bounds.width + INFINITE_EXPORT_PADDING * 2,
    height: bounds.height + INFINITE_EXPORT_PADDING * 2,
  };

  const outputWidth = Math.max(INFINITE_MIN_SIZE, paddedBounds.width);
  const outputHeight = Math.max(
    Math.round((INFINITE_MIN_SIZE * paddedBounds.height) / paddedBounds.width),
    paddedBounds.height
  );

  const transform = getViewportForBounds(paddedBounds, outputWidth, outputHeight, 0.1, 4, 0);

  const dataUrl = await captureViewport(viewportEl, outputWidth, outputHeight, transform);
  downloadFile(dataUrl, `${workspaceTitle}.png`);
}

export async function exportFixedCanvasToPng(
  preset: CanvasFormatPreset,
  workspaceTitle: string
): Promise<void> {
  if (!preset.width || !preset.height) throw new Error("Preset has no fixed dimensions");

  const viewportEl = getViewportElement();
  if (!viewportEl) throw new Error("ReactFlow viewport element not found");

  const bounds = { x: 0, y: 0, width: preset.width, height: preset.height };
  const transform = getViewportForBounds(bounds, preset.width, preset.height, 0.1, 4, 0);

  const dataUrl = await captureViewport(viewportEl, preset.width, preset.height, transform);
  downloadFile(dataUrl, `${workspaceTitle}.png`);
}

// mm per pixel at 96dpi (1 inch = 25.4mm, 1 inch = 96px)
const PX_TO_MM = 25.4 / 96;

export async function exportFixedCanvasToPdf(
  preset: CanvasFormatPreset,
  workspaceTitle: string
): Promise<void> {
  if (!preset.width || !preset.height) throw new Error("Preset has no fixed dimensions");

  const viewportEl = getViewportElement();
  if (!viewportEl) throw new Error("ReactFlow viewport element not found");

  const bounds = { x: 0, y: 0, width: preset.width, height: preset.height };
  const transform = getViewportForBounds(bounds, preset.width, preset.height, 0.1, 4, 0);

  const pngDataUrl = await captureViewport(viewportEl, preset.width, preset.height, transform);

  const widthMm = preset.width * PX_TO_MM;
  const heightMm = preset.height * PX_TO_MM;

  const { jsPDF } = await import("jspdf");
  const orientation = preset.width >= preset.height ? "landscape" : "portrait";
  const doc = new jsPDF({
    orientation,
    unit: "mm",
    format: [widthMm, heightMm],
  });

  doc.addImage(pngDataUrl, "PNG", 0, 0, widthMm, heightMm);
  doc.save(`${workspaceTitle}.pdf`);
}
