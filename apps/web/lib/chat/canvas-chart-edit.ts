import { useChatStore } from "@/stores/chat-store";
import { useUIStore } from "@/stores/ui-store";
import { useWorkspaceStore } from "@/stores/workspace-store";
import type { ChartNodeData } from "@/types/workspace";

export type BeginCanvasChartEditResult = "started" | "no_session" | "no_workspace";

/**
 * Put one canvas chart into the active conversation's composer.
 *
 * Keeping this transition in one place matters: both the free-layout node and
 * the web-design zone expose the affordance, and they must bind to exactly the
 * same session/workspace identity before the chat panel is revealed.
 */
export function beginCanvasChartEdit({
  nodeId,
  data,
  pageId,
  zoneId,
}: {
  nodeId: string;
  data: ChartNodeData;
  pageId?: string;
  zoneId?: string;
}): BeginCanvasChartEditResult {
  const sessionId = useChatStore.getState().activeSessionId;
  if (!sessionId) return "no_session";

  const workspace = useWorkspaceStore.getState();
  if (!workspace.activeWorkspaceId) return "no_workspace";

  const ui = useUIStore.getState();
  ui.setChartEditTarget({
    sessionId,
    workspaceId: workspace.activeWorkspaceId,
    canvasFormat: workspace.canvasFormat.id,
    nodeId,
    zoneId,
    pageId,
    assetId: data.assetId,
    title: data.title,
    chartType: data.chartType,
    spec: data.spec,
    assistantRows: data.assistantRows,
  });
  ui.setActivePanel("both");
  return "started";
}
