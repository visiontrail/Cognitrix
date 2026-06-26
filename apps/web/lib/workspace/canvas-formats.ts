import type { WorkspaceCanvasFormat, WorkspaceCanvasFormatId } from "@/types/workspace";

export type CanvasFormatPreset = {
  id: WorkspaceCanvasFormatId;
  labelKey: string;
  descriptionKey: string;
  width: number | null;
  height: number | null;
  /**
   * Whether this canvas maps to a physical paper size and is therefore suitable
   * for the browser print dialog (A4/A3/Letter). Slide- and screen-oriented
   * fixed canvases (16:9) and free canvases (infinite/web-design) stay false.
   */
  printable: boolean;
  /**
   * How a multi-page export of this format should be laid out. `"slide"` formats
   * (16:9) export as a landscape, full-bleed presentation deck (one slide per
   * PDF page); `"document"` formats (A4/A3/Letter) export as paper pages with an
   * orientation derived from their aspect ratio. Infinite/web-design canvases
   * never paginate, so the value is unused for them.
   */
  printStyle: "document" | "slide";
};

export const DEFAULT_CANVAS_FORMAT: WorkspaceCanvasFormat = { id: "infinite" };

/** Vertical gap (canvas px) rendered between stacked pages of a fixed canvas. */
export const CANVAS_PAGE_GAP = 48;

/** Upper bound on how many pages a single fixed canvas may hold. */
export const MAX_CANVAS_PAGES = 50;

export const CANVAS_FORMAT_PRESETS: CanvasFormatPreset[] = [
  {
    id: "infinite",
    labelKey: "workspace.canvasFormat.infinite",
    descriptionKey: "workspace.canvasFormat.infiniteDescription",
    width: null,
    height: null,
    printable: false,
    printStyle: "document",
  },
  {
    id: "web-design",
    labelKey: "workspace.canvasFormat.webDesign",
    descriptionKey: "workspace.canvasFormat.webDesignDescription",
    width: null,
    height: null,
    printable: false,
    printStyle: "document",
  },
  {
    id: "a4-portrait",
    labelKey: "workspace.canvasFormat.a4Portrait",
    descriptionKey: "workspace.canvasFormat.a4PortraitDescription",
    width: 794,
    height: 1123,
    printable: true,
    printStyle: "document",
  },
  {
    id: "a4-landscape",
    labelKey: "workspace.canvasFormat.a4Landscape",
    descriptionKey: "workspace.canvasFormat.a4LandscapeDescription",
    width: 1123,
    height: 794,
    printable: true,
    printStyle: "document",
  },
  {
    id: "a3-portrait",
    labelKey: "workspace.canvasFormat.a3Portrait",
    descriptionKey: "workspace.canvasFormat.a3PortraitDescription",
    width: 1123,
    height: 1587,
    printable: true,
    printStyle: "document",
  },
  {
    id: "letter-portrait",
    labelKey: "workspace.canvasFormat.letterPortrait",
    descriptionKey: "workspace.canvasFormat.letterPortraitDescription",
    width: 816,
    height: 1056,
    printable: true,
    printStyle: "document",
  },
  {
    id: "wide-16-9",
    labelKey: "workspace.canvasFormat.wide169",
    descriptionKey: "workspace.canvasFormat.wide169Description",
    width: 1280,
    height: 720,
    printable: false,
    printStyle: "slide",
  },
];

export function getCanvasFormatPreset(id: WorkspaceCanvasFormatId): CanvasFormatPreset {
  return (
    CANVAS_FORMAT_PRESETS.find((preset) => preset.id === id) ??
    CANVAS_FORMAT_PRESETS[0]
  );
}

export function normalizeCanvasFormat(value: unknown): WorkspaceCanvasFormat {
  if (!value || typeof value !== "object") {
    return DEFAULT_CANVAS_FORMAT;
  }

  const id = (value as { id?: unknown }).id;
  if (typeof id !== "string") {
    return DEFAULT_CANVAS_FORMAT;
  }

  const preset = CANVAS_FORMAT_PRESETS.find((item) => item.id === id);
  return preset ? { id: preset.id } : DEFAULT_CANVAS_FORMAT;
}

/** True when a format renders a bounded page (and can therefore paginate). */
export function isBoundedCanvasFormat(preset: CanvasFormatPreset): boolean {
  return preset.width != null && preset.height != null;
}

/**
 * Resolve how many pages a fixed canvas currently has. Unbounded formats
 * (infinite/web-design) are always a single conceptual page; bounded formats
 * read the persisted per-format count, clamped to `[1, MAX_CANVAS_PAGES]`.
 */
export function getCanvasPageCount(
  formatId: WorkspaceCanvasFormatId,
  pages: Partial<Record<WorkspaceCanvasFormatId, number>> | undefined
): number {
  const preset = getCanvasFormatPreset(formatId);
  if (!isBoundedCanvasFormat(preset)) return 1;
  const raw = pages?.[formatId];
  if (typeof raw !== "number" || !Number.isFinite(raw)) return 1;
  return Math.min(MAX_CANVAS_PAGES, Math.max(1, Math.trunc(raw)));
}

/** Distance (canvas px) from the top of one page to the top of the next. */
export function getCanvasPageStride(preset: CanvasFormatPreset): number {
  return (preset.height ?? 0) + CANVAS_PAGE_GAP;
}

export type CanvasPageRect = {
  index: number;
  x: number;
  y: number;
  width: number;
  height: number;
};

/**
 * Lay the requested number of pages out vertically in canvas coordinates, each
 * separated by `CANVAS_PAGE_GAP`. Returns an empty list for unbounded formats.
 */
export function getCanvasPageRects(
  preset: CanvasFormatPreset,
  pageCount: number
): CanvasPageRect[] {
  if (!isBoundedCanvasFormat(preset)) return [];
  const count = Math.max(1, Math.trunc(pageCount));
  const stride = getCanvasPageStride(preset);
  return Array.from({ length: count }, (_, index) => ({
    index,
    x: 0,
    y: index * stride,
    width: preset.width!,
    height: preset.height!,
  }));
}

type OccupancyNodeLike = {
  position?: { x?: number; y?: number } | null;
  width?: number | null;
  height?: number | null;
  hidden?: boolean | null;
  measured?: { width?: number; height?: number } | null;
  data?: { height?: number; type?: string } | null;
};

/**
 * Index of the last page touched by any visible node, based on each node's
 * bottom edge. Returns 0 when nothing is placed (page one always exists). Used
 * to keep page removal from orphaning content beyond the new last page.
 */
export function getMaxOccupiedCanvasPage(
  nodes: OccupancyNodeLike[],
  preset: CanvasFormatPreset
): number {
  if (!isBoundedCanvasFormat(preset)) return 0;
  const stride = getCanvasPageStride(preset);
  let maxPage = 0;
  for (const node of nodes) {
    if (node.hidden) continue;
    const top = Number(node.position?.y ?? 0);
    const height = Number(
      node.height ?? node.measured?.height ?? node.data?.height ?? 0
    );
    const safeHeight = Number.isFinite(height) && height > 0 ? height : 0;
    const bottom = top + safeHeight;
    // Use the lower of the two edges so a zero-height node still maps to its page.
    const page = Math.max(0, Math.floor(Math.max(top, bottom - 1) / stride));
    if (page > maxPage) maxPage = page;
  }
  return maxPage;
}
