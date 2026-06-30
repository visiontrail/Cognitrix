"use client";

import { FormEvent, useMemo, useRef, useState } from "react";
import { AlertCircle, Bot, Brain, ChevronDown, ChevronRight, Loader2, Send, Wrench, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { streamPublicAssistant, type PublishedManifest } from "@/lib/public/api";
import { useI18n } from "@/lib/i18n/context";
import { cn, isRecord } from "@/lib/utils";

type PublicAssistantDrawerProps = {
  token: string;
  manifest: PublishedManifest;
  open: boolean;
  selectedChartId?: string;
  onClose: () => void;
};

type DrawerMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  traceRows?: TraceRow[];
  traceState?: TraceState;
};

type TraceRow = {
  id: string;
  label: string;
  detail?: string;
  status: "running" | "success" | "error";
};
type TraceState = "live" | "collapsed" | "expanded";
type TranslateFn = (key: string, params?: Record<string, string | number | null | undefined>) => string;

export function PublicAssistantDrawer({
  token,
  manifest,
  open,
  selectedChartId,
  onClose,
}: PublicAssistantDrawerProps) {
  const { t } = useI18n();
  const conversationIdRef = useRef(`public-${createId()}`);
  const [messages, setMessages] = useState<DrawerMessage[]>([]);
  const [input, setInput] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const assistantAvailable = manifest.assistant?.available === true;
  const selectedChart = useMemo(
    () => manifest.charts.find((chart) => chart.chart_id === selectedChartId),
    [manifest.charts, selectedChartId]
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = input.trim();
    if (!message || isRunning || !assistantAvailable) return;
    setInput("");
    setError(null);
    setIsRunning(true);
    const assistantMessageId = createId();
    setMessages((current) => [
      ...current,
      { id: createId(), role: "user", text: message },
      { id: assistantMessageId, role: "assistant", text: "", traceRows: [], traceState: "live" },
    ]);

    try {
      for await (const event of streamPublicAssistant(token, {
        message,
        conversation_id: conversationIdRef.current,
        chart_id: selectedChartId,
      })) {
        const payload = isRecord(event.data) ? event.data : {};
        if (event.event === "planning") {
          const text = String(payload.text ?? t("public.assistant.planning"));
          appendTraceRow(assistantMessageId, {
            id: `planning-${createId()}`,
            label: t("public.assistant.planning"),
            detail: text,
            status: "running",
          });
          continue;
        }
        if (event.event === "tool_use") {
          const stepId = String(payload.step_id ?? createId());
          const toolName = String(payload.tool_name ?? t("public.assistant.tool"));
          updateAssistantMessage(assistantMessageId, (assistant) => ({
            ...assistant,
            traceRows: [
              ...(assistant.traceRows ?? []).filter((row) => row.id !== stepId),
              { id: stepId, label: toolName, detail: t("public.assistant.toolRunning"), status: "running" },
            ],
          }));
          continue;
        }
        if (event.event === "tool_result") {
          const stepId = String(payload.step_id ?? createId());
          const status: TraceRow["status"] = payload.status === "error" ? "error" : "success";
          updateAssistantMessage(assistantMessageId, (assistant) => {
            const rows = assistant.traceRows ?? [];
            const nextRow: TraceRow = {
              id: stepId,
              label: t("public.assistant.tool"),
              detail: resultPreview(payload.result, t),
              status,
            };
            return {
              ...assistant,
              traceRows: rows.some((row) => row.id === stepId)
                ? rows.map((row) => (row.id === stepId ? { ...row, status, detail: nextRow.detail } : row))
                : [...rows, nextRow],
            };
          });
          continue;
        }
        if (event.event === "final") {
          const text = String(payload.text ?? "").trim();
          updateAssistantMessage(assistantMessageId, (assistant) => ({
            ...assistant,
            text,
            traceRows: markTraceRowsComplete(assistant.traceRows ?? []),
            traceState: "collapsed",
          }));
          setIsRunning(false);
          continue;
        }
        if (event.event === "error") {
          const text = String(payload.message ?? t("public.assistant.error"));
          setError(text);
          appendTraceRow(assistantMessageId, {
            id: `error-${createId()}`,
            label: t("public.assistant.errorTitle"),
            detail: text,
            status: "error",
          });
          updateAssistantMessage(assistantMessageId, (assistant) => ({
            ...assistant,
            traceState: "expanded",
          }));
          setIsRunning(false);
        }
      }
    } catch {
      setError(t("public.assistant.error"));
      appendTraceRow(assistantMessageId, {
        id: `error-${createId()}`,
        label: t("public.assistant.errorTitle"),
        detail: t("public.assistant.error"),
        status: "error",
      });
      updateAssistantMessage(assistantMessageId, (assistant) => ({ ...assistant, traceState: "expanded" }));
    } finally {
      setIsRunning(false);
    }
  }

  function updateAssistantMessage(
    messageId: string,
    updater: (message: DrawerMessage) => DrawerMessage
  ) {
    setMessages((current) =>
      current.map((message) => (message.id === messageId ? updater(message) : message))
    );
  }

  function appendTraceRow(messageId: string, row: TraceRow) {
    updateAssistantMessage(messageId, (assistant) => ({
      ...assistant,
      traceRows: [...(assistant.traceRows ?? []), row],
    }));
  }

  function setAssistantTraceState(messageId: string, traceState: TraceState) {
    updateAssistantMessage(messageId, (assistant) => ({ ...assistant, traceState }));
  }

  if (!open) return null;

  return (
    <aside
      className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-[#d8d1c1] bg-[#fffdf8] text-[#2f332f] shadow-xl dark:border-white/15 dark:bg-[#141426] dark:text-white sm:w-[420px]"
      data-public-canvas-control
      data-public-canvas-export-ignore
      data-testid="public-assistant-drawer"
    >
      <header className="flex h-14 items-center justify-between border-b border-[#e8dfcf] px-4 dark:border-white/10">
        <div className="flex min-w-0 items-center gap-2">
          <Bot className="h-4 w-4 text-[#4b7f8c]" aria-hidden="true" />
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold">{t("public.assistant.title")}</h2>
            {selectedChart ? (
              <p className="truncate text-xs text-[#777166] dark:text-gray-300">{selectedChart.title}</p>
            ) : null}
          </div>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          onClick={onClose}
          aria-label={t("public.assistant.close")}
          className="h-8 w-8"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </Button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {!assistantAvailable ? (
          <div className="rounded-md border border-[#e8dfcf] bg-white p-3 text-sm text-[#777166] dark:border-white/10 dark:bg-white/[0.04] dark:text-gray-300">
            {t("public.assistant.unavailable")}
          </div>
        ) : null}

        <div className="space-y-3">
          {messages.map((message) => (
            <div
              key={message.id}
              className={cn(
                "max-w-[88%] text-sm leading-relaxed",
                message.role === "user"
                  ? "ml-auto"
                  : "mr-auto"
              )}
            >
              {message.role === "assistant" ? (
                <PublicAssistantTrace
                  rows={message.traceRows ?? []}
                  state={message.traceState ?? "collapsed"}
                  onToggle={() =>
                    setAssistantTraceState(
                      message.id,
                      message.traceState === "expanded" ? "collapsed" : "expanded"
                    )
                  }
                  t={t}
                />
              ) : null}
              {message.text ? (
                <div
                  className={cn(
                    "rounded-md px-3 py-2",
                    message.role === "user"
                      ? "bg-[#335f69] text-white"
                      : "border border-[#e8dfcf] bg-white text-[#2f332f] dark:border-white/10 dark:bg-white/[0.06] dark:text-white"
                  )}
                >
                  <p className="whitespace-pre-wrap break-words">{message.text}</p>
                </div>
              ) : null}
            </div>
          ))}
        </div>

        {error ? (
          <div className="mt-4 rounded-md border border-[#e8c0af] bg-[#fff4ef] p-3 text-sm text-[#8a3a22] dark:border-[#c96442]/40 dark:bg-[#341a13] dark:text-[#ffd4c6]">
            {error}
          </div>
        ) : null}
      </div>

      <form onSubmit={handleSubmit} className="border-t border-[#e8dfcf] p-3 dark:border-white/10">
        <div className="flex items-end gap-2">
          <Textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder={t("public.assistant.placeholder")}
            disabled={!assistantAvailable || isRunning}
            className="min-h-11 resize-none bg-white dark:bg-white/[0.06]"
            data-testid="public-assistant-input"
          />
          <Button
            type="submit"
            size="icon-sm"
            disabled={!input.trim() || !assistantAvailable || isRunning}
            aria-label={t("public.assistant.send")}
            className="h-10 w-10 shrink-0"
          >
            {isRunning ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Send className="h-4 w-4" aria-hidden="true" />
            )}
          </Button>
        </div>
      </form>
    </aside>
  );
}

function PublicAssistantTrace({
  rows,
  state,
  onToggle,
  t,
}: {
  rows: TraceRow[];
  state: TraceState;
  onToggle: () => void;
  t: TranslateFn;
}) {
  if (rows.length === 0 && state !== "live") return null;

  const hasError = rows.some((row) => row.status === "error");
  const running = state === "live";
  const expanded = state === "expanded" || running;
  const toolCount = rows.filter((row) => row.id.startsWith("planning-") === false && row.status !== "error").length;
  const label = running
    ? t("public.assistant.planning")
    : hasError
      ? t("public.assistant.errorTitle")
      : `${t("public.assistant.traceComplete")} · ${t("chat.trace.toolCallsCount", { count: toolCount })}`;

  return (
    <div className={cn("mb-2", rows.length === 0 && "min-h-5")}>
      <button
        type="button"
        className={cn(
          "flex max-w-full items-center gap-1.5 text-xs text-[#777166] underline-offset-2 hover:underline dark:text-gray-300",
          running && "cursor-default hover:no-underline"
        )}
        onClick={running ? undefined : onToggle}
        disabled={running}
        aria-expanded={expanded}
      >
        {running ? (
          <Brain className="h-3.5 w-3.5 shrink-0 animate-pulse text-[#4b7f8c]" aria-hidden="true" />
        ) : expanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        )}
        <span className="truncate">{label}</span>
      </button>

      {expanded ? (
        <div className="mt-2 max-h-[40vh] space-y-2 overflow-y-auto border-l border-[#d8e6ea] pl-3 dark:border-[#4b7f8c]/40">
          {rows.map((row) => (
            <div key={row.id} className="flex gap-2 text-xs text-[#555250] dark:text-gray-200">
              {row.id.startsWith("planning-") ? (
                <Brain
                  className={cn(
                    "mt-0.5 h-3.5 w-3.5 shrink-0 text-[#4b7f8c]",
                    row.status === "running" && "animate-pulse"
                  )}
                  aria-hidden="true"
                />
              ) : row.status === "running" ? (
                <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-[#4b7f8c]" aria-hidden="true" />
              ) : row.status === "error" ? (
                <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#c96442]" aria-hidden="true" />
              ) : (
                <Wrench className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#4b7f8c]" aria-hidden="true" />
              )}
              <div className="min-w-0">
                <p className="truncate font-medium">{row.label}</p>
                {row.detail ? <p className="line-clamp-2 text-[#777166] dark:text-gray-300">{row.detail}</p> : null}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function markTraceRowsComplete(rows: TraceRow[]): TraceRow[] {
  return rows.map((row) =>
    row.status === "running" ? { ...row, status: "success" } : row
  );
}

function resultPreview(result: unknown, t: TranslateFn): string {
  if (!isRecord(result)) return t("public.assistant.toolComplete");
  const rowCount = typeof result.row_count === "number" ? result.row_count : undefined;
  if (rowCount !== undefined) {
    return t("public.assistant.rowsReturned", { count: rowCount });
  }
  if (Array.isArray(result.tables)) {
    return t("public.assistant.tablesAvailable", { count: result.tables.length });
  }
  return t("public.assistant.toolComplete");
}

function createId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2, 10);
}
