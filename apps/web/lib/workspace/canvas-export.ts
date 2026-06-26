import { toPng } from "html-to-image";
import { getNodesBounds, getViewportForBounds } from "@xyflow/react";
import type { Node } from "@xyflow/react";
import type { CanvasFormatPreset } from "./canvas-formats";
import { getCanvasPageStride } from "./canvas-formats";

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
 * Capture an arbitrary canvas rectangle (canvas coordinates) to a PNG data URL,
 * rendered at the given output pixel size. Shared by every fixed-canvas export
 * path so PNG, PDF, and print stay pixel-for-pixel identical.
 */
async function captureFixedCanvasRect(
  bounds: { x: number; y: number; width: number; height: number },
  outputWidth: number,
  outputHeight: number
): Promise<string> {
  const viewportEl = getViewportElement();
  if (!viewportEl) throw new Error("ReactFlow viewport element not found");

  const transform = getViewportForBounds(bounds, outputWidth, outputHeight, 0.1, 4, 0);
  return captureViewport(viewportEl, outputWidth, outputHeight, transform);
}

/** Capture a single page (0-based) of a stacked fixed canvas at native size. */
function captureFixedCanvasPage(preset: CanvasFormatPreset, pageIndex: number): Promise<string> {
  if (!preset.width || !preset.height) throw new Error("Preset has no fixed dimensions");
  const pageTop = pageIndex * getCanvasPageStride(preset);
  const bounds = { x: 0, y: pageTop, width: preset.width, height: preset.height };
  return captureFixedCanvasRect(bounds, preset.width, preset.height);
}

function clampPageCount(pageCount: number): number {
  return Math.max(1, Math.trunc(Number.isFinite(pageCount) ? pageCount : 1));
}

export async function exportFixedCanvasToPng(
  preset: CanvasFormatPreset,
  workspaceTitle: string,
  pageCount = 1
): Promise<void> {
  if (!preset.width || !preset.height) throw new Error("Preset has no fixed dimensions");
  const pages = clampPageCount(pageCount);

  let dataUrl: string;
  if (pages === 1) {
    dataUrl = await captureFixedCanvasPage(preset, 0);
  } else {
    // Stack every page (and the gaps between them) into a single tall image so
    // the exported PNG mirrors the on-screen multi-page layout.
    const stride = getCanvasPageStride(preset);
    const totalHeight = pages * preset.height + (pages - 1) * (stride - preset.height);
    dataUrl = await captureFixedCanvasRect(
      { x: 0, y: 0, width: preset.width, height: totalHeight },
      preset.width,
      totalHeight
    );
  }
  downloadFile(dataUrl, `${workspaceTitle}.png`);
}

// mm per pixel at 96dpi (1 inch = 25.4mm, 1 inch = 96px)
const PX_TO_MM = 25.4 / 96;

/**
 * Export a fixed canvas to a multi-page PDF whose page geometry is chosen by the
 * preset's `printStyle`:
 *  - `"slide"` (16:9) → a landscape, full-bleed presentation deck, one slide per
 *    page. The slide preset maps exactly onto PowerPoint's 16:9 page size
 *    (1280×720 px → 338.67 × 190.5 mm), so the result opens as a true slide deck.
 *  - `"document"` (A4/A3/Letter) → paper pages with an orientation derived from
 *    the format's aspect ratio.
 * Either way, each on-screen page becomes one PDF page.
 */
export async function exportFixedCanvasToPdf(
  preset: CanvasFormatPreset,
  workspaceTitle: string,
  pageCount = 1
): Promise<void> {
  if (!preset.width || !preset.height) throw new Error("Preset has no fixed dimensions");
  const pages = clampPageCount(pageCount);

  const widthMm = preset.width * PX_TO_MM;
  const heightMm = preset.height * PX_TO_MM;
  const isSlide = preset.printStyle === "slide";
  const orientation: "landscape" | "portrait" = isSlide
    ? "landscape"
    : preset.width >= preset.height
      ? "landscape"
      : "portrait";

  const { jsPDF } = await import("jspdf");
  const doc = new jsPDF({
    orientation,
    unit: "mm",
    format: [widthMm, heightMm],
    compress: true,
  });

  for (let page = 0; page < pages; page += 1) {
    if (page > 0) {
      doc.addPage([widthMm, heightMm], orientation);
    }
    const pngDataUrl = await captureFixedCanvasPage(preset, page);
    doc.addImage(pngDataUrl, "PNG", 0, 0, widthMm, heightMm);
  }

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
 * Print a fixed-size canvas via the browser's native print dialog. Every page is
 * captured and dropped into a hidden, isolated iframe whose `@page` size matches
 * the paper format (in mm), with one image per sheet separated by hard page
 * breaks — so a multi-page canvas prints as multiple sheets at true scale and the
 * surrounding app UI is never part of the printout. From the dialog the user can
 * pick a physical printer or "Save as PDF".
 */
export async function printFixedCanvas(
  preset: CanvasFormatPreset,
  workspaceTitle: string,
  pageCount = 1
): Promise<void> {
  if (!preset.width || !preset.height) throw new Error("Preset has no fixed dimensions");
  const pages = clampPageCount(pageCount);

  const widthMm = preset.width * PX_TO_MM;
  const heightMm = preset.height * PX_TO_MM;

  const pageImages: string[] = [];
  for (let page = 0; page < pages; page += 1) {
    pageImages.push(await captureFixedCanvasPage(preset, page));
  }

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

    const body = pageImages
      .map(
        (_, index) =>
          `<div class="print-page"><img class="print-image" data-index="${index}" alt="" /></div>`
      )
      .join("");

    doc.open();
    doc.write(
      `<!DOCTYPE html><html><head><meta charset="utf-8" />` +
        `<title>${escapeHtml(workspaceTitle)}</title><style>` +
        `@page { size: ${widthMm}mm ${heightMm}mm; margin: 0; }` +
        `html, body { margin: 0; padding: 0; }` +
        `.print-page { break-after: page; page-break-after: always; }` +
        `.print-page:last-child { break-after: auto; page-break-after: auto; }` +
        `.print-image { display: block; width: ${widthMm}mm; height: ${heightMm}mm; }` +
        `</style></head><body>${body}</body></html>`
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

    const imgs = Array.from(
      doc.querySelectorAll<HTMLImageElement>("img.print-image")
    );
    if (imgs.length !== pageImages.length) {
      iframe.remove();
      reject(new Error("Print image element unavailable"));
      return;
    }

    let loaded = 0;
    const onImageSettled = () => {
      loaded += 1;
      if (loaded >= imgs.length) {
        window.setTimeout(triggerPrint, 50);
      }
    };

    imgs.forEach((img) => {
      img.onload = onImageSettled;
      img.onerror = onImageSettled;
      const index = Number(img.dataset.index ?? 0);
      img.src = pageImages[index] ?? "";
    });

    // Data URLs load synchronously in practice, but guard against a missed
    // onload so the promise can never hang the export button.
    fallbackTimer = window.setTimeout(triggerPrint, 2000);
  });
}
