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

/**
 * Capture a fixed-size canvas preset to a PNG data URL at its exact pixel
 * dimensions. Shared by the PNG, PDF, and print paths so they stay pixel-for-
 * pixel identical.
 */
async function captureFixedCanvas(preset: CanvasFormatPreset): Promise<string> {
  if (!preset.width || !preset.height) throw new Error("Preset has no fixed dimensions");

  const viewportEl = getViewportElement();
  if (!viewportEl) throw new Error("ReactFlow viewport element not found");

  const bounds = { x: 0, y: 0, width: preset.width, height: preset.height };
  const transform = getViewportForBounds(bounds, preset.width, preset.height, 0.1, 4, 0);

  return captureViewport(viewportEl, preset.width, preset.height, transform);
}

export async function exportFixedCanvasToPng(
  preset: CanvasFormatPreset,
  workspaceTitle: string
): Promise<void> {
  const dataUrl = await captureFixedCanvas(preset);
  downloadFile(dataUrl, `${workspaceTitle}.png`);
}

// mm per pixel at 96dpi (1 inch = 25.4mm, 1 inch = 96px)
const PX_TO_MM = 25.4 / 96;

export async function exportFixedCanvasToPdf(
  preset: CanvasFormatPreset,
  workspaceTitle: string
): Promise<void> {
  const pngDataUrl = await captureFixedCanvas(preset);

  const widthMm = preset.width! * PX_TO_MM;
  const heightMm = preset.height! * PX_TO_MM;

  const { jsPDF } = await import("jspdf");
  const orientation = preset.width! >= preset.height! ? "landscape" : "portrait";
  const doc = new jsPDF({
    orientation,
    unit: "mm",
    format: [widthMm, heightMm],
  });

  doc.addImage(pngDataUrl, "PNG", 0, 0, widthMm, heightMm);
  doc.save(`${workspaceTitle}.pdf`);
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * Print a fixed-size canvas via the browser's native print dialog. The captured
 * PNG is dropped into a hidden, isolated iframe whose `@page` size matches the
 * paper format (in mm), so the printer reproduces the canvas at true scale and
 * the surrounding app UI is never part of the printout. From the dialog the
 * user can pick a physical printer or "Save as PDF".
 */
export async function printFixedCanvas(
  preset: CanvasFormatPreset,
  workspaceTitle: string
): Promise<void> {
  const pngDataUrl = await captureFixedCanvas(preset);

  const widthMm = preset.width! * PX_TO_MM;
  const heightMm = preset.height! * PX_TO_MM;

  await new Promise<void>((resolve, reject) => {
    const iframe = document.createElement("iframe");
    iframe.setAttribute("aria-hidden", "true");
    iframe.style.position = "fixed";
    iframe.style.right = "0";
    iframe.style.bottom = "0";
    iframe.style.width = "0";
    iframe.style.height = "0";
    iframe.style.border = "0";
    iframe.style.visibility = "hidden";
    document.body.appendChild(iframe);

    const doc = iframe.contentWindow?.document;
    const win = iframe.contentWindow;
    if (!doc || !win) {
      iframe.remove();
      reject(new Error("Print iframe document unavailable"));
      return;
    }

    let settled = false;
    let fallbackTimer = 0;
    const removeIframe = () => {
      // Defer removal so the browser keeps the document alive for the dialog.
      window.setTimeout(() => iframe.remove(), 1000);
    };

    doc.open();
    doc.write(
      `<!DOCTYPE html><html><head><meta charset="utf-8" />` +
        `<title>${escapeHtml(workspaceTitle)}</title><style>` +
        `@page { size: ${widthMm}mm ${heightMm}mm; margin: 0; }` +
        `html, body { margin: 0; padding: 0; }` +
        `img { display: block; width: ${widthMm}mm; height: ${heightMm}mm; }` +
        `</style></head><body><img id="print-image" alt="" /></body></html>`
    );
    doc.close();

    const triggerPrint = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(fallbackTimer);
      try {
        win.focus();
        win.print();
        resolve();
      } catch (err) {
        reject(err instanceof Error ? err : new Error("Print failed"));
      } finally {
        removeIframe();
      }
    };

    const img = doc.getElementById("print-image") as HTMLImageElement | null;
    if (!img) {
      iframe.remove();
      reject(new Error("Print image element unavailable"));
      return;
    }

    img.onload = () => window.setTimeout(triggerPrint, 50);
    img.onerror = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(fallbackTimer);
      iframe.remove();
      reject(new Error("Print image failed to load"));
    };
    // Data URLs load synchronously in practice, but guard against a missed
    // onload so the promise can never hang the export button.
    fallbackTimer = window.setTimeout(triggerPrint, 2000);
    img.src = pngDataUrl;
  });
}
