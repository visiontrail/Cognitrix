"use client";

import { useMemo, useState } from "react";
import { CheckCircle2, CircleSlash, CircleStop, TriangleAlert, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n/context";
import { useWorkspaceStore } from "@/stores/workspace-store";
import type { AgentRunSummary } from "@/types/chat";

/**
 * Terminal state of an agent-canvas run, with run-level undo ("撤销本次生成"):
 * deletes only the run's page (cascading its blocks); chart assets remain in
 * the asset library.
 */
export function AgentRunSummaryCard({ run }: { run: AgentRunSummary }) {
  const { t } = useI18n();
  const undoAgentRun = useWorkspaceStore((s) => s.undoAgentRun);
  const pageExists = useWorkspaceStore((s) =>
    (s.webDesign.pages ?? []).some((page) => page.id === run.pageId)
  );
  const [undone, setUndone] = useState(false);

  const { icon, labelKey } = useMemo(() => {
    switch (run.status) {
      case "completed":
        return { icon: <CheckCircle2 className="h-3.5 w-3.5 text-success-green" />, labelKey: "chat.agentRun.completed" };
      case "stopped":
        return { icon: <CircleStop className="h-3.5 w-3.5 text-stone-gray" />, labelKey: "chat.agentRun.stopped" };
      case "partial":
        return { icon: <TriangleAlert className="h-3.5 w-3.5 text-terracotta" />, labelKey: "chat.agentRun.partial" };
      default:
        return { icon: <CircleSlash className="h-3.5 w-3.5 text-error-crimson" />, labelKey: "chat.agentRun.failed" };
    }
  }, [run.status]);

  const handleUndo = () => {
    undoAgentRun(run.pageId);
    setUndone(true);
    toast.success(t("chat.agentRun.undone"));
  };

  const canUndo = pageExists && !undone;

  return (
    <div
      data-testid="agent-run-summary-card"
      className="flex w-full max-w-lg flex-wrap items-center justify-between gap-2 rounded-generous border border-border-cream bg-ivory px-3 py-2 shadow-whisper"
    >
      <p className="flex items-center gap-1.5 text-caption text-charcoal-warm">
        {icon}
        {t(labelKey, {
          placed: run.placedCount,
          failed: run.failedCount,
        })}
      </p>
      {canUndo && (
        <Button size="sm" variant="ghost" onClick={handleUndo}>
          <Undo2 className="h-3.5 w-3.5" />
          {t("chat.agentRun.undo")}
        </Button>
      )}
    </div>
  );
}
