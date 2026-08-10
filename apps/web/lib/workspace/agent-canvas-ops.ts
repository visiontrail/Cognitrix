import type { AgentCanvasWireOp } from "@/lib/chat/agent-canvas";
import {
  AGENT_ERROR_CHART_TYPE,
  agentChartNodeSize,
  agentNodeIdForBlock,
  agentTextNodeSize,
  normalizeSectionLevel,
  spanForSizePreset,
  textStyleForSectionLevel,
  type AgentCanvasStoreOp,
} from "@/lib/workspace/agent-canvas-layout";
import { useAssetStore } from "@/stores/asset-store";
import { useWorkspaceStore } from "@/stores/workspace-store";
import type { ChartAsset } from "@/types/chart";
import type {
  ChartNodeData,
  TextNodeData,
  WebDesignTextStyle,
  WorkspaceCanvasFormatId,
  WorkspaceNode,
} from "@/types/workspace";

/**
 * Wire-op dispatcher: converts a `canvas_op` SSE payload into a store op and
 * applies it. Deterministic block/node ids + the store's idempotent skip make
 * overlapping live delivery and replay safe to interleave.
 *
 * `toAsset` converts the backend raw chart spec into a client ChartAsset; the
 * caller supplies it (the chat hook owns that conversion) so this module never
 * depends on hook internals.
 */

export type AgentCanvasOpDeps = {
  toAsset: (rawSpec: unknown, meta: { assetId: string; title: string }) => ChartAsset | null;
};

const TEXT_STYLES: readonly WebDesignTextStyle[] = ["title", "subtitle", "body"];

function normalizeTextStyle(value: unknown): WebDesignTextStyle {
  return TEXT_STYLES.includes(value as WebDesignTextStyle)
    ? (value as WebDesignTextStyle)
    : "body";
}

function agentMetadata(op: AgentCanvasWireOp, blockId: string) {
  return {
    agentRunId: op.runId,
    agentPageId: op.pageId,
    agentBlockId: blockId,
  };
}

function chartNodeFor(op: AgentCanvasWireOp, blockId: string, asset: ChartAsset, sizePreset: string): WorkspaceNode {
  const size = agentChartNodeSize(op.canvasFormat, sizePreset);
  const data: ChartNodeData = {
    type: "chart",
    assetId: asset.id,
    title: asset.title,
    chartType: asset.chartType,
    spec: asset.spec,
    assistantRows: asset.assistantRows,
    assistantRowsComplete: asset.assistantRowsComplete,
    width: size.width,
    height: size.height,
    ...agentMetadata(op, blockId),
  };
  return {
    id: agentNodeIdForBlock(blockId),
    type: "chartNode",
    position: { x: 0, y: 0 },
    width: size.width,
    height: size.height,
    initialWidth: size.width,
    initialHeight: size.height,
    data,
  };
}

function errorPlaceholderNodeFor(
  op: AgentCanvasWireOp,
  blockId: string,
  payload: Record<string, unknown>,
  sizePreset: string
): WorkspaceNode {
  const error = (payload.error ?? {}) as Record<string, unknown>;
  const size = agentChartNodeSize(op.canvasFormat, sizePreset);
  const data: ChartNodeData = {
    type: "chart",
    assetId: blockId,
    title: String(payload.title ?? ""),
    chartType: AGENT_ERROR_CHART_TYPE,
    spec: {
      chartType: AGENT_ERROR_CHART_TYPE,
      title: String(payload.title ?? ""),
      subtitle: String(error.message ?? ""),
      echartsOption: {},
    },
    width: size.width,
    height: size.height,
    ...agentMetadata(op, blockId),
  };
  return {
    id: agentNodeIdForBlock(blockId),
    type: "chartNode",
    position: { x: 0, y: 0 },
    width: size.width,
    height: size.height,
    initialWidth: size.width,
    initialHeight: size.height,
    data,
  };
}

function textNodeFor(
  op: AgentCanvasWireOp,
  blockId: string,
  content: string,
  style: WebDesignTextStyle,
  pageMarker = false
): WorkspaceNode {
  const size = agentTextNodeSize(op.canvasFormat, style, pageMarker);
  const data: TextNodeData = {
    type: "text",
    content,
    fontSize: size.fontSize,
    fontWeight: style === "body" ? "normal" : "bold",
    color: "#3f3d39",
    width: size.width,
    height: size.height,
    ...agentMetadata(op, blockId),
    agentPageMarker: pageMarker,
  };
  return {
    id: agentNodeIdForBlock(blockId),
    type: "textNode",
    position: { x: 0, y: 0 },
    dragHandle: ".text-node-drag-handle",
    width: size.width,
    height: size.height,
    initialWidth: size.width,
    initialHeight: size.height,
    data,
  };
}

export function toStoreOp(op: AgentCanvasWireOp, deps: AgentCanvasOpDeps): AgentCanvasStoreOp | null {
  const payload = op.payload;
  const blockId = String(
    payload.block_id ?? (op.opType === "create_page" ? `agent-page-${op.runId}-${op.seq}` : "")
  );
  const base = { runId: op.runId, canvasFormat: op.canvasFormat };
  switch (op.opType) {
    case "create_page":
      if (!blockId) return null;
      return {
        ...base,
        type: "create_page",
        pageId: op.pageId,
        blockId,
        title: String(payload.title ?? "Dashboard"),
        parentPageId: String(payload.parent_page_id ?? ""),
        node: textNodeFor(
          op,
          blockId,
          String(payload.title ?? "Dashboard"),
          "title",
          true
        ),
      };
    case "add_section":
      if (!blockId) return null;
      return {
        ...base,
        type: "add_section",
        pageId: op.pageId,
        blockId,
        title: String(payload.title ?? ""),
        level: normalizeSectionLevel(payload.level),
        node: textNodeFor(
          op,
          blockId,
          String(payload.title ?? ""),
          textStyleForSectionLevel(normalizeSectionLevel(payload.level))
        ),
      };
    case "add_text_block":
      if (!blockId) return null;
      return {
        ...base,
        type: "add_text_block",
        pageId: op.pageId,
        blockId,
        style: normalizeTextStyle(payload.style),
        content: String(payload.content ?? ""),
        node: textNodeFor(
          op,
          blockId,
          String(payload.content ?? ""),
          normalizeTextStyle(payload.style)
        ),
      };
    case "place_chart": {
      if (!blockId) return null;
      const assetId = String(payload.asset_id ?? "");
      const asset = deps.toAsset(payload.spec, {
        assetId: assetId || `asset-${blockId}`,
        title: String(payload.title ?? ""),
      });
      if (!asset) return null;
      const sizePreset = String(payload.size_preset ?? "");
      return {
        ...base,
        type: "place_chart",
        pageId: op.pageId,
        blockId,
        chartId: asset.id,
        node: chartNodeFor(op, blockId, asset, sizePreset),
        span: spanForSizePreset(sizePreset),
      };
    }
    case "error_placeholder":
      if (!blockId) return null;
      const sizePreset = String(payload.size_preset ?? "");
      return {
        ...base,
        type: "error_placeholder",
        pageId: op.pageId,
        blockId,
        node: errorPlaceholderNodeFor(op, blockId, payload, sizePreset),
        span: spanForSizePreset(sizePreset),
      };
    default:
      return null;
  }
}

/** Apply one wire op; returns true when the op changed the canvas. */
export function applyAgentCanvasWireOp(op: AgentCanvasWireOp, deps: AgentCanvasOpDeps): boolean {
  const storeOp = toStoreOp(op, deps);
  if (!storeOp) return false;
  const applied = useWorkspaceStore.getState().applyAgentCanvasOp(storeOp);
  if (applied && storeOp.type === "place_chart") {
    // Archive the chart in the asset library too (dedupes by id).
    const asset = useAssetStore.getState().getAsset(storeOp.chartId);
    if (!asset) {
      const rebuilt = deps.toAsset(op.payload.spec, {
        assetId: storeOp.chartId,
        title: String(op.payload.title ?? ""),
      });
      if (rebuilt) useAssetStore.getState().addAsset(rebuilt);
    }
  }
  return applied;
}
