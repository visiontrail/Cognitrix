import type { CSSProperties } from "react";
import type { WorkspaceCanvasFormatId } from "@/types/workspace";

/**
 * Canvas background catalog.
 *
 * Every infinite / paper / slide canvas can swap its backdrop. The presets here
 * follow a few hard rules drawn from how Figma, tldraw, Keynote and editorial
 * page layout actually treat surfaces:
 *
 *  1. A backdrop is scenery, never subject. Pattern contrast stays low enough
 *     that a chart or text block always wins the foreground.
 *  2. Alignment surfaces (dot / line grids) belong on the infinite canvas where
 *     people place things freely; paper keeps a faint print grid; slides lean on
 *     flat tone or a single calm gradient so projected content reads.
 *  3. Light and dark are both first-class — a few deliberately dark surfaces let
 *     a slide deck or a hero board feel intentional rather than washed out.
 *
 * Rendering model: each preset is a base color plus zero or more image
 * "layers" (patterns or gradients), composed into a single CSS declaration by
 * {@link composeCanvasBackgroundStyle}. The same declaration paints the
 * infinite/slide container, each paper page, and the picker swatch, so what you
 * choose is exactly what you get.
 */

export type CanvasBackgroundGroup = "surface" | "grid" | "editorial" | "atmosphere";

type BackgroundLayer = {
  /** A CSS <image> — gradient or repeating pattern. */
  image: string;
  /** Optional background-size for this layer (defaults to `auto`). */
  size?: string;
  /** Optional background-repeat for this layer (defaults to `repeat`). */
  repeat?: string;
};

export type CanvasBackgroundPreset = {
  id: string;
  labelKey: string;
  group: CanvasBackgroundGroup;
  /** Dark-toned surface — flips page chrome (page numbers, frame) to light ink. */
  dark?: boolean;
  /** Solid fill drawn beneath every layer. */
  baseColor: string;
  /** Image layers painted front-to-back over {@link baseColor}. */
  layers?: BackgroundLayer[];
};

// Tuned once here so grid/line presets stay visually consistent.
const TERRACOTTA_LINE = "rgba(201, 100, 66, 0.09)";
const WARM_DOT = "#d3cdbf";

export const CANVAS_BACKGROUND_PRESETS: CanvasBackgroundPreset[] = [
  // ── Surfaces — flat, get-out-of-the-way tones ───────────────────────────────
  {
    id: "ivory",
    labelKey: "workspace.canvasBackground.ivory",
    group: "surface",
    baseColor: "#fffef9",
  },
  {
    id: "pure-white",
    labelKey: "workspace.canvasBackground.pureWhite",
    group: "surface",
    baseColor: "#ffffff",
  },
  {
    id: "parchment",
    labelKey: "workspace.canvasBackground.parchment",
    group: "surface",
    baseColor: "#f4f0e6",
  },
  {
    id: "sand",
    labelKey: "workspace.canvasBackground.sand",
    group: "surface",
    baseColor: "#ece3d2",
  },
  {
    id: "graphite",
    labelKey: "workspace.canvasBackground.graphite",
    group: "surface",
    dark: true,
    baseColor: "#1f1e1c",
  },
  {
    id: "midnight",
    labelKey: "workspace.canvasBackground.midnight",
    group: "surface",
    dark: true,
    baseColor: "#13151d",
  },

  // ── Grids — alignment aids ──────────────────────────────────────────────────
  {
    id: "dots",
    labelKey: "workspace.canvasBackground.dots",
    group: "grid",
    baseColor: "#fdfcf7",
    layers: [
      {
        image: `radial-gradient(circle, ${WARM_DOT} 1.2px, transparent 1.6px)`,
        size: "20px 20px",
      },
    ],
  },
  {
    id: "paper-grid",
    labelKey: "workspace.canvasBackground.paperGrid",
    group: "grid",
    baseColor: "#fffef9",
    layers: [
      { image: `linear-gradient(90deg, ${TERRACOTTA_LINE} 1px, transparent 1px)`, size: "40px 40px" },
      { image: `linear-gradient(${TERRACOTTA_LINE} 1px, transparent 1px)`, size: "40px 40px" },
    ],
  },
  {
    id: "graph-paper",
    labelKey: "workspace.canvasBackground.graphPaper",
    group: "grid",
    baseColor: "#f3f7f2",
    layers: [
      { image: "linear-gradient(rgba(70, 132, 92, 0.26) 1px, transparent 1px)", size: "96px 96px" },
      { image: "linear-gradient(90deg, rgba(70, 132, 92, 0.26) 1px, transparent 1px)", size: "96px 96px" },
      { image: "linear-gradient(rgba(70, 132, 92, 0.11) 1px, transparent 1px)", size: "24px 24px" },
      { image: "linear-gradient(90deg, rgba(70, 132, 92, 0.11) 1px, transparent 1px)", size: "24px 24px" },
    ],
  },
  {
    id: "blueprint",
    labelKey: "workspace.canvasBackground.blueprint",
    group: "grid",
    dark: true,
    baseColor: "#0f2a43",
    layers: [
      { image: "linear-gradient(rgba(132, 198, 255, 0.32) 1px, transparent 1px)", size: "96px 96px" },
      { image: "linear-gradient(90deg, rgba(132, 198, 255, 0.32) 1px, transparent 1px)", size: "96px 96px" },
      { image: "linear-gradient(rgba(132, 198, 255, 0.13) 1px, transparent 1px)", size: "24px 24px" },
      { image: "linear-gradient(90deg, rgba(132, 198, 255, 0.13) 1px, transparent 1px)", size: "24px 24px" },
    ],
  },

  // ── Editorial — ruled writing surfaces ──────────────────────────────────────
  {
    id: "ruled",
    labelKey: "workspace.canvasBackground.ruled",
    group: "editorial",
    baseColor: "#fffdf6",
    layers: [
      {
        image:
          "linear-gradient(90deg, transparent 56px, rgba(201, 100, 66, 0.28) 56px, rgba(201, 100, 66, 0.28) 57px, transparent 57px)",
        size: "100% 100%",
        repeat: "no-repeat",
      },
      { image: "linear-gradient(rgba(63, 84, 148, 0.12) 1px, transparent 1px)", size: "100% 32px" },
    ],
  },
  {
    id: "legal-pad",
    labelKey: "workspace.canvasBackground.legalPad",
    group: "editorial",
    baseColor: "#fbf6cf",
    layers: [
      {
        image:
          "linear-gradient(90deg, transparent 52px, rgba(193, 71, 56, 0.35) 52px, rgba(193, 71, 56, 0.35) 53px, transparent 53px)",
        size: "100% 100%",
        repeat: "no-repeat",
      },
      { image: "linear-gradient(rgba(63, 84, 148, 0.16) 1px, transparent 1px)", size: "100% 30px" },
    ],
  },

  // ── Atmospheres — gradient & texture mood ───────────────────────────────────
  {
    id: "dawn",
    labelKey: "workspace.canvasBackground.dawn",
    group: "atmosphere",
    baseColor: "#fff6ea",
    layers: [
      {
        image:
          "radial-gradient(120% 120% at 18% 0%, #ffe6d2 0%, #fff5e9 46%, #fbf1e2 100%)",
        size: "100% 100%",
        repeat: "no-repeat",
      },
    ],
  },
  {
    id: "terracotta-wash",
    labelKey: "workspace.canvasBackground.terracottaWash",
    group: "atmosphere",
    baseColor: "#fffdf7",
    layers: [
      {
        image:
          "radial-gradient(90% 80% at 82% 8%, rgba(201, 100, 66, 0.16) 0%, rgba(201, 100, 66, 0) 55%)",
        size: "100% 100%",
        repeat: "no-repeat",
      },
    ],
  },
  {
    id: "dusk",
    labelKey: "workspace.canvasBackground.dusk",
    group: "atmosphere",
    dark: true,
    baseColor: "#1d1830",
    layers: [
      {
        image: "linear-gradient(155deg, #191c2e 0%, #2a1d36 58%, #3a2238 100%)",
        size: "100% 100%",
        repeat: "no-repeat",
      },
    ],
  },
  {
    id: "grain",
    labelKey: "workspace.canvasBackground.grain",
    group: "atmosphere",
    baseColor: "#faf4e9",
    layers: [
      { image: "radial-gradient(rgba(120, 108, 86, 0.10) 0.5px, transparent 0.5px)", size: "4px 4px" },
      { image: "radial-gradient(rgba(120, 108, 86, 0.07) 0.5px, transparent 0.5px)", size: "7px 7px" },
    ],
  },
];

const PRESET_BY_ID = new Map(CANVAS_BACKGROUND_PRESETS.map((preset) => [preset.id, preset]));
const DEFAULT_DARK_TEXT_COLOR = "#3f3d39";
const INVERTED_DARK_SURFACE_TEXT_COLOR = "#fffef9";

/** Per-format default backdrop — preserves each canvas's established look. */
const DEFAULT_BACKGROUND_BY_FORMAT: Partial<Record<WorkspaceCanvasFormatId, string>> = {
  infinite: "dots",
  "a4-portrait": "paper-grid",
  "a4-landscape": "paper-grid",
  "a3-portrait": "paper-grid",
  "letter-portrait": "paper-grid",
  "wide-16-9": "ivory",
};

export function getDefaultCanvasBackgroundId(formatId: WorkspaceCanvasFormatId): string {
  return DEFAULT_BACKGROUND_BY_FORMAT[formatId] ?? "ivory";
}

export function getCanvasBackgroundPreset(id: string | undefined): CanvasBackgroundPreset {
  return (id && PRESET_BY_ID.get(id)) || CANVAS_BACKGROUND_PRESETS[0];
}

/**
 * Resolve the active backdrop for a format: the explicit per-format choice if
 * present, otherwise that format's sensible default.
 */
export function resolveCanvasBackgroundPreset(
  formatId: WorkspaceCanvasFormatId,
  backgrounds: Partial<Record<WorkspaceCanvasFormatId, string>> | undefined
): CanvasBackgroundPreset {
  const chosen = backgrounds?.[formatId];
  if (chosen && PRESET_BY_ID.has(chosen)) return getCanvasBackgroundPreset(chosen);
  return getCanvasBackgroundPreset(getDefaultCanvasBackgroundId(formatId));
}

/** Compose a preset into a paint-anywhere CSS declaration. */
export function composeCanvasBackgroundStyle(preset: CanvasBackgroundPreset): CSSProperties {
  if (!preset.layers || preset.layers.length === 0) {
    return { backgroundColor: preset.baseColor };
  }
  return {
    backgroundColor: preset.baseColor,
    backgroundImage: preset.layers.map((layer) => layer.image).join(", "),
    backgroundSize: preset.layers.map((layer) => layer.size ?? "auto").join(", "),
    backgroundRepeat: preset.layers.map((layer) => layer.repeat ?? "repeat").join(", "),
    backgroundPosition: "0 0",
  };
}

/**
 * Keep free-floating canvas text readable when a dark backdrop is selected.
 * Dark user colors (including the default near-black) are treated as foreground
 * ink and flipped to light ink; already-light custom colors are preserved.
 */
export function resolveCanvasTextColor(
  textColor: string | undefined,
  backgroundPreset: CanvasBackgroundPreset
): string {
  const color = textColor || DEFAULT_DARK_TEXT_COLOR;
  if (!backgroundPreset.dark) return color;
  return isDarkCssColor(color) ? INVERTED_DARK_SURFACE_TEXT_COLOR : color;
}

function isDarkCssColor(color: string): boolean {
  const rgb = parseCssColor(color);
  if (!rgb) return false;
  const [red, green, blue] = rgb.map((channel) => {
    const value = channel / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  const relativeLuminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue;
  return relativeLuminance < 0.45;
}

function parseCssColor(color: string): [number, number, number] | null {
  const normalized = color.trim().toLowerCase();
  if (normalized === "black") return [0, 0, 0];
  if (normalized === "white") return [255, 255, 255];

  const hex = normalized.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (hex) {
    const value = hex[1];
    if (value.length === 3) {
      return value.split("").map((digit) => parseInt(`${digit}${digit}`, 16)) as [number, number, number];
    }
    return [
      parseInt(value.slice(0, 2), 16),
      parseInt(value.slice(2, 4), 16),
      parseInt(value.slice(4, 6), 16),
    ];
  }

  const rgb = normalized.match(/^rgba?\(\s*([.\d]+)\s*,\s*([.\d]+)\s*,\s*([.\d]+)(?:\s*,\s*[\d.]+)?\s*\)$/);
  if (!rgb) return null;
  return [
    clampRgbChannel(Number(rgb[1])),
    clampRgbChannel(Number(rgb[2])),
    clampRgbChannel(Number(rgb[3])),
  ];
}

function clampRgbChannel(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(255, value));
}

/** Order groups are surfaced in the picker. */
export const CANVAS_BACKGROUND_GROUP_ORDER: CanvasBackgroundGroup[] = [
  "surface",
  "grid",
  "editorial",
  "atmosphere",
];
