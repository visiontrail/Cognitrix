import { toPng } from "html-to-image";

const PX_TO_MM = 25.4 / 96;

type CaptureOptions = {
  backgroundColor?: string;
  width?: number;
  height?: number;
  style?: Partial<CSSStyleDeclaration>;
};

function exportFilter(domNode: HTMLElement): boolean {
  return !domNode.closest?.("[data-public-canvas-export-ignore]");
}

function safeDimension(value: number, fallback: number): number {
  if (!Number.isFinite(value) || value <= 0) return fallback;
  return Math.ceil(value);
}

function getElementSize(element: HTMLElement): { width: number; height: number } {
  const rect = element.getBoundingClientRect();
  return {
    width: safeDimension(Math.max(element.scrollWidth, element.offsetWidth, rect.width), 1),
    height: safeDimension(Math.max(element.scrollHeight, element.offsetHeight, rect.height), 1),
  };
}

function downloadFile(dataUrl: string, filename: string) {
  const link = document.createElement("a");
  link.href = dataUrl;
  link.download = filename;
  link.click();
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function captureElement(element: HTMLElement, options: CaptureOptions = {}): Promise<string> {
  const naturalSize = getElementSize(element);
  const width = safeDimension(options.width ?? naturalSize.width, naturalSize.width);
  const height = safeDimension(options.height ?? naturalSize.height, naturalSize.height);

  return toPng(element, {
    backgroundColor: options.backgroundColor ?? "#f7f4eb",
    width,
    height,
    filter: exportFilter,
    pixelRatio: 2,
    style: {
      width: `${width}px`,
      height: `${height}px`,
      transform: "none",
      transformOrigin: "top left",
      ...options.style,
    },
  });
}

export async function exportPublicCanvasToPng(
  element: HTMLElement,
  filenameBase: string,
  options?: CaptureOptions
): Promise<void> {
  const dataUrl = await captureElement(element, options);
  downloadFile(dataUrl, `${filenameBase}.png`);
}

export async function exportPublicCanvasToPdf(
  element: HTMLElement,
  filenameBase: string,
  options?: CaptureOptions
): Promise<void> {
  const naturalSize = getElementSize(element);
  const width = safeDimension(options?.width ?? naturalSize.width, naturalSize.width);
  const height = safeDimension(options?.height ?? naturalSize.height, naturalSize.height);
  const pngDataUrl = await captureElement(element, { ...options, width, height });
  const widthMm = width * PX_TO_MM;
  const heightMm = height * PX_TO_MM;
  const { jsPDF } = await import("jspdf");
  const doc = new jsPDF({
    orientation: width >= height ? "landscape" : "portrait",
    unit: "mm",
    format: [widthMm, heightMm],
  });

  doc.addImage(pngDataUrl, "PNG", 0, 0, widthMm, heightMm);
  doc.save(`${filenameBase}.pdf`);
}

export async function printPublicCanvas(
  element: HTMLElement,
  documentTitle: string,
  options?: CaptureOptions
): Promise<void> {
  const naturalSize = getElementSize(element);
  const width = safeDimension(options?.width ?? naturalSize.width, naturalSize.width);
  const height = safeDimension(options?.height ?? naturalSize.height, naturalSize.height);
  const pngDataUrl = await captureElement(element, { ...options, width, height });
  const widthMm = width * PX_TO_MM;
  const heightMm = height * PX_TO_MM;

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
    const removeIframe = () => window.setTimeout(() => iframe.remove(), 1000);

    doc.open();
    doc.write(
      `<!DOCTYPE html><html><head><meta charset="utf-8" />` +
        `<title>${escapeHtml(documentTitle)}</title><style>` +
        `@page { size: ${widthMm}mm ${heightMm}mm; margin: 0; }` +
        `html, body { margin: 0; padding: 0; background: #fff; }` +
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
    fallbackTimer = window.setTimeout(triggerPrint, 2000);
    img.src = pngDataUrl;
  });
}
