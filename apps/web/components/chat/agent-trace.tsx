"use client";

import { useEffect, useRef, useState } from "react";
import { useChatStore } from "@/stores/chat-store";
import { useI18n } from "@/lib/i18n/context";
import { AgentTraceStep } from "./agent-trace-step";
import { Brain } from "lucide-react";
import type { TraceSummary } from "@/types/chat";

function ThinkingDots() {
  return (
    <span className="flex items-center gap-0.5">
      <span className="w-1 h-1 rounded-full bg-stone-gray animate-bounce" style={{ animationDelay: "0ms" }} />
      <span className="w-1 h-1 rounded-full bg-stone-gray animate-bounce" style={{ animationDelay: "160ms" }} />
      <span className="w-1 h-1 rounded-full bg-stone-gray animate-bounce" style={{ animationDelay: "320ms" }} />
    </span>
  );
}

function formatDurationSec(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

type Props = {
  messageId: string;
  traceSummary?: TraceSummary;
};

export function AgentTrace({ messageId, traceSummary }: Props) {
  const { t } = useI18n();
  const trace = useChatStore((s) => s.traceByMessageId[messageId]);
  const setTraceState = useChatStore((s) => s.setTraceState);

  // 1Hz tick for elapsed time display while live
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (trace?.state !== "live") return;
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, [trace?.state]);

  // Auto-scroll latest live step into view
  const liveEndRef = useRef<HTMLDivElement>(null);
  // Auto-scroll planning text container to bottom
  const planningEndRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (trace?.state === "live") {
      liveEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      planningEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [trace?.steps?.length, trace?.state]);

  // No in-memory trace and no summary — nothing to show
  if (!trace && !traceSummary) return null;

  // No in-memory trace but summary exists: render minimal chip using summary only
  if (!trace) {
    const durationStr = formatDurationSec(traceSummary!.durationMs);
    const hasError = traceSummary!.status === "error";
    const label = hasError
      ? t("chat.trace.errored", { duration: durationStr })
      : `${t("chat.trace.thoughtFor", { duration: durationStr })} · ${t("chat.trace.toolCallsCount", { count: traceSummary!.stepCount })}`;
    return (
      <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-0.5">
        <span
          className={`text-[10px] select-none cursor-help ${hasError ? "text-terracotta" : "text-stone-gray"}`}
          title={t("chat.trace.bodiesUnavailableAfterReload")}
        >
          {label}
        </span>
        <span className="text-[10px] text-stone-gray/75 select-none">{t("chat.trace.aiDisclaimer")}</span>
      </div>
    );
  }

  const steps = trace.steps;
  const isLive = trace.state === "live";

  // Live state — three phases depending on what has arrived so far
  if (isLive) {
    // Phase 0: no events yet → blinking "思考中"
    if (steps.length === 0) {
      return (
        <div className="mb-2">
          <div className="flex items-center gap-1.5 pl-3 border-l border-border-cream py-1">
            <Brain className="w-3 h-3 text-stone-gray shrink-0 animate-pulse" />
            <span className="text-[11px] text-stone-gray select-none">思考中</span>
            <ThinkingDots />
          </div>
        </div>
      );
    }

    const hasActionSteps = steps.some((s) => s.kind === "tool" || s.kind === "error");

    // Phase 1: planning only (no tool calls yet) → compact 3-4 line scrollable text
    if (!hasActionSteps) {
      const planningText = steps
        .filter((s) => s.kind === "planning")
        .map((s) => s.text)
        .join("\n\n");
      return (
        <div className="mb-2">
          <div className="border-l border-border-cream pl-3">
            <div className="flex items-center gap-1.5 mb-1">
              <Brain className="w-3 h-3 text-stone-gray shrink-0 animate-pulse" />
              <span className="text-[10px] text-stone-gray select-none">思考中</span>
              <ThinkingDots />
            </div>
            <div className="max-h-[4.5rem] overflow-y-auto">
              <p className="text-[11px] text-stone-gray leading-snug whitespace-pre-wrap">
                {planningText}
              </p>
              <div ref={planningEndRef} />
            </div>
          </div>
        </div>
      );
    }

    // Phase 2: tool calls in progress — fully expanded with max-height cap and internal scroll
    return (
      <div className="mb-2">
        <div className="max-h-[60vh] overflow-y-auto border-l border-border-cream pl-3 space-y-0.5">
          {steps.map((step, i) => (
            <AgentTraceStep
              key={step.id}
              step={step}
              isLive={true}
              isLatest={i === steps.length - 1}
              nowMs={nowMs}
            />
          ))}
          <div ref={liveEndRef} />
        </div>
      </div>
    );
  }

  // Collapsed / expanded state
  const durationMs = (trace.endedAt ?? Date.now()) - trace.startedAt;
  const durationStr = formatDurationSec(durationMs);
  const toolCount = steps.filter((s) => s.kind === "tool").length;
  const hasError = steps.some((s) => s.kind === "error");
  const isExpanded = trace.state === "expanded";

  const chipLabel = hasError
    ? t("chat.trace.errored", { duration: durationStr })
    : `${t("chat.trace.thoughtFor", { duration: durationStr })} · ${t("chat.trace.toolCallsCount", { count: toolCount })}`;

  return (
    <div className="mb-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
        <button
          type="button"
          className={`text-[10px] underline-offset-2 hover:underline select-none ${hasError ? "text-terracotta" : "text-stone-gray"}`}
          onClick={() => setTraceState(messageId, isExpanded ? "collapsed" : "expanded")}
          title={isExpanded ? t("chat.trace.collapse") : t("chat.trace.expand")}
        >
          {chipLabel}
        </button>
        <span className="text-[10px] text-stone-gray/75 select-none">{t("chat.trace.aiDisclaimer")}</span>
      </div>

      {isExpanded && steps.length > 0 && (
        <div className="mt-1 max-h-[60vh] overflow-y-auto border-l border-border-cream pl-3 space-y-0.5">
          {steps.map((step) => (
            <AgentTraceStep
              key={step.id}
              step={step}
              isLive={false}
              isLatest={false}
              nowMs={nowMs}
            />
          ))}
        </div>
      )}
    </div>
  );
}
