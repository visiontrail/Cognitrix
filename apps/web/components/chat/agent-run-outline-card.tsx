"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, LayoutDashboard, Type, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useSendMessage } from "@/hooks/use-chat";
import {
  getAutoApprovePreference,
  setAutoApprovePreference,
} from "@/lib/chat/agent-canvas";
import { useI18n } from "@/lib/i18n/context";
import { cn } from "@/lib/utils";
import type { AgentRunOutline } from "@/types/chat";

type Props = {
  sessionId: string;
  outline: AgentRunOutline;
};

/**
 * Dashboard-outline approval card (agent canvas mode). Mirrors the multi-chart
 * confirmation UI: chart items are individually deselectable, text items are
 * informational, and a "skip approval" preference is persisted locally and
 * sent as `auto_approve` on future agent-mode requests.
 */
export function AgentRunOutlineCard({ sessionId, outline }: Props) {
  const { t } = useI18n();
  const sendMessage = useSendMessage();
  const chartKeys = useMemo(
    () =>
      outline.sections.flatMap((section) =>
        section.items.filter((item) => item.kind === "chart").map((item) => item.key)
      ),
    [outline.sections]
  );
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(() => new Set(chartKeys));
  const [skipApproval, setSkipApproval] = useState(() => getAutoApprovePreference());
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    setSelectedKeys(new Set(chartKeys));
    setSubmitted(false);
  }, [outline.confirmationId, chartKeys]);

  const selectedCount = selectedKeys.size;
  const interactionsLocked = outline.approved || submitted || sendMessage.isPending;
  const overLimit = selectedCount > outline.maxChartCount;
  const canConfirm = selectedCount > 0 && !overLimit && !interactionsLocked;

  const toggleItem = (key: string) => {
    if (interactionsLocked) return;
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const confirm = () => {
    if (!canConfirm) return;
    setSubmitted(true);
    setAutoApprovePreference(skipApproval);
    sendMessage.mutate({
      sessionId,
      content: t("chat.agentOutline.confirmMessage", { count: selectedCount }),
      agentRunConfirmation: {
        confirmationId: outline.confirmationId,
        action: "confirm",
        selectedItemKeys:
          selectedCount === chartKeys.length ? undefined : Array.from(selectedKeys),
      },
    });
  };

  const cancel = () => {
    if (interactionsLocked) return;
    setSubmitted(true);
    sendMessage.mutate({
      sessionId,
      content: t("chat.agentOutline.cancelMessage"),
      agentRunConfirmation: {
        confirmationId: outline.confirmationId,
        action: "cancel",
      },
    });
  };

  return (
    <div
      data-testid="agent-run-outline-card"
      className="w-full max-w-lg rounded-generous border border-border-cream bg-ivory px-4 py-3 shadow-whisper"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-body-sm font-semibold text-near-black">
            <LayoutDashboard className="h-3.5 w-3.5 text-terracotta" />
            {outline.pageTitle || t("chat.agentOutline.title")}
          </p>
          <p className="mt-1 text-caption leading-relaxed text-stone-gray">
            {outline.approved
              ? t("chat.agentOutline.autoApproved")
              : outline.reason || t("chat.agentOutline.defaultReason")}
          </p>
        </div>
        <Badge variant={overLimit ? "destructive" : "secondary"}>
          {t("chat.agentOutline.countBadge", {
            selected: selectedCount,
            max: outline.maxChartCount,
          })}
        </Badge>
      </div>

      <div className="mt-3 max-h-64 space-y-3 overflow-y-auto pr-1">
        {outline.sections.map((section) => (
          <div key={section.key}>
            <p className="mb-1 text-caption font-semibold uppercase tracking-wide text-stone-gray">
              {section.title}
            </p>
            <div className="space-y-1.5">
              {section.items.map((item) =>
                item.kind === "chart" ? (
                  <label
                    key={item.key}
                    aria-disabled={interactionsLocked}
                    className={cn(
                      "flex min-h-9 items-center gap-2 rounded-subtle border border-border-cream bg-parchment px-2 py-1.5 text-body-sm text-charcoal-warm",
                      interactionsLocked ? "cursor-not-allowed opacity-70" : "cursor-pointer"
                    )}
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-terracotta"
                      checked={selectedKeys.has(item.key)}
                      disabled={interactionsLocked}
                      onChange={() => toggleItem(item.key)}
                    />
                    <span className="min-w-0 flex-1 break-words">
                      {item.title}
                      {item.description ? (
                        <span className="block text-caption text-stone-gray">{item.description}</span>
                      ) : null}
                    </span>
                    <Badge variant="outline">{item.chartType}</Badge>
                  </label>
                ) : (
                  <p
                    key={item.key}
                    className="flex items-start gap-2 rounded-subtle bg-parchment/60 px-2 py-1.5 text-caption text-stone-gray"
                  >
                    <Type className="mt-0.5 h-3 w-3 shrink-0" />
                    <span className="min-w-0 break-words">{item.content}</span>
                  </p>
                )
              )}
            </div>
          </div>
        ))}
      </div>

      {(overLimit || outline.truncated) && (
        <p className="mt-2 text-caption leading-relaxed text-error-crimson">
          {overLimit
            ? t("chat.agentOutline.limitExceeded", { max: outline.maxChartCount })
            : t("chat.agentOutline.truncated", { max: outline.maxChartCount })}
        </p>
      )}

      {!outline.approved && (
        <>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={confirm} disabled={!canConfirm}>
              <Check className="h-3.5 w-3.5" />
              {t("chat.agentOutline.approve", { count: selectedCount })}
            </Button>
            <Button size="sm" variant="ghost" onClick={cancel} disabled={interactionsLocked}>
              <X className="h-3.5 w-3.5" />
              {t("chat.agentOutline.cancel")}
            </Button>
          </div>
          <label
            className={cn(
              "mt-2 flex items-center gap-1.5 text-caption text-stone-gray",
              interactionsLocked ? "cursor-not-allowed opacity-70" : "cursor-pointer"
            )}
          >
            <input
              type="checkbox"
              className="h-3.5 w-3.5 accent-terracotta"
              checked={skipApproval}
              disabled={interactionsLocked}
              onChange={(event) => setSkipApproval(event.target.checked)}
            />
            {t("chat.agentOutline.skipApproval")}
          </label>
        </>
      )}
    </div>
  );
}
