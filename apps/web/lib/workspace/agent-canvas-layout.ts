import type { WebDesignTextStyle, WorkspaceNode } from "@/types/workspace";

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
export type AgentCanvasStoreOp =
  | {
      type: "create_page";
      pageId: string;
      title: string;
      /** Empty for the run's root page; set for every page opened by `add_page`. */
      parentPageId: string;
    }
  | {
      type: "add_section";
      pageId: string;
      blockId: string;
      title: string;
      level: SectionLevel;
    }
  | {
      type: "add_text_block";
      pageId: string;
      blockId: string;
      style: WebDesignTextStyle;
      content: string;
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
    };
