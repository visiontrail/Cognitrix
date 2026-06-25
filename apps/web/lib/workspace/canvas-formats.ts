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
};

export const DEFAULT_CANVAS_FORMAT: WorkspaceCanvasFormat = { id: "infinite" };

export const CANVAS_FORMAT_PRESETS: CanvasFormatPreset[] = [
  {
    id: "infinite",
    labelKey: "workspace.canvasFormat.infinite",
    descriptionKey: "workspace.canvasFormat.infiniteDescription",
    width: null,
    height: null,
    printable: false,
  },
  {
    id: "web-design",
    labelKey: "workspace.canvasFormat.webDesign",
    descriptionKey: "workspace.canvasFormat.webDesignDescription",
    width: null,
    height: null,
    printable: false,
  },
  {
    id: "a4-portrait",
    labelKey: "workspace.canvasFormat.a4Portrait",
    descriptionKey: "workspace.canvasFormat.a4PortraitDescription",
    width: 794,
    height: 1123,
    printable: true,
  },
  {
    id: "a4-landscape",
    labelKey: "workspace.canvasFormat.a4Landscape",
    descriptionKey: "workspace.canvasFormat.a4LandscapeDescription",
    width: 1123,
    height: 794,
    printable: true,
  },
  {
    id: "a3-portrait",
    labelKey: "workspace.canvasFormat.a3Portrait",
    descriptionKey: "workspace.canvasFormat.a3PortraitDescription",
    width: 1123,
    height: 1587,
    printable: true,
  },
  {
    id: "letter-portrait",
    labelKey: "workspace.canvasFormat.letterPortrait",
    descriptionKey: "workspace.canvasFormat.letterPortraitDescription",
    width: 816,
    height: 1056,
    printable: true,
  },
  {
    id: "wide-16-9",
    labelKey: "workspace.canvasFormat.wide169",
    descriptionKey: "workspace.canvasFormat.wide169Description",
    width: 1280,
    height: 720,
    printable: false,
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
