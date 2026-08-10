"use client";

import { useEffect } from "react";
import { toChartAsset } from "@/hooks/use-chat";
import { useBackendCapabilities } from "@/hooks/use-backend-capabilities";
import {
  fetchActiveAgentRun,
  fetchAgentRunOps,
  tailAgentRun,
} from "@/lib/chat/agent-canvas";
import { applyAgentCanvasWireOp, type AgentCanvasOpDeps } from "@/lib/workspace/agent-canvas-ops";
import { isAgentNodeForRun } from "@/lib/workspace/agent-canvas-layout";
import { useUIStore } from "@/stores/ui-store";
import { useWorkspaceStore } from "@/stores/workspace-store";

const RUNNING_STATUSES = new Set(["running"]);

function opDeps(runId: string): AgentCanvasOpDeps {
  return {
    toAsset: (rawSpec, meta) =>
      toChartAsset(rawSpec, {
        sessionId: "",
        messageId: runId,
        prompt: meta.title,
        assetId: meta.assetId,
        title: meta.title,
      }),
  };
}

/**
 * Reconnect/replay for agent-canvas runs (canvas-op-streaming spec): on load
 * (after the workspace snapshot has been applied), query the workspace's
 * active/latest run; replay missed ops idempotently onto the run page and
 * re-attach to the live tail while the run is still `running`.
 *
 * Terminal runs are reconciled only when their page already exists on the
 * canvas — replaying a finished run onto a canvas where the user deleted the
 * page (run-level undo) must not resurrect it.
 */
export function useAgentCanvasRunRecovery({ enabled }: { enabled: boolean }) {
  const workspaceId = useWorkspaceStore((s) => s.activeWorkspaceId);
  const capabilities = useBackendCapabilities();
  const active = enabled && Boolean(workspaceId) && capabilities.agentCanvasModeEnabled;

  useEffect(() => {
    if (!active || !workspaceId) return;
    const abort = new AbortController();
    let cancelled = false;

    (async () => {
      const run = await fetchActiveAgentRun(workspaceId);
      if (cancelled || !run || !run.runId) return;
      const deps = opDeps(run.runId);
      const isRunning = RUNNING_STATUSES.has(run.status);

      if (!isRunning) {
        const workspace = useWorkspaceStore.getState();
        const pageExists =
          (workspace.webDesign.pages ?? []).some((page) => page.id === run.pageId) ||
          [workspace.nodes, ...Object.values(workspace.nodesByFormat)].some((nodes) =>
            (nodes ?? []).some((node) => isAgentNodeForRun(node, run.runId))
          );
        useUIStore.getState().clearAgentRun(run.runId);
        if (!pageExists) return;
        const { ops } = await fetchAgentRunOps(run.runId, 0);
        if (cancelled) return;
        for (const op of ops) {
          applyAgentCanvasWireOp(op, deps);
        }
        return;
      }

      useUIStore.getState().setActiveAgentRun({
        runId: run.runId,
        pageId: run.pageId,
        workspaceId,
        canvasFormat: run.canvasFormat,
      });
      const { ops } = await fetchAgentRunOps(run.runId, 0);
      if (cancelled) {
        return;
      }
      let lastSeq = 0;
      for (const op of ops) {
        applyAgentCanvasWireOp(op, deps);
        lastSeq = Math.max(lastSeq, op.seq);
      }
      try {
        await tailAgentRun(
          run.runId,
          lastSeq,
          (op) => {
            if (!cancelled) applyAgentCanvasWireOp(op, deps);
          },
          abort.signal
        );
      } catch {
        // Tail interruptions are non-destructive; the next load replays again.
      } finally {
        if (!cancelled) {
          useUIStore.getState().clearAgentRun(run.runId);
        }
      }
    })().catch(() => {
      // Recovery is best-effort; a failed probe must never break the canvas.
    });

    return () => {
      cancelled = true;
      abort.abort();
    };
  }, [active, workspaceId]);
}
