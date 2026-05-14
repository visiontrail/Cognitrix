import { toBlob } from "html-to-image";

const CHART_PNG_BACKGROUND = "#f5f0e8";
const CHART_PNG_PIXEL_RATIO = 2;

export function canCopyPngToClipboard(): boolean {
  return Boolean(navigator.clipboard) && typeof ClipboardItem !== "undefined";
}

export async function copyElementAsPngToClipboard(element: HTMLElement): Promise<void> {
  const blob = await toBlob(element, {
    backgroundColor: CHART_PNG_BACKGROUND,
    pixelRatio: CHART_PNG_PIXEL_RATIO,
  });

  if (!blob) {
    throw new Error("png_export_failed");
  }

  await navigator.clipboard.write([
    new ClipboardItem({
      "image/png": blob,
    }),
  ]);
}
