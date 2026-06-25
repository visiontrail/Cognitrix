"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useSendMessage } from "@/hooks/use-chat";
import { useI18n } from "@/lib/i18n/context";
import { cn } from "@/lib/utils";
import type { MultiChartConfirmation } from "@/types/chat";

type Props = {
  sessionId: string;
  confirmation: MultiChartConfirmation;
};

export function MultiChartConfirmationBox({ sessionId, confirmation }: Props) {
  const { t } = useI18n();
  const sendMessage = useSendMessage();
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(
    () => new Set(confirmation.items.filter((item) => item.selected !== false).map((item) => item.key))
  );
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    setSelectedKeys(new Set(confirmation.items.filter((item) => item.selected !== false).map((item) => item.key)));
    setSubmitted(false);
  }, [confirmation.confirmationId, confirmation.items]);

  const selectedItems = useMemo(
    () => confirmation.items.filter((item) => selectedKeys.has(item.key)),
    [confirmation.items, selectedKeys]
  );
  const selectedCount = selectedItems.length;
  const overLimit = selectedCount > confirmation.maxChartCount;
  const interactionsLocked = submitted || sendMessage.isPending;
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
    sendMessage.mutate({
      sessionId,
      content: t("chat.multiChart.confirmMessage", { count: selectedCount }),
      // Replay the data-labels option captured when this confirmation opened —
      // the specs are produced on this turn, so the flag must travel with it.
      showDataLabels: confirmation.showDataLabels,
      multiChartConfirmation: {
        confirmationId: confirmation.confirmationId,
        action: selectedCount === confirmation.items.length ? "confirm" : "adjust",
        selectedItems: selectedItems.map((item) => ({ key: item.key, label: item.label })),
      },
    });
  };

  const cancel = () => {
    if (interactionsLocked) return;
    setSubmitted(true);
    sendMessage.mutate({
      sessionId,
      content: t("chat.multiChart.cancelMessage"),
      multiChartConfirmation: {
        confirmationId: confirmation.confirmationId,
        action: "cancel",
      },
    });
  };

  return (
    <div className="w-full max-w-lg rounded-generous border border-border-cream bg-ivory px-4 py-3 shadow-whisper">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-body-sm font-semibold text-near-black">
            {t("chat.multiChart.title")}
          </p>
          <p className="mt-1 text-caption leading-relaxed text-stone-gray">
            {confirmation.reason || t("chat.multiChart.defaultReason", { dimension: confirmation.groupingDimension })}
          </p>
        </div>
        <Badge variant={overLimit ? "destructive" : "secondary"}>
          {t("chat.multiChart.countBadge", {
            selected: selectedCount,
            max: confirmation.maxChartCount,
          })}
        </Badge>
      </div>

      <div className="mt-3 max-h-52 space-y-2 overflow-y-auto pr-1">
        {confirmation.items.map((item) => (
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
            <span className="min-w-0 flex-1 break-words">{item.label}</span>
          </label>
        ))}
      </div>

      {(overLimit || confirmation.truncated) && (
        <p className="mt-2 text-caption leading-relaxed text-error-crimson">
          {overLimit
            ? t("chat.multiChart.limitExceeded", { max: confirmation.maxChartCount })
            : t("chat.multiChart.truncated", { max: confirmation.maxChartCount })}
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={confirm} disabled={!canConfirm}>
          <Check className="h-3.5 w-3.5" />
          {t("chat.multiChart.generateSelected", { count: selectedCount })}
        </Button>
        <Button size="sm" variant="ghost" onClick={cancel} disabled={interactionsLocked}>
          <X className="h-3.5 w-3.5" />
          {t("chat.multiChart.cancel")}
        </Button>
      </div>
    </div>
  );
}
