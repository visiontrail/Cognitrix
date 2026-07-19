import type { AgentCanvasWireOp } from "@/lib/chat/agent-canvas";
import {
  AGENT_ERROR_CHART_TYPE,
  agentNodeIdForBlock,
  spanForSizePreset,
  type AgentCanvasStoreOp,
} from "@/lib/workspace/agent-canvas-layout";
import { useAssetStore } from "@/stores/asset-store";
import { useWorkspaceStore } from "@/stores/workspace-store";
import type { ChartAsset } from "@/types/chart";
import type { ChartNodeData, WebDesignTextStyle, WorkspaceNode } from "@/types/workspace";

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

function chartNodeFor(blockId: string, asset: ChartAsset): WorkspaceNode {
  const data: ChartNodeData = {
    type: "chart",
    assetId: asset.id,
    title: asset.title,
    chartType: asset.chartType,
    spec: asset.spec,
    assistantRows: asset.assistantRows,
    assistantRowsComplete: asset.assistantRowsComplete,
    width: 480,
    height: 320,
  };
  return {
    id: agentNodeIdForBlock(blockId),
    type: "chartNode",
    position: { x: 0, y: 0 },
    data,
  };
}

function errorPlaceholderNodeFor(blockId: string, payload: Record<string, unknown>): WorkspaceNode {
  const error = (payload.error ?? {}) as Record<string, unknown>;
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
    width: 480,
    height: 320,
  };
  return {
    id: agentNodeIdForBlock(blockId),
    type: "chartNode",
    position: { x: 0, y: 0 },
    data,
  };
}

export function toStoreOp(op: AgentCanvasWireOp, deps: AgentCanvasOpDeps): AgentCanvasStoreOp | null {
  const payload = op.payload;
  const blockId = String(payload.block_id ?? "");
  switch (op.opType) {
    case "create_page":
      return { type: "create_page", pageId: op.pageId, title: String(payload.title ?? "Dashboard") };
    case "add_section":
      if (!blockId) return null;
      return {
        type: "add_section",
        pageId: op.pageId,
        blockId,
        title: String(payload.title ?? ""),
      };
    case "add_text_block":
      if (!blockId) return null;
      return {
        type: "add_text_block",
        pageId: op.pageId,
        blockId,
        style: normalizeTextStyle(payload.style),
        content: String(payload.content ?? ""),
      };
    case "place_chart": {
      if (!blockId) return null;
      const assetId = String(payload.asset_id ?? "");
      const asset = deps.toAsset(payload.spec, {
        assetId: assetId || `asset-${blockId}`,
        title: String(payload.title ?? ""),
      });
      if (!asset) return null;
      return {
        type: "place_chart",
        pageId: op.pageId,
        blockId,
        chartId: asset.id,
        node: chartNodeFor(blockId, asset),
        span: spanForSizePreset(String(payload.size_preset ?? "")),
      };
    }
    case "error_placeholder":
      if (!blockId) return null;
      return {
        type: "error_placeholder",
        pageId: op.pageId,
        blockId,
        node: errorPlaceholderNodeFor(blockId, payload),
        span: spanForSizePreset(String(payload.size_preset ?? "")),
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
