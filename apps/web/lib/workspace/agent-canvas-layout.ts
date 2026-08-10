import { getCanvasFormatPreset } from "@/lib/workspace/canvas-formats";
import type {
  WebDesignTextStyle,
  WorkspaceCanvasFormatId,
  WorkspaceNode,
} from "@/types/workspace";

/**
 * Structure-only contract between agent-canvas ops and the layout engine
 * (design D2): the model chooses a size preset; the client maps it to a fixed
 * grid span and lets `findSlot` compute the position. Given the same op
 * sequence on an empty page, the resulting layout is identical everywhere.
 */

export type SizePreset = "kpi" | "half" | "wide" | "full";

export const SIZE_PRESET_SPANS: Record<SizePreset, { w: number; h: number }> = {
  kpi: { w: 3, h: 2 },
  half: { w: 6, h: 3 },
  wide: { w: 12, h: 3 },
  full: { w: 12, h: 4 },
};

export const TEXT_STYLE_SPANS: Record<WebDesignTextStyle, { w: number; h: number }> = {
  title: { w: 12, h: 1 },
  subtitle: { w: 12, h: 1 },
  body: { w: 12, h: 2 },
};

export function spanForSizePreset(preset: string | undefined): { w: number; h: number } {
  return SIZE_PRESET_SPANS[(preset ?? "") as SizePreset] ?? SIZE_PRESET_SPANS.half;
}

export function spanForTextStyle(style: string | undefined): { w: number; h: number } {
  return TEXT_STYLE_SPANS[(style ?? "") as WebDesignTextStyle] ?? TEXT_STYLE_SPANS.body;
}

/** Chart node whose `chartType` marks a retryable agent error placeholder. */
export const AGENT_ERROR_CHART_TYPE = "agent_error";

export function agentNodeIdForBlock(blockId: string): string {
  return `node-${blockId}`;
}

export function agentRunIdFromRootPageId(pageId: string): string {
  return pageId.startsWith("agent-") ? pageId.slice("agent-".length) : "";
}

/** Parse a deterministic block id back into the retry endpoint coordinates. */
export function parseAgentBlockId(blockId: string): { runId: string; seq: number } | null {
  if (!blockId.startsWith("agent-block-")) return null;
  const rest = blockId.slice("agent-block-".length);
  const lastDash = rest.lastIndexOf("-");
  if (lastDash <= 0) return null;
  const runId = rest.slice(0, lastDash);
  const seq = Number(rest.slice(lastDash + 1));
  return runId && Number.isFinite(seq) ? { runId, seq } : null;
}

export function isAgentNodeForRun(node: WorkspaceNode, runId: string): boolean {
  return Boolean(runId) && node.data.agentRunId === runId;
}

const FREE_LAYOUT_CONTENT_WIDTH = 1120;
const CANVAS_SIDE_MARGIN = 40;
// Keep semantic sizing aligned with the generic placement grid so two `half`
// cards (or three KPI cards) fit exactly inside the Agent content band.
const NODE_GAP = 28;

function availableCanvasWidth(canvasFormat: WorkspaceCanvasFormatId): number {
  const preset = getCanvasFormatPreset(canvasFormat);
  return preset.width == null
    ? FREE_LAYOUT_CONTENT_WIDTH
    : Math.max(320, preset.width - CANVAS_SIDE_MARGIN * 2);
}

/** Pixel footprint used by React Flow canvases for the model's semantic spans. */
export function agentChartNodeSize(
  canvasFormat: WorkspaceCanvasFormatId,
  preset: string | undefined
): { width: number; height: number } {
  const availableWidth = availableCanvasWidth(canvasFormat);
  const boundedWidth = getCanvasFormatPreset(canvasFormat).width;
  const columns = boundedWidth != null && boundedWidth < 1000 ? 2 : 3;
  const columnWidth = Math.floor((availableWidth - NODE_GAP * (columns - 1)) / columns);

  if (preset === "wide") return { width: availableWidth, height: 340 };
  if (preset === "full") return { width: availableWidth, height: 460 };
  if (preset === "kpi") return { width: columnWidth, height: 280 };
  return {
    width: Math.floor((availableWidth - NODE_GAP) / 2),
    height: 340,
  };
}

export function agentTextNodeSize(
  canvasFormat: WorkspaceCanvasFormatId,
  style: WebDesignTextStyle,
  pageMarker = false
): { width: number; height: number; fontSize: number } {
  const width = availableCanvasWidth(canvasFormat);
  if (pageMarker) return { width, height: 72, fontSize: 30 };
  if (style === "title") return { width, height: 58, fontSize: 24 };
  if (style === "subtitle") return { width, height: 50, fontSize: 20 };
  return { width, height: 132, fontSize: 16 };
}

/** Section heading depth: 1 = section, 2 = sub-section. */
export type SectionLevel = 1 | 2;

export function normalizeSectionLevel(value: unknown): SectionLevel {
  return Number(value) === 2 ? 2 : 1;
}

/** A sub-section renders one step down from a section heading. */
export function textStyleForSectionLevel(level: SectionLevel): WebDesignTextStyle {
  return level === 2 ? "subtitle" : "title";
}

/** Store-level ops: the wire payload already converted into client shapes. */
type AgentCanvasStoreOpBase = {
  runId: string;
  canvasFormat: WorkspaceCanvasFormatId;
};

export type AgentCanvasStoreOp = AgentCanvasStoreOpBase & (
  | {
      type: "create_page";
      pageId: string;
      blockId: string;
      title: string;
      /** Empty for the run's root page; set for every page opened by `add_page`. */
      parentPageId: string;
      node: WorkspaceNode;
    }
  | {
      type: "add_section";
      pageId: string;
      blockId: string;
      title: string;
      level: SectionLevel;
      node: WorkspaceNode;
    }
  | {
      type: "add_text_block";
      pageId: string;
      blockId: string;
      style: WebDesignTextStyle;
      content: string;
      node: WorkspaceNode;
    }
  | {
      type: "place_chart";
      pageId: string;
      blockId: string;
      chartId: string;
      node: WorkspaceNode;
      span: { w: number; h: number };
    }
  | {
      type: "error_placeholder";
      pageId: string;
      blockId: string;
      node: WorkspaceNode;
      span: { w: number; h: number };
    }
);
