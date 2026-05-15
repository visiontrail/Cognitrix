"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useChatStore, type PendingIngestionApproval, type PendingIngestionSetup } from "@/stores/chat-store";
import { useAssetStore } from "@/stores/asset-store";
import { useUIStore } from "@/stores/ui-store";
import { useWorkspaceStore } from "@/stores/workspace-store";
import { API_BASE_URL } from "@/lib/api-base";
import { parseSSEStream } from "@/lib/chat/sse";
import {
  buildFallbackSessionTitle,
  DEFAULT_SESSION_TITLE,
  normalizeSessionTitle,
  requestGeneratedSessionTitle,
  shouldAutoGenerateSessionTitle,
} from "@/lib/chat/session-title";
import { getActiveAuthContext, getAuthorizationHeader } from "@/lib/auth/session";
import { useI18n } from "@/lib/i18n/context";
import { refreshWorkspaceCatalog } from "@/lib/workspace/query-keys";
import {
  approveIngestionProposal,
  createIngestionUpload,
  mapPlanLikePayload,
  streamIngestionExecute,
  streamIngestionPlan,
  streamIngestionSetupConfirm,
} from "@/lib/ingestion/api";
import type { IngestionSSEEvent } from "@/lib/ingestion/api";
import type { QueryChartType } from "@/lib/charts/chart-type-options";
import { buildGaugeFallbackOption, buildSingleValueFallbackOption } from "@/lib/charts/kpi-options";
import { buildRichTreemapFallbackOption } from "@/lib/charts/treemap-option";
import { generateId, isRecord } from "@/lib/utils";
import type { ChartAsset, ChartSpec, ChartType, KnownChartType } from "@/types/chart";
import type { ChatMessage, ChatSession } from "@/types/chat";
import type {
  IngestionApprovalResult,
  IngestionCatalogSetupSeed,
  IngestionExecuteResult,
  IngestionPlanAwaitingApproval,
  IngestionPlanResult,
  IngestionProposalAction,
  IngestionTimeGrain,
  IngestionUploadResult,
} from "@/types/ingestion";

const EMPTY_MESSAGES: ChatMessage[] = [];
export const chatSessionsQueryKey = (workspaceId: string | null | undefined) => ["chat-sessions", workspaceId ?? null] as const;
export const chatMessagesQueryKey = (workspaceId: string | null | undefined, sessionId: string | null | undefined) =>
  ["chat-messages", workspaceId ?? null, sessionId ?? null] as const;

function getActiveWorkspaceIdOrThrow(t: TranslateFn): string {
  const workspaceId = useWorkspaceStore.getState().activeWorkspaceId;
  if (!workspaceId) {
    throw new Error(t("chat.toast.noWorkspace"));
  }
  return workspaceId;
}

function assertSessionInCurrentScope(sessionId: string, t: TranslateFn): void {
  if (!useChatStore.getState().hasSessionInCurrentScope(sessionId)) {
    throw new Error(t("chat.requestFailed"));
  }
}

export function useChatSessions() {
  const setSessions = useChatStore((s) => s.setSessions);
  const workspaceId = useWorkspaceStore((s) => s.activeWorkspaceId);

  return useQuery({
    queryKey: chatSessionsQueryKey(workspaceId),
    queryFn: async () => {
      if (!workspaceId) {
        return [];
      }
      const sessions = useChatStore.getState().sessions;
      setSessions(sessions);
      return sessions;
    },
  });
}

export function useChatMessages(sessionId: string | null) {
  const setMessages = useChatStore((s) => s.setMessages);
  const workspaceId = useWorkspaceStore((s) => s.activeWorkspaceId);

  return useQuery({
    queryKey: chatMessagesQueryKey(workspaceId, sessionId),
    queryFn: async () => {
      if (!workspaceId || !sessionId) {
        return EMPTY_MESSAGES;
      }
      const messages = useChatStore.getState().messagesBySession[sessionId] ?? EMPTY_MESSAGES;
      setMessages(sessionId, messages);
      return messages;
    },
    enabled: Boolean(workspaceId && sessionId),
    staleTime: Infinity,
  });
}

export function useCreateSession() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const addSession = useChatStore((s) => s.addSession);
  const setActiveSession = useChatStore((s) => s.setActiveSession);
  const workspaceId = useWorkspaceStore((s) => s.activeWorkspaceId);

  return useMutation({
    mutationFn: async (title?: string) => {
      getActiveWorkspaceIdOrThrow(t);
      return createLocalSession(title);
    },
    onSuccess: (session) => {
      addSession(session);
      setActiveSession(session.id);
      queryClient.invalidateQueries({ queryKey: chatSessionsQueryKey(workspaceId) });
    },
  });
}

export function useDeleteSession() {
  const queryClient = useQueryClient();
  const removeSession = useChatStore((s) => s.removeSession);
  const workspaceId = useWorkspaceStore((s) => s.activeWorkspaceId);

  return useMutation({
    mutationFn: async (_sessionId: string) => undefined,
    onSuccess: (_, sessionId) => {
      removeSession(sessionId);
      queryClient.invalidateQueries({ queryKey: chatSessionsQueryKey(workspaceId) });
    },
  });
}

export function useSendMessage() {
  const { t, locale } = useI18n();
  const queryClient = useQueryClient();
  const appendMessage = useChatStore((s) => s.appendMessage);
  const touchSession = useChatStore((s) => s.touchSession);
  const addAsset = useAssetStore((s) => s.addAsset);
  const setSessionSending = useUIStore((s) => s.setSessionSending);

  return useMutation({
    mutationFn: async ({
      sessionId,
      content,
      attachment,
      approvedAction,
      preferredChartType,
    }: {
      sessionId: string;
      content: string;
      attachment?: File;
      approvedAction?: IngestionProposalAction;
      preferredChartType?: QueryChartType;
    }) => {
      const workspaceId = getActiveWorkspaceIdOrThrow(t);
      assertSessionInCurrentScope(sessionId, t);
      const abortController = new AbortController();
      activeChatControllers.set(sessionId, abortController);
      try {
        const trimmedContent = content.trim();
        const pendingApproval = useChatStore.getState().pendingIngestionBySession[sessionId];
        if (attachment) {
          useChatStore.getState().clearPendingIngestionApproval(sessionId);
          useChatStore.getState().clearPendingIngestionSetup(sessionId);
          return await runIngestionConversationResponse({
            sessionId,
            workspaceId,
            content: trimmedContent || t("chat.ingestion.defaultRequirement"),
            attachment,
            signal: abortController.signal,
            t,
          });
        }
        if (pendingApproval) {
          const options = collectApprovalOptions(pendingApproval.plan);
          const resolvedAction =
            approvedAction && options.includes(approvedAction)
              ? approvedAction
              : resolvePendingApprovalAction({
                  rawInput: trimmedContent,
                  pending: pendingApproval,
                });
          if (!resolvedAction) {
            if (trimmedContent) {
              useChatStore.getState().clearPendingIngestionApproval(sessionId);
              return await runIngestionRePlanningWithInstruction({
                sessionId,
                workspaceId,
                pending: pendingApproval,
                instruction: trimmedContent,
                signal: abortController.signal,
                t,
              });
            }
            throw new Error(
              t("chat.ingestion.awaitingApprovalInvalidChoice", {
                options: formatPendingApprovalOptions({
                  pending: pendingApproval,
                  t,
                }),
              })
            );
          }
          return await runIngestionApprovalResponse({
            sessionId,
            pending: pendingApproval,
            approvedAction: resolvedAction,
            signal: abortController.signal,
            t,
          });
        }
        return await streamAssistantResponse({
          sessionId,
          content: trimmedContent,
          preferredChartType,
          workspaceId,
          signal: abortController.signal,
          t,
          responseLocale: locale,
        });
      } finally {
        if (activeChatControllers.get(sessionId) === abortController) {
          activeChatControllers.delete(sessionId);
        }
        setSessionSending(sessionId, false);
      }
    },
    onMutate: ({ sessionId, content, attachment }) => {
      try {
        getActiveWorkspaceIdOrThrow(t);
        assertSessionInCurrentScope(sessionId, t);
      } catch {
        return { sessionId, optimistic: false };
      }
      setSessionSending(sessionId, true);
      const normalizedContent = formatUserMessageContent({
        content,
        attachmentName: attachment?.name,
        t,
      });
      const userMessage = createUserMessage(sessionId, normalizedContent);
      const session = useChatStore.getState().sessions.find((item) => item.id === sessionId);
      const shouldGenerateTitle = shouldAutoGenerateSessionTitle(session);
      const fallbackTitle = shouldGenerateTitle
        ? buildFallbackSessionTitle(normalizedContent)
        : undefined;
      appendMessage(sessionId, userMessage);
      touchSession(sessionId, {
        lastMessage: userMessage.content,
        messageDelta: 1,
        title: fallbackTitle,
      });
      if (shouldGenerateTitle) {
        const authContext = getActiveAuthContext(DEFAULT_AUTH_CONTEXT);
        void requestGeneratedSessionTitle({
          apiBaseUrl: API_BASE_URL,
          authContext,
          content: normalizedContent,
          locale,
        })
          .then((title) => {
            useChatStore.getState().touchSession(sessionId, { title });
          })
          .catch(() => undefined);
      }
      return { sessionId, optimistic: true };
    },
    onSuccess: ({ assistantMessage, chartAsset, preAppended, catalogRefreshWorkspaceId }, { sessionId }) => {
      if (preAppended) {
        useChatStore.getState().replaceMessage(sessionId, assistantMessage.id, assistantMessage);
      } else {
        appendMessage(sessionId, assistantMessage);
      }
      if (chartAsset) {
        addAsset(chartAsset);
      }
      touchSession(sessionId, {
        lastMessage: assistantMessage.content,
        messageDelta: 1,
      });
      const workspaceId = useWorkspaceStore.getState().activeWorkspaceId;
      queryClient.invalidateQueries({ queryKey: chatSessionsQueryKey(workspaceId) });
      queryClient.invalidateQueries({ queryKey: chatMessagesQueryKey(workspaceId, sessionId) });
      if (catalogRefreshWorkspaceId) {
        void refreshWorkspaceCatalog(queryClient, catalogRefreshWorkspaceId);
      }
    },
    onError: (error, { sessionId }) => {
      if (!useChatStore.getState().hasSessionInCurrentScope(sessionId)) {
        return;
      }
      const errorMessage: ChatMessage = {
        id: `msg-${generateId()}`,
        sessionId,
        role: "assistant",
        content: error instanceof Error ? error.message : t("chat.requestFailed"),
        timestamp: new Date().toISOString(),
      };
      appendMessage(sessionId, errorMessage);
      touchSession(sessionId, {
        lastMessage: errorMessage.content,
        messageDelta: 1,
      });
      const workspaceId = useWorkspaceStore.getState().activeWorkspaceId;
      queryClient.invalidateQueries({ queryKey: chatSessionsQueryKey(workspaceId) });
      queryClient.invalidateQueries({ queryKey: chatMessagesQueryKey(workspaceId, sessionId) });
    },
    onSettled: (_data, _error, { sessionId }) => {
      setSessionSending(sessionId, false);
    },
  });
}

const DEFAULT_DATASET_TABLE = process.env.NEXT_PUBLIC_DEFAULT_DATASET_TABLE ?? "employees_wide";
const configuredClearance = Number(process.env.NEXT_PUBLIC_DEFAULT_CLEARANCE ?? 1);
const DEFAULT_CLEARANCE = Number.isFinite(configuredClearance)
  ? Math.max(0, Math.trunc(configuredClearance))
  : 1;
const DEFAULT_AUTH_CONTEXT = {
  userId: process.env.NEXT_PUBLIC_DEFAULT_USER_ID ?? "demo-user",
  projectId: process.env.NEXT_PUBLIC_DEFAULT_PROJECT_ID ?? "demo-project",
  role: process.env.NEXT_PUBLIC_DEFAULT_ROLE ?? "hr",
  department: process.env.NEXT_PUBLIC_DEFAULT_DEPARTMENT ?? "HR",
  clearance: DEFAULT_CLEARANCE,
};
const SUPPORTED_CHART_TYPES = new Set<KnownChartType>([
  "bar",
  "negative_bar",
  "grouped_bar",
  "line",
  "pie",
  "area",
  "stacked_bar",
  "stacked_line",
  "scatter",
  "scatter_clustering",
  "radar",
  "funnel",
  "multiple_funnel",
  "radialBar",
  "composed",
  "gauge",
  "heatmap",
  "treemap",
  "sankey",
  "sunburst",
  "boxplot",
  "candlestick",
  "graph",
  "map",
  "parallel",
  "wordCloud",
  "table",
  "single_value",
  "note",
  "empty",
]);
const SUPPORTED_CHART_TYPES_BY_LOWER = new Map<string, KnownChartType>(
  Array.from(SUPPORTED_CHART_TYPES).map((item) => [item.toLowerCase(), item])
);
const CHART_TYPE_ALIASES: Record<string, KnownChartType> = {
  "stackedbar": "stacked_bar",
  "stacked-bar": "stacked_bar",
  "bar-y-category": "grouped_bar",
  "bar_y_category": "grouped_bar",
  "groupedbar": "grouped_bar",
  "grouped-bar": "grouped_bar",
  "horizontal_bar": "grouped_bar",
  "horizontal-bar": "grouped_bar",
  "horizontal_grouped_bar": "grouped_bar",
  "horizontal-grouped-bar": "grouped_bar",
  "negativebar": "negative_bar",
  "negative-bar": "negative_bar",
  "bar-negative": "negative_bar",
  "bar_negative": "negative_bar",
  "bar-negative2": "negative_bar",
  "bar_negative2": "negative_bar",
  "positive_negative_bar": "negative_bar",
  "positive-negative-bar": "negative_bar",
  "scatterclustering": "scatter_clustering",
  "scatter-clustering": "scatter_clustering",
  "scatter_cluster": "scatter_clustering",
  "scatter-cluster": "scatter_clustering",
  "clustered_scatter": "scatter_clustering",
  "clustered-scatter": "scatter_clustering",
  "stackedline": "stacked_line",
  "stacked-line": "stacked_line",
  "singlevalue": "single_value",
  "single-value": "single_value",
  "radialbar": "radialBar",
  "radial_bar": "radialBar",
  "wordcloud": "wordCloud",
  "word_cloud": "wordCloud",
  "funnelmutiple": "multiple_funnel",
  "funnel-mutiple": "multiple_funnel",
  "funnel_mutiple": "multiple_funnel",
  "funnelmultiple": "multiple_funnel",
  "funnel-multiple": "multiple_funnel",
  "funnel_multiple": "multiple_funnel",
  "multiplefunnel": "multiple_funnel",
  "multiple-funnel": "multiple_funnel",
  "multiple-funnels": "multiple_funnel",
  "multiple_funnels": "multiple_funnel",
};
const FALLBACK_OPTION_TYPES = new Set<KnownChartType>([
  "bar",
  "negative_bar",
  "grouped_bar",
  "line",
  "pie",
  "area",
  "stacked_bar",
  "stacked_line",
  "scatter",
  "scatter_clustering",
  "radar",
  "funnel",
  "multiple_funnel",
  "treemap",
  "single_value",
  "gauge",
]);
type TranslateFn = (key: string, params?: Record<string, string | number | null | undefined>) => string;
type AssistantResponse = {
  assistantMessage: ChatMessage;
  chartAsset?: ChartAsset;
  preAppended: boolean;
  catalogRefreshWorkspaceId?: string;
};
const activeChatControllers = new Map<string, AbortController>();

export function stopChatResponse(sessionId: string): boolean {
  const controller = activeChatControllers.get(sessionId);
  if (!controller) {
    return false;
  }
  controller.abort();
  activeChatControllers.delete(sessionId);
  return true;
}

async function streamAssistantResponse({
  sessionId,
  content,
  preferredChartType,
  workspaceId,
  signal,
  t,
  responseLocale,
}: {
  sessionId: string;
  content: string;
  preferredChartType?: QueryChartType;
  workspaceId: string;
  signal?: AbortSignal;
  t: TranslateFn;
  responseLocale: string;
}): Promise<AssistantResponse> {
  const messageId = `msg-${generateId()}`;
  const traceStartedAt = Date.now();
  const store = useChatStore.getState();
  store.startTrace(messageId, traceStartedAt);

  // Pre-append placeholder so <AgentTrace> mounts immediately and renders live steps
  const placeholder: ChatMessage = {
    id: messageId,
    sessionId,
    role: "assistant",
    content: "",
    timestamp: new Date().toISOString(),
  };
  store.appendMessage(sessionId, placeholder);
  const removePlaceholder = () => {
    useChatStore.setState((s) => ({
      messagesBySession: {
        ...s.messagesBySession,
        [sessionId]: (s.messagesBySession[sessionId] ?? []).filter((m) => m.id !== messageId),
      },
    }));
  };

  const aiMessage = buildMessageWithChartPreference({ content, preferredChartType });
  const authContext = getActiveAuthContext(DEFAULT_AUTH_CONTEXT);
  const authorizationHeader = await getAuthorizationHeader(API_BASE_URL, authContext);

  let finalText = "";
  let latestSpec: unknown = null;
  let terminalReason: "final" | "error" | "closed" = "closed";
  let planningStepCounter = 0;
  let toolStepCount = 0;

  try {
    const response = await fetch(`${API_BASE_URL}/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authorizationHeader,
      },
      body: JSON.stringify({
        user_id: authContext.userId,
        project_id: authContext.projectId,
        workspace_id: workspaceId,
        role: authContext.role,
        department: authContext.department,
        clearance: authContext.clearance,
        dataset_table: DEFAULT_DATASET_TABLE,
        message: aiMessage,
        preferred_chart_type: preferredChartType ?? null,
        response_locale: responseLocale,
        conversation_id: sessionId,
        request_id: generateId(),
      }),
      signal,
    });

    if (!response.ok || !response.body) {
      useChatStore.getState().endTrace(messageId, "error");
      removePlaceholder();
      throw new Error(`chat_stream_failed_${response.status}`);
    }

    for await (const streamEvent of parseSSEStream(response.body)) {
      const payload = isRecord(streamEvent.data) ? streamEvent.data : {};

      if (streamEvent.event === "planning") {
        const text = String(payload.text ?? "");
        useChatStore.getState().pushTraceStep(messageId, {
          kind: "planning",
          id: `planning-${planningStepCounter++}`,
          text,
          startedAt: Date.now(),
        });
        continue;
      }

      if (streamEvent.event === "tool_use") {
        const stepId = String(payload.step_id ?? `tool-${toolStepCount}`);
        const startedAt = typeof payload.started_at === "number" ? (payload.started_at as number) * 1000 : Date.now();
        const tool = String(payload.tool_name ?? "unknown");
        const args = isRecord(payload.arguments) ? payload.arguments : {};
        toolStepCount++;
        useChatStore.getState().pushTraceStep(messageId, {
          kind: "tool",
          id: stepId,
          tool,
          args,
          startedAt,
          status: "running",
        });
        continue;
      }

      if (streamEvent.event === "tool_result") {
        const stepId = String(payload.step_id ?? "");
        const completedAt = typeof payload.completed_at === "number" ? (payload.completed_at as number) * 1000 : Date.now();
        const startedAt = typeof payload.started_at === "number" ? (payload.started_at as number) * 1000 : undefined;
        const status = payload.status === "error" ? "error" : "ok";
        const result = payload.result;
        const resultPreview = computeResultPreview(result);
        const patch: Record<string, unknown> = { completedAt, status, result, resultPreview };
        if (startedAt !== undefined) {
          patch.startedAt = startedAt;
        }
        useChatStore.getState().patchTraceStep(messageId, stepId, patch as Parameters<typeof store.patchTraceStep>[2]);
        continue;
      }

      if (streamEvent.event === "error") {
        if (!finalText) {
          finalText = String(payload.message ?? t("chat.requestFailed"));
        }
        useChatStore.getState().pushTraceStep(messageId, {
          kind: "error",
          id: `error-${Date.now()}`,
          message: String(payload.message ?? ""),
          code: payload.code ? String(payload.code) : undefined,
          at: Date.now(),
        });
        terminalReason = "error";
        continue;
      }

      if (streamEvent.event === "spec") {
        latestSpec = payload.spec ?? null;
        continue;
      }

      if (streamEvent.event === "final") {
        finalText = String(payload.text ?? finalText);
        terminalReason = "final";
        continue;
      }
    }
  } catch (error) {
    if (isAbortError(error)) {
      useChatStore.getState().endTrace(messageId, "closed");
      return {
        assistantMessage: buildStoppedAssistantMessage({ sessionId, messageId, t }),
        chartAsset: undefined,
        preAppended: true,
      };
    }
    useChatStore.getState().endTrace(messageId, "error");
    removePlaceholder();
    throw error;
  }

  useChatStore.getState().endTrace(messageId, terminalReason);

  const trace = useChatStore.getState().traceByMessageId[messageId];
  const traceSteps = trace?.steps ?? [];
  const toolCallCount = traceSteps.filter((s) => s.kind === "tool").length;
  const durationMs = trace ? (trace.endedAt ?? Date.now()) - trace.startedAt : 0;
  const traceStatus: "ok" | "error" | "incomplete" =
    terminalReason === "final" ? "ok" : terminalReason === "error" ? "error" : "incomplete";

  const chartAsset = toChartAsset(latestSpec, {
    sessionId,
    prompt: content,
  });
  const fallbackText = chartAsset
    ? t("chat.generatedChart", { title: chartAsset.title })
    : t("chat.completed");
  const assistantMessage: ChatMessage = {
    id: messageId,
    sessionId,
    role: "assistant",
    content: finalText || fallbackText,
    chartAsset: chartAsset
      ? {
          assetId: chartAsset.id,
          title: chartAsset.title,
          chartType: chartAsset.chartType,
        }
      : undefined,
    timestamp: new Date().toISOString(),
    traceSummary:
      traceSteps.length > 0
        ? { stepCount: toolCallCount, durationMs, status: traceStatus }
        : undefined,
  };
  return { assistantMessage, chartAsset: chartAsset ?? undefined, preAppended: true };
}

function computeResultPreview(result: unknown): string {
  if (Array.isArray(result)) {
    return `${result.length} rows`;
  }
  if (isRecord(result)) {
    const rows = result.rows;
    if (Array.isArray(rows)) {
      return `${rows.length} rows`;
    }
  }
  const text = typeof result === "string" ? result : JSON.stringify(result) ?? "";
  return text.length > 80 ? text.slice(0, 80) + "…" : text;
}

function buildMessageWithChartPreference({
  content,
  preferredChartType,
}: {
  content: string;
  preferredChartType?: QueryChartType;
}): string {
  if (!preferredChartType) {
    return content;
  }
  return [
    content,
    "",
    "[Chart type selection]",
    `chart_type: ${preferredChartType}`,
    `Use this exact chart_type in the final JSON answer unless the query returns no rows.`,
  ].join("\n");
}

async function consumeIngestionStreamIntoTrace(
  stream: AsyncGenerator<IngestionSSEEvent>,
  messageId: string,
): Promise<{ decisionPayload: Record<string, unknown> | null; hasError: boolean; errorMessage: string | null }> {
  const store = useChatStore.getState();
  let planningCount = 0;
  let toolCount = 0;
  let decisionPayload: Record<string, unknown> | null = null;
  let hasError = false;
  let errorMessage: string | null = null;

  for await (const event of stream) {
    const payload = isRecord(event.data) ? event.data : {};

    if (event.event === "planning") {
      const text = String(payload.text ?? "");
      if (text) {
        store.pushTraceStep(messageId, {
          kind: "planning",
          id: `planning-${planningCount++}`,
          text,
          startedAt: Date.now(),
        });
      }
    } else if (event.event === "tool_use") {
      const stepId = String(payload.step_id ?? `tool-${toolCount++}`);
      const startedAt = typeof payload.started_at === "number" ? (payload.started_at as number) * 1000 : Date.now();
      store.pushTraceStep(messageId, {
        kind: "tool",
        id: stepId,
        tool: String(payload.tool_name ?? ""),
        args: isRecord(payload.arguments) ? payload.arguments : {},
        startedAt,
        status: "running",
      });
    } else if (event.event === "tool_result") {
      const stepId = String(payload.step_id ?? "");
      const completedAt = typeof payload.completed_at === "number" ? (payload.completed_at as number) * 1000 : Date.now();
      const startedAt = typeof payload.started_at === "number" ? (payload.started_at as number) * 1000 : undefined;
      const status = payload.status === "error" ? "error" : "ok";
      const result = payload.result;
      const patch: Record<string, unknown> = { completedAt, status, result, resultPreview: computeResultPreview(result) };
      if (startedAt !== undefined) patch.startedAt = startedAt;
      store.patchTraceStep(messageId, stepId, patch as Parameters<typeof store.patchTraceStep>[2]);
    } else if (event.event === "decision") {
      decisionPayload = payload;
    } else if (event.event === "error") {
      hasError = true;
      errorMessage = String(payload.message ?? "") || errorMessage;
      store.pushTraceStep(messageId, {
        kind: "error",
        id: `error-${Date.now()}`,
        message: String(payload.message ?? ""),
        code: payload.code ? String(payload.code) : undefined,
        at: Date.now(),
      });
    }
  }

  return { decisionPayload, hasError, errorMessage };
}

async function runIngestionConversationResponse({
  sessionId,
  workspaceId,
  content,
  attachment,
  signal,
  t,
}: {
  sessionId: string;
  workspaceId: string;
  content: string;
  attachment: File;
  signal?: AbortSignal;
  t: TranslateFn;
}): Promise<AssistantResponse> {
  const messageId = `msg-${generateId()}`;
  const traceStartedAt = Date.now();
  const store = useChatStore.getState();
  store.startTrace(messageId, traceStartedAt);

  const placeholder: ChatMessage = {
    id: messageId,
    sessionId,
    role: "assistant",
    content: "",
    timestamp: new Date().toISOString(),
  };
  store.appendMessage(sessionId, placeholder);

  const removePlaceholder = () => {
    useChatStore.setState((s) => ({
      messagesBySession: {
        ...s.messagesBySession,
        [sessionId]: (s.messagesBySession[sessionId] ?? []).filter((m) => m.id !== messageId),
      },
    }));
  };

  let upload: IngestionUploadResult;
  try {
    upload = await createIngestionUpload({ workspaceId, file: attachment, signal });
  } catch (err) {
    if (isAbortError(err)) {
      store.endTrace(messageId, "closed");
      return {
        assistantMessage: buildStoppedAssistantMessage({ sessionId, messageId, t }),
        chartAsset: undefined,
        preAppended: true,
      };
    }
    store.endTrace(messageId, "error");
    removePlaceholder();
    throw err;
  }

  let traceHasError = false;

  try {
    const { decisionPayload: planPayload, hasError: planHasError, errorMessage: planErrorMessage } = await consumeIngestionStreamIntoTrace(
      streamIngestionPlan({ workspaceId, jobId: upload.jobId, conversationId: sessionId, message: content, signal }),
      messageId,
    );
    traceHasError = planHasError;
    if (!planPayload) {
      throw new Error(planErrorMessage ?? t("chat.requestFailed"));
    }

    const plan = mapPlanLikePayload(planPayload);

    store.endTrace(messageId, traceHasError ? "error" : "final");

    const trace = useChatStore.getState().traceByMessageId[messageId];
    const traceSteps = trace?.steps ?? [];
    const toolCallCount = traceSteps.filter((s) => s.kind === "tool").length;
    const durationMs = trace ? (trace.endedAt ?? Date.now()) - trace.startedAt : 0;

    if (plan?.status === "awaiting_catalog_setup") {
      useChatStore.getState().setPendingIngestionSetup(sessionId, { upload, plan });
    } else if (plan?.status === "awaiting_user_approval") {
      useChatStore.getState().setPendingIngestionApproval(sessionId, { upload, plan });
    }

    const assistantMessage: ChatMessage = {
      id: messageId,
      sessionId,
      role: "assistant",
      content: buildIngestionSummaryMessage({
        upload,
        plan,
        approvalResult: null,
        executionResult: null,
        t,
      }),
      timestamp: new Date().toISOString(),
      traceSummary:
        traceSteps.length > 0
          ? { stepCount: toolCallCount, durationMs, status: traceHasError ? "error" : "ok" }
          : undefined,
    };
    return {
      assistantMessage,
      chartAsset: undefined,
      preAppended: true,
    };
  } catch (err) {
    if (isAbortError(err)) {
      store.endTrace(messageId, "closed");
      return {
        assistantMessage: buildStoppedAssistantMessage({ sessionId, messageId, t }),
        chartAsset: undefined,
        preAppended: true,
      };
    }
    store.endTrace(messageId, "error");
    removePlaceholder();
    throw err;
  }
}

async function runIngestionRePlanningWithInstruction({
  sessionId,
  workspaceId,
  pending,
  instruction,
  signal,
  t,
}: {
  sessionId: string;
  workspaceId: string;
  pending: PendingIngestionApproval;
  instruction: string;
  signal?: AbortSignal;
  t: TranslateFn;
}): Promise<AssistantResponse> {
  const messageId = `msg-${generateId()}`;
  const traceStartedAt = Date.now();
  const store = useChatStore.getState();
  store.startTrace(messageId, traceStartedAt);

  const placeholder: ChatMessage = {
    id: messageId,
    sessionId,
    role: "assistant",
    content: "",
    timestamp: new Date().toISOString(),
  };
  store.appendMessage(sessionId, placeholder);

  const removePlaceholder = () => {
    useChatStore.setState((s) => ({
      messagesBySession: {
        ...s.messagesBySession,
        [sessionId]: (s.messagesBySession[sessionId] ?? []).filter((m) => m.id !== messageId),
      },
    }));
  };

  let traceHasError = false;
  const upload = pending.upload;

  try {
    const { decisionPayload: planPayload, hasError: planHasError, errorMessage: planErrorMessage } =
      await consumeIngestionStreamIntoTrace(
        streamIngestionPlan({
          workspaceId,
          jobId: upload.jobId,
          conversationId: sessionId,
          message: instruction,
          signal,
        }),
        messageId,
      );
    traceHasError = planHasError;
    if (!planPayload) {
      throw new Error(planErrorMessage ?? t("chat.requestFailed"));
    }

    const plan = mapPlanLikePayload(planPayload);

    store.endTrace(messageId, traceHasError ? "error" : "final");

    const trace = useChatStore.getState().traceByMessageId[messageId];
    const traceSteps = trace?.steps ?? [];
    const toolCallCount = traceSteps.filter((s) => s.kind === "tool").length;
    const durationMs = trace ? (trace.endedAt ?? Date.now()) - trace.startedAt : 0;

    if (plan?.status === "awaiting_catalog_setup") {
      useChatStore.getState().setPendingIngestionSetup(sessionId, { upload, plan });
    } else if (plan?.status === "awaiting_user_approval") {
      useChatStore.getState().setPendingIngestionApproval(sessionId, { upload, plan });
    }

    const assistantMessage: ChatMessage = {
      id: messageId,
      sessionId,
      role: "assistant",
      content: buildIngestionSummaryMessage({
        upload,
        plan,
        approvalResult: null,
        executionResult: null,
        t,
      }),
      timestamp: new Date().toISOString(),
      traceSummary:
        traceSteps.length > 0
          ? { stepCount: toolCallCount, durationMs, status: traceHasError ? "error" : "ok" }
          : undefined,
    };
    return {
      assistantMessage,
      chartAsset: undefined,
      preAppended: true,
    };
  } catch (err) {
    if (isAbortError(err)) {
      store.endTrace(messageId, "closed");
      return {
        assistantMessage: buildStoppedAssistantMessage({ sessionId, messageId, t }),
        chartAsset: undefined,
        preAppended: true,
      };
    }
    store.endTrace(messageId, "error");
    removePlaceholder();
    throw err;
  }
}

async function runIngestionApprovalResponse({
  sessionId,
  pending,
  approvedAction,
  signal,
  t,
}: {
  sessionId: string;
  pending: PendingIngestionApproval;
  approvedAction: IngestionProposalAction;
  signal?: AbortSignal;
  t: TranslateFn;
}): Promise<AssistantResponse> {
  const messageId = `msg-${generateId()}`;
  const traceStartedAt = Date.now();
  const store = useChatStore.getState();
  store.startTrace(messageId, traceStartedAt);

  const placeholder: ChatMessage = {
    id: messageId,
    sessionId,
    role: "assistant",
    content: "",
    timestamp: new Date().toISOString(),
  };
  store.appendMessage(sessionId, placeholder);

  const removePlaceholder = () => {
    useChatStore.setState((s) => ({
      messagesBySession: {
        ...s.messagesBySession,
        [sessionId]: (s.messagesBySession[sessionId] ?? []).filter((m) => m.id !== messageId),
      },
    }));
  };

  const plan = pending.plan;
  let approvalResult: IngestionApprovalResult;
  try {
    approvalResult = await approveIngestionProposal({
      workspaceId: plan.workspaceId,
      jobId: plan.jobId,
      proposalId: plan.proposalId,
      approvedAction,
      userOverrides:
        approvedAction === "time_partitioned_new_table"
          ? { timeGrain: plan.proposal.timeGrain }
          : undefined,
      signal,
    });
  } catch (err) {
    if (isAbortError(err)) {
      store.endTrace(messageId, "closed");
      return {
        assistantMessage: buildStoppedAssistantMessage({ sessionId, messageId, t }),
        chartAsset: undefined,
        preAppended: true,
      };
    }
    store.endTrace(messageId, "error");
    removePlaceholder();
    throw err;
  }

  // Advance the multi-proposal queue: drop the proposal we just acted on, and
  // either set the next proposal as pending or clear if this was the last one.
  // Cancel advances too — the user can cancel each proposal individually if
  // they want to bail on the whole plan.
  const remainingAfterCurrent = plan.proposals.slice(1);
  if (remainingAfterCurrent.length === 0) {
    useChatStore.getState().clearPendingIngestionApproval(sessionId);
  } else {
    const nextHead = remainingAfterCurrent[0];
    const nextPlan: IngestionPlanAwaitingApproval = {
      ...plan,
      proposalId: nextHead.proposalId,
      proposal: nextHead.proposal,
      proposals: remainingAfterCurrent,
    };
    useChatStore.getState().setPendingIngestionApproval(sessionId, { upload: pending.upload, plan: nextPlan });
  }

  let executionResult: IngestionExecuteResult | null = null;
  let traceHasError = false;

  try {
    if (approvalResult.status === "approved") {
      const { decisionPayload, hasError } = await consumeIngestionStreamIntoTrace(
        streamIngestionExecute({
          workspaceId: plan.workspaceId,
          jobId: plan.jobId,
          proposalId: plan.proposalId,
          signal,
        }),
        messageId,
      );
      traceHasError = hasError;
      if (decisionPayload) {
        const receipt = isRecord(decisionPayload.receipt) ? decisionPayload.receipt : {};
        executionResult = {
          status: "succeeded",
          workspaceId: String(decisionPayload.workspace_id ?? ""),
          jobId: String(decisionPayload.job_id ?? ""),
          proposalId: String(decisionPayload.proposal_id ?? ""),
          executionId: String(decisionPayload.execution_id ?? ""),
          receipt: {
            success: Boolean(receipt.success),
            workspaceId: String(receipt.workspace_id ?? ""),
            jobId: String(receipt.job_id ?? ""),
            targetTable: String(receipt.target_table ?? ""),
            executionMode: String(receipt.execution_mode ?? "update_existing") as import("@/types/ingestion").IngestionProposalAction,
            insertedRows: Number(receipt.inserted_rows ?? 0),
            updatedRows: Number(receipt.updated_rows ?? 0),
            affectedRows: Number(receipt.affected_rows ?? 0),
            rowsAfter: Number(receipt.rows_after ?? 0),
            duckdbPath: String(receipt.duckdb_path ?? ""),
            finishedAt: String(receipt.finished_at ?? ""),
          },
        };
      }
    }

    store.endTrace(messageId, traceHasError ? "error" : "final");

    const trace = useChatStore.getState().traceByMessageId[messageId];
    const traceSteps = trace?.steps ?? [];
    const toolCallCount = traceSteps.filter((s) => s.kind === "tool").length;
    const durationMs = trace ? (trace.endedAt ?? Date.now()) - trace.startedAt : 0;

    const assistantMessage: ChatMessage = {
      id: messageId,
      sessionId,
      role: "assistant",
      content: buildIngestionSummaryMessage({
        upload: pending.upload,
        plan,
        approvalResult,
        executionResult,
        t,
      }),
      timestamp: new Date().toISOString(),
      traceSummary:
        traceSteps.length > 0
          ? { stepCount: toolCallCount, durationMs, status: traceHasError ? "error" : "ok" }
          : undefined,
    };
    return {
      assistantMessage,
      chartAsset: undefined,
      preAppended: true,
      catalogRefreshWorkspaceId: executionResult?.receipt.success ? plan.workspaceId : undefined,
    };
  } catch (err) {
    if (isAbortError(err)) {
      store.endTrace(messageId, "closed");
      return {
        assistantMessage: buildStoppedAssistantMessage({ sessionId, messageId, t }),
        chartAsset: undefined,
        preAppended: true,
      };
    }
    store.endTrace(messageId, "error");
    removePlaceholder();
    throw err;
  }
}

async function runIngestionSetupConfirmResponse({
  sessionId,
  workspaceId,
  pending,
  seed,
  signal,
  t,
}: {
  sessionId: string;
  workspaceId: string;
  pending: PendingIngestionSetup;
  seed: IngestionCatalogSetupSeed;
  signal?: AbortSignal;
  t: TranslateFn;
}): Promise<AssistantResponse> {
  const messageId = `msg-${generateId()}`;
  const traceStartedAt = Date.now();
  const store = useChatStore.getState();
  store.startTrace(messageId, traceStartedAt);

  const placeholder: ChatMessage = {
    id: messageId,
    sessionId,
    role: "assistant",
    content: "",
    timestamp: new Date().toISOString(),
  };
  store.appendMessage(sessionId, placeholder);

  const removePlaceholder = () => {
    useChatStore.setState((s) => ({
      messagesBySession: {
        ...s.messagesBySession,
        [sessionId]: (s.messagesBySession[sessionId] ?? []).filter((m) => m.id !== messageId),
      },
    }));
  };

  let traceHasError = false;

  try {
    const { decisionPayload, hasError } = await consumeIngestionStreamIntoTrace(
      streamIngestionSetupConfirm({
        workspaceId,
        jobId: pending.upload.jobId,
        conversationId: sessionId,
        message: undefined,
        setup: seed,
        signal,
      }),
      messageId,
    );
    traceHasError = hasError;

    useChatStore.getState().clearPendingIngestionSetup(sessionId);

    const plan = decisionPayload ? mapPlanLikePayload(decisionPayload) : null;

    store.endTrace(messageId, traceHasError ? "error" : "final");

    const trace = useChatStore.getState().traceByMessageId[messageId];
    const traceSteps = trace?.steps ?? [];
    const toolCallCount = traceSteps.filter((s) => s.kind === "tool").length;
    const durationMs = trace ? (trace.endedAt ?? Date.now()) - trace.startedAt : 0;

    if (plan?.status === "awaiting_catalog_setup") {
      useChatStore.getState().setPendingIngestionSetup(sessionId, { upload: pending.upload, plan });
    } else if (plan?.status === "awaiting_user_approval") {
      useChatStore.getState().setPendingIngestionApproval(sessionId, { upload: pending.upload, plan });
    }

    if (!plan) {
      const errorMessage: ChatMessage = {
        id: messageId,
        sessionId,
        role: "assistant",
        content: t("chat.requestFailed"),
        timestamp: new Date().toISOString(),
      };
      return { assistantMessage: errorMessage, chartAsset: undefined, preAppended: true };
    }

    const assistantMessage: ChatMessage = {
      id: messageId,
      sessionId,
      role: "assistant",
      content: buildIngestionSummaryMessage({
        upload: pending.upload,
        plan,
        approvalResult: null,
        executionResult: null,
        t,
      }),
      timestamp: new Date().toISOString(),
      traceSummary:
        traceSteps.length > 0
          ? { stepCount: toolCallCount, durationMs, status: traceHasError ? "error" : "ok" }
          : undefined,
    };
    return {
      assistantMessage,
      chartAsset: undefined,
      preAppended: true,
      catalogRefreshWorkspaceId:
        !traceHasError && plan.status !== "awaiting_catalog_setup" ? workspaceId : undefined,
    };
  } catch (err) {
    if (isAbortError(err)) {
      store.endTrace(messageId, "closed");
      return {
        assistantMessage: buildStoppedAssistantMessage({ sessionId, messageId, t }),
        chartAsset: undefined,
        preAppended: true,
      };
    }
    store.endTrace(messageId, "error");
    removePlaceholder();
    throw err;
  }
}

export function useConfirmIngestionSetup() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const appendMessage = useChatStore((s) => s.appendMessage);
  const touchSession = useChatStore((s) => s.touchSession);
  const setSessionSending = useUIStore((s) => s.setSessionSending);

  return useMutation({
    mutationFn: async ({
      sessionId,
      seed,
    }: {
      sessionId: string;
      seed: IngestionCatalogSetupSeed;
    }) => {
      const workspaceId = getActiveWorkspaceIdOrThrow(t);
      assertSessionInCurrentScope(sessionId, t);
      const pending = useChatStore.getState().pendingIngestionSetupBySession[sessionId];
      if (!pending) {
        throw new Error("No pending setup found");
      }
      const abortController = new AbortController();
      activeChatControllers.set(sessionId, abortController);
      try {
        return await runIngestionSetupConfirmResponse({
          sessionId,
          workspaceId,
          pending,
          seed,
          signal: abortController.signal,
          t,
        });
      } finally {
        if (activeChatControllers.get(sessionId) === abortController) {
          activeChatControllers.delete(sessionId);
        }
        setSessionSending(sessionId, false);
      }
    },
    onMutate: ({ sessionId }) => {
      try {
        getActiveWorkspaceIdOrThrow(t);
        assertSessionInCurrentScope(sessionId, t);
      } catch {
        return { sessionId, optimistic: false };
      }
      setSessionSending(sessionId, true);
    },
    onSuccess: ({ assistantMessage, chartAsset, preAppended, catalogRefreshWorkspaceId }, { sessionId }) => {
      if (preAppended) {
        useChatStore.getState().replaceMessage(sessionId, assistantMessage.id, assistantMessage);
      } else {
        appendMessage(sessionId, assistantMessage);
      }
      touchSession(sessionId, {
        lastMessage: assistantMessage.content,
        messageDelta: 1,
      });
      const workspaceId = useWorkspaceStore.getState().activeWorkspaceId;
      queryClient.invalidateQueries({ queryKey: chatSessionsQueryKey(workspaceId) });
      queryClient.invalidateQueries({ queryKey: chatMessagesQueryKey(workspaceId, sessionId) });
      if (catalogRefreshWorkspaceId) {
        void refreshWorkspaceCatalog(queryClient, catalogRefreshWorkspaceId);
      }
    },
    onError: (error, { sessionId }) => {
      if (!useChatStore.getState().hasSessionInCurrentScope(sessionId)) {
        return;
      }
      const errorMessage: ChatMessage = {
        id: `msg-${generateId()}`,
        sessionId,
        role: "assistant",
        content: error instanceof Error ? error.message : t("chat.requestFailed"),
        timestamp: new Date().toISOString(),
      };
      appendMessage(sessionId, errorMessage);
      touchSession(sessionId, {
        lastMessage: errorMessage.content,
        messageDelta: 1,
      });
      const workspaceId = useWorkspaceStore.getState().activeWorkspaceId;
      queryClient.invalidateQueries({ queryKey: chatSessionsQueryKey(workspaceId) });
      queryClient.invalidateQueries({ queryKey: chatMessagesQueryKey(workspaceId, sessionId) });
    },
    onSettled: (_data, _error, { sessionId }) => {
      setSessionSending(sessionId, false);
    },
  });
}

function createLocalSession(title?: string): ChatSession {
  const now = new Date().toISOString();
  return {
    id: `session-${generateId()}`,
    title: normalizeSessionTitle(title ?? "", DEFAULT_SESSION_TITLE),
    createdAt: now,
    updatedAt: now,
    messageCount: 0,
  };
}

function createUserMessage(sessionId: string, content: string): ChatMessage {
  return {
    id: `msg-${generateId()}`,
    sessionId,
    role: "user",
    content,
    timestamp: new Date().toISOString(),
  };
}

function buildStoppedAssistantMessage({
  sessionId,
  messageId,
  t,
}: {
  sessionId: string;
  messageId: string;
  t: TranslateFn;
}): ChatMessage {
  const trace = useChatStore.getState().traceByMessageId[messageId];
  const traceSteps = trace?.steps ?? [];
  const toolCallCount = traceSteps.filter((s) => s.kind === "tool").length;
  const durationMs = trace ? (trace.endedAt ?? Date.now()) - trace.startedAt : 0;
  return {
    id: messageId,
    sessionId,
    role: "assistant",
    content: t("chat.stopped"),
    timestamp: new Date().toISOString(),
    traceSummary:
      traceSteps.length > 0
        ? { stepCount: toolCallCount, durationMs, status: "incomplete" }
        : undefined,
  };
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

function formatUserMessageContent({
  content,
  attachmentName,
  t,
}: {
  content: string;
  attachmentName?: string;
  t: TranslateFn;
}): string {
  const trimmed = content.trim();
  if (!attachmentName) {
    return trimmed;
  }
  if (!trimmed) {
    return t("chat.userAttachedFileOnly", { fileName: attachmentName });
  }
  return t("chat.userAttachedFileWithPrompt", {
    fileName: attachmentName,
    prompt: trimmed,
  });
}

function buildIngestionSummaryMessage({
  upload,
  plan,
  approvalResult,
  executionResult,
  t,
}: {
  upload: IngestionUploadResult;
  plan: IngestionPlanResult;
  approvalResult: IngestionApprovalResult | null;
  executionResult: IngestionExecuteResult | null;
  t: TranslateFn;
}): string {
  const parseStats = extractUploadStats(upload);
  const lines: string[] = [
    t("chat.ingestion.summaryTitle"),
    t("chat.ingestion.parsedFile", {
      fileName: upload.fileSummary.fileName,
      sheetCount: parseStats.sheetCount,
      rowCount: parseStats.totalRows,
    }),
    t("chat.ingestion.jobId", { jobId: upload.jobId }),
  ];

  if (plan.status === "awaiting_catalog_setup") {
    lines.push(t("chat.ingestion.setupRequired"));
    return lines.join("\n");
  }

  lines.push(...buildAwaitingApprovalSummary(plan, approvalResult, executionResult, t));
  return lines.join("\n");
}

function buildAwaitingApprovalSummary(
  plan: IngestionPlanAwaitingApproval,
  approvalResult: IngestionApprovalResult | null,
  executionResult: IngestionExecuteResult | null,
  t: TranslateFn
): string[] {
  const actionLabel = toProposalActionLabel({
    action: plan.proposal.recommendedAction,
    timeGrain: plan.proposal.timeGrain,
    t,
  });
  const lines = [
    t("chat.ingestion.recommended", {
      action: actionLabel,
      table: plan.proposal.targetTable ?? t("ingestion.lifecycle.targetNotSet"),
    }),
    t("chat.ingestion.diffPreview", {
      insertCount: plan.proposal.diffPreview.predictedInsertCount,
      updateCount: plan.proposal.diffPreview.predictedUpdateCount,
      conflictCount: plan.proposal.diffPreview.predictedConflictCount,
    }),
  ];

  if (plan.proposal.risks.length > 0) {
    lines.push(
      `${t("chat.ingestion.risksTitle")}\n${plan.proposal.risks
        .slice(0, 3)
        .map((risk, index) => `${index + 1}. ${risk}`)
        .join("\n")}`
    );
  }

  if (approvalResult?.status === "cancelled") {
    lines.push(t("chat.ingestion.autoDecisionCancelled"));
    return lines;
  }

  if (!approvalResult) {
    const options = collectApprovalOptions(plan);
    lines.push(
      t("chat.ingestion.awaitingApprovalQuestion", {
        question: plan.humanApproval.question,
      })
    );
    lines.push(
      t("chat.ingestion.awaitingApprovalOptions", {
        options: formatApprovalActionsForDisplay({
          actions: options,
          timeGrain: plan.proposal.timeGrain,
          t,
        }),
      })
    );
    if (plan.humanApproval.recommendedOption) {
      lines.push(
        t("chat.ingestion.awaitingApprovalRecommended", {
          action: toProposalActionLabel({
            action: plan.humanApproval.recommendedOption,
            timeGrain: plan.proposal.timeGrain,
            t,
          }),
        })
      );
    }
    return lines;
  }

  if (approvalResult?.status === "approved") {
    lines.push(
      t("chat.ingestion.autoApproved", {
        action: toProposalActionLabel({
          action: approvalResult.approvedAction,
          timeGrain: approvalResult.timeGrain,
          t,
        }),
      })
    );
  }
  if (executionResult) {
    lines.push(
      t("chat.ingestion.executionReceipt", {
        targetTable: executionResult.receipt.targetTable,
        insertedRows: executionResult.receipt.insertedRows,
        updatedRows: executionResult.receipt.updatedRows,
      })
    );
    lines.push(
      t("chat.ingestion.executionRows", {
        affectedRows: executionResult.receipt.affectedRows,
        rowsAfter: executionResult.receipt.rowsAfter,
      })
    );
  }
  return lines;
}

function normalizeProposalAction(action: string): IngestionProposalAction | null {
  const normalized = action.trim().toLowerCase();
  if (
    normalized === "update_existing" ||
    normalized === "time_partitioned_new_table" ||
    normalized === "new_table" ||
    normalized === "cancel"
  ) {
    return normalized;
  }
  return null;
}

function collectApprovalOptions(plan: IngestionPlanAwaitingApproval): IngestionProposalAction[] {
  const fromApproval = plan.humanApproval.options
    .map((item) => normalizeProposalAction(item))
    .filter((item): item is IngestionProposalAction => item !== null);
  const fromProposal = plan.proposal.candidateActions
    .map((item) => normalizeProposalAction(item))
    .filter((item): item is IngestionProposalAction => item !== null);
  const merged = fromApproval.length > 0 ? fromApproval : fromProposal;
  if (merged.length === 0) {
    return ["update_existing", "time_partitioned_new_table", "new_table", "cancel"];
  }
  const deduped: IngestionProposalAction[] = [];
  for (const item of merged) {
    if (!deduped.includes(item)) {
      deduped.push(item);
    }
  }
  return deduped;
}

function formatApprovalActionsForDisplay({
  actions,
  timeGrain,
  t,
}: {
  actions: IngestionProposalAction[];
  timeGrain: IngestionTimeGrain;
  t: TranslateFn;
}): string {
  return actions
    .map((action, index) => `${index + 1}) ${action} (${toProposalActionLabel({ action, timeGrain, t })})`)
    .join("  ");
}

function formatPendingApprovalOptions({
  pending,
  t,
}: {
  pending: PendingIngestionApproval;
  t: TranslateFn;
}): string {
  return formatApprovalActionsForDisplay({
    actions: collectApprovalOptions(pending.plan),
    timeGrain: pending.plan.proposal.timeGrain,
    t,
  });
}

function resolvePendingApprovalAction({
  rawInput,
  pending,
}: {
  rawInput: string;
  pending: PendingIngestionApproval;
}): IngestionProposalAction | null {
  const options = collectApprovalOptions(pending.plan);
  if (options.length === 0) {
    return null;
  }
  const normalized = rawInput.trim().toLowerCase();
  if (!normalized) {
    return null;
  }

  const direct = normalizeProposalAction(normalized);
  if (direct && options.includes(direct)) {
    return direct;
  }

  const compact = normalized.replace(/\s+/g, "");
  const aliases: Record<string, IngestionProposalAction> = {
    "updateexisting": "update_existing",
    "更新现有表": "update_existing",
    "更新已有表": "update_existing",
    "timepartitionednewtable": "time_partitioned_new_table",
    "分区新表": "time_partitioned_new_table",
    "按时间分区新建表": "time_partitioned_new_table",
    "newtable": "new_table",
    "创建新表": "new_table",
    "cancel": "cancel",
    "取消": "cancel",
    "recommended": pending.plan.proposal.recommendedAction,
    "推荐": pending.plan.proposal.recommendedAction,
    "建议": pending.plan.proposal.recommendedAction,
  };
  const aliasAction = aliases[compact];
  if (aliasAction && options.includes(aliasAction)) {
    return aliasAction;
  }

  const asIndex = Number.parseInt(compact, 10);
  if (Number.isFinite(asIndex) && asIndex >= 1 && asIndex <= options.length) {
    return options[asIndex - 1] ?? null;
  }

  for (const option of options) {
    if (normalized.includes(option)) {
      return option;
    }
  }
  return null;
}

function toProposalActionLabel({
  action,
  timeGrain,
  t,
}: {
  action: string;
  timeGrain: string;
  t: TranslateFn;
}): string {
  if (action === "update_existing") {
    return t("ingestion.lifecycle.action.updateExisting");
  }
  if (action === "new_table") {
    return t("ingestion.lifecycle.action.newTable");
  }
  if (action === "time_partitioned_new_table") {
    if (timeGrain === "month") {
      return t("ingestion.lifecycle.action.newMonthly");
    }
    if (timeGrain === "quarter") {
      return t("ingestion.lifecycle.action.newQuarterly");
    }
    if (timeGrain === "year") {
      return t("ingestion.lifecycle.action.newYearly");
    }
    return t("ingestion.lifecycle.action.newTable");
  }
  if (action === "cancel") {
    return t("ingestion.lifecycle.action.cancel");
  }
  return action;
}

function extractUploadStats(upload: IngestionUploadResult): { sheetCount: number; totalRows: number } {
  if (!isRecord(upload.sheetSummary)) {
    return { sheetCount: 0, totalRows: 0 };
  }
  const sheets = Array.isArray(upload.sheetSummary.sheets)
    ? upload.sheetSummary.sheets.filter(isRecord)
    : [];
  const normalizedSheetCount = asNumber(upload.sheetSummary.sheet_count);
  const sheetCount = normalizedSheetCount > 0 ? normalizedSheetCount : sheets.length;
  const totalRows = sheets.reduce((sum, sheet) => sum + asNumber(sheet.row_count), 0);
  return { sheetCount, totalRows };
}

function toChartAsset(
  rawSpec: unknown,
  source: { sessionId: string; prompt: string }
): ChartAsset | null {
  if (!isRecord(rawSpec)) {
    return null;
  }

  const chartType = normalizeChartType(rawSpec.chart_type);
  if (chartType === "empty") {
    return null;
  }
  const title = typeof rawSpec.title === "string" && rawSpec.title.trim() ? rawSpec.title : "Chart";
  const echartsOption = resolveEchartsOption(rawSpec);
  if (!echartsOption) {
    return null;
  }

  const spec: ChartSpec = {
    chartType,
    title,
    subtitle: typeof rawSpec.subtitle === "string" ? rawSpec.subtitle : undefined,
    echartsOption,
  };
  const now = new Date().toISOString();
  return {
    id: `asset-${generateId()}`,
    title,
    description: spec.subtitle,
    chartType,
    spec,
    sourceMeta: {
      sessionId: source.sessionId,
      messageId: `msg-${generateId()}`,
      prompt: source.prompt,
      datasetTable: DEFAULT_DATASET_TABLE,
    },
    createdAt: now,
    updatedAt: now,
  };
}

function resolveEchartsOption(rawSpec: Record<string, unknown>): Record<string, unknown> | null {
  const rows = Array.isArray(rawSpec.data) ? rawSpec.data.filter(isRecord) : [];
  const withRawRows = (option: Record<string, unknown>): Record<string, unknown> => {
    if (!rows.length || Array.isArray(option.__rows__)) {
      return option;
    }
    return { ...option, __rows__: rows };
  };
  const config = isRecord(rawSpec.config) ? rawSpec.config : {};
  const option = config.option;
  if (isRecord(option)) {
    return withRawRows(option);
  }

  const title = typeof rawSpec.title === "string" ? rawSpec.title : "Chart";
  const chartType = normalizeChartType(rawSpec.chart_type);
  const configuredYKey = typeof config.yKey === "string" ? config.yKey : null;
  if (chartType === "single_value" || chartType === "gauge") {
    const yKey = configuredYKey ?? inferYKey(rows, null);
    const value = rows.length > 0 && yKey ? asNumber(rows[0]?.[yKey]) : 0;
    const name = configuredYKey ?? yKey ?? "value";
    return withRawRows(
      chartType === "gauge"
        ? buildGaugeFallbackOption({ title, value, name })
        : buildSingleValueFallbackOption({ title, value, name })
    );
  }

  // Table: build a marker option so chart-preview renders an HTML data table.
  if (chartType === "table") {
    const cols = rows.length ? Object.keys(rows[0]) : [];
    return { __table__: true, __columns__: cols, __rows__: rows, __title__: title, series: [] };
  }

  if (!FALLBACK_OPTION_TYPES.has(chartType as KnownChartType)) {
    // Never rewrite unsupported/advanced chart types to a different fallback type.
    return null;
  }

  const xKey = typeof config.xKey === "string" ? config.xKey : inferXKey(rows);
  const yKey = configuredYKey ?? inferYKey(rows, xKey);
  if (!xKey || !yKey) {
    return null;
  }

  const categories = rows.map((row, index) => String(row[xKey] ?? `item-${index + 1}`));
  const values = rows.map((row) => asNumber(row[yKey]));

  if (chartType === "negative_bar") {
    return withRawRows({
      title: { text: title, left: "center" },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      grid: { top: 60, left: "3%", right: "4%", bottom: 20, containLabel: true },
      xAxis: {
        type: "value",
        position: "top",
        splitLine: { lineStyle: { type: "dashed" } },
      },
      yAxis: {
        type: "category",
        axisLine: { show: false },
        axisLabel: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        data: categories,
      },
      series: [
        {
          name: configuredYKey ?? yKey,
          type: "bar",
          stack: "Total",
          label: { show: true, formatter: "{b}" },
          data: values.map((value) => ({
            value,
            itemStyle: { color: value < 0 ? "#c96442" : "#4b7f8c" },
            ...(value < 0 ? { label: { position: "right" } } : {}),
          })),
        },
      ],
    });
  }

  if (chartType === "treemap") {
    const nameKey = typeof config.nameKey === "string" ? config.nameKey : null;
    return withRawRows(buildRichTreemapFallbackOption({ rows, title, xKey, yKey, nameKey }));
  }

  if (chartType === "funnel") {
    return withRawRows({
      title: { text: title, left: "center" },
      tooltip: { trigger: "item" },
      series: [
        {
          type: "funnel",
          left: "10%",
          top: 60,
          bottom: 20,
          width: "80%",
          data: rows.map((row, index) => ({
            name: String(row[xKey] ?? `item-${index + 1}`),
            value: asNumber(row[yKey]),
          })),
        },
      ],
    });
  }

  if (chartType === "multiple_funnel") {
    const data = rows.map((row, index) => ({
      name: String(row[xKey] ?? `item-${index + 1}`),
      value: asNumber(row[yKey]),
    }));
    return withRawRows({
      title: { text: title, left: "left", top: "bottom" },
      tooltip: { trigger: "item", formatter: "{a}<br/>{b}: {c}" },
      legend: { orient: "vertical", left: "left", data: data.map((item) => item.name) },
      series: [
        { name: "Funnel", type: "funnel", width: "40%", height: "45%", left: "5%", top: "50%", data },
        { name: "Pyramid", type: "funnel", width: "40%", height: "45%", left: "5%", top: "5%", sort: "ascending", data },
        {
          name: "Funnel",
          type: "funnel",
          width: "40%",
          height: "45%",
          left: "55%",
          top: "5%",
          label: { position: "left" },
          data,
        },
        {
          name: "Pyramid",
          type: "funnel",
          width: "40%",
          height: "45%",
          left: "55%",
          top: "50%",
          sort: "ascending",
          label: { position: "left" },
          data,
        },
      ],
    });
  }

  if (chartType === "radar") {
    const maxValue = Math.max(1, ...values);
    return withRawRows({
      title: { text: title, left: "center" },
      tooltip: {},
      radar: {
        indicator: categories.map((name) => ({
          name,
          max: Math.ceil(maxValue * 1.2),
        })),
      },
      series: [
        {
          type: "radar",
          data: [{ value: values, name: title }],
        },
      ],
    });
  }

  if (chartType === "pie") {
    return withRawRows({
      title: { text: title, left: "center" },
      tooltip: { trigger: "item" },
      series: [
        {
          type: "pie",
          radius: "65%",
          data: rows.map((row, index) => ({
            name: String(row[xKey] ?? `item-${index + 1}`),
            value: asNumber(row[yKey]),
          })),
        },
      ],
    });
  }

  if (chartType === "scatter") {
    const points = rows.map((row, index) => {
      const xValue = row[xKey];
      if (typeof xValue === "number") {
        return [xValue, asNumber(row[yKey])];
      }
      return [index + 1, asNumber(row[yKey])];
    });
    return withRawRows({
      title: { text: title, left: "center" },
      tooltip: { trigger: "item" },
      xAxis: { type: "value", name: xKey },
      yAxis: { type: "value", name: yKey },
      series: [{ type: "scatter", data: points }],
    });
  }

  if (chartType === "scatter_clustering") {
    return withRawRows(buildScatterClusteringOption({
      rows,
      xKey,
      yKey,
      title,
      labelKey: typeof config.nameKey === "string" ? config.nameKey : null,
    }));
  }

  if (chartType === "grouped_bar" || chartType === "stacked_bar") {
    const seriesKey = typeof config.seriesKey === "string" ? config.seriesKey : null;
    if (!seriesKey) {
      const horizontalAxis = chartType === "grouped_bar";
      return withRawRows({
        title: { text: title, left: "center" },
        tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
        grid: { left: "3%", right: "4%", bottom: "3%", containLabel: true },
        xAxis: horizontalAxis ? { type: "value" } : { type: "category", data: categories },
        yAxis: horizontalAxis ? { type: "category", data: categories } : { type: "value" },
        series: [{ type: "bar", ...(chartType === "stacked_bar" ? { stack: "total" } : {}), data: values }],
      });
    }

    const categoryOrder: string[] = [];
    const categorySet = new Set<string>();
    const seriesOrder: string[] = [];
    const seriesSet = new Set<string>();
    const matrix = new Map<string, Map<string, number>>();

    for (const row of rows) {
      const category = String(row[xKey] ?? "");
      const seriesName = String(row[seriesKey] ?? "");
      if (!categorySet.has(category)) {
        categorySet.add(category);
        categoryOrder.push(category);
      }
      if (!seriesSet.has(seriesName)) {
        seriesSet.add(seriesName);
        seriesOrder.push(seriesName);
      }
      const rowMap = matrix.get(seriesName) ?? new Map<string, number>();
      rowMap.set(category, asNumber(row[yKey]));
      matrix.set(seriesName, rowMap);
    }

    return withRawRows({
      title: { text: title, left: "center" },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      legend: { top: 28 },
      grid: { left: "3%", right: "4%", bottom: "3%", containLabel: true },
      xAxis: chartType === "grouped_bar" ? { type: "value" } : { type: "category", data: categoryOrder },
      yAxis: chartType === "grouped_bar" ? { type: "category", data: categoryOrder } : { type: "value" },
      series: seriesOrder.map((seriesName) => ({
        type: "bar",
        name: seriesName,
        ...(chartType === "stacked_bar" ? { stack: "total" } : {}),
        data: categoryOrder.map((category) => matrix.get(seriesName)?.get(category) ?? 0),
      })),
    });
  }

  const seriesType = chartType === "line" || chartType === "area" ? "line" : "bar";
  return withRawRows({
    title: { text: title, left: "center" },
    tooltip: { trigger: "axis" },
    grid: { left: "3%", right: "4%", bottom: "3%", containLabel: true },
    xAxis: { type: "category", data: categories },
    yAxis: { type: "value" },
    series: [
      {
        type: seriesType,
        data: values,
        smooth: chartType === "line" || chartType === "area",
        ...(chartType === "area" ? { areaStyle: {} } : {}),
      },
    ],
  });
}

function inferXKey(rows: Array<Record<string, unknown>>): string | null {
  if (!rows.length) {
    return null;
  }
  const firstRow = rows[0];
  const keys = Object.keys(firstRow);
  if (!keys.length) {
    return null;
  }
  if (keys.includes("label")) {
    return "label";
  }
  const stringKey = keys.find((key) => typeof firstRow[key] === "string");
  return stringKey ?? keys[0];
}

function inferYKey(rows: Array<Record<string, unknown>>, xKey: string | null): string | null {
  if (!rows.length) {
    return null;
  }
  const firstRow = rows[0];
  const keys = Object.keys(firstRow);
  const numberKey = keys.find((key) => key !== xKey && typeof firstRow[key] === "number");
  if (numberKey) {
    return numberKey;
  }
  if (keys.includes("metric_value")) {
    return "metric_value";
  }
  return keys.find((key) => key !== xKey) ?? null;
}

function normalizeChartType(rawChartType: unknown): ChartType {
  const normalized = String(rawChartType ?? "bar").trim();
  if (!normalized) {
    return "bar";
  }

  if (SUPPORTED_CHART_TYPES.has(normalized as KnownChartType)) {
    return normalized as KnownChartType;
  }

  const lowered = normalized.toLowerCase();
  const canonical = SUPPORTED_CHART_TYPES_BY_LOWER.get(lowered);
  if (canonical) {
    return canonical;
  }

  const aliased = CHART_TYPE_ALIASES[lowered];
  if (aliased) {
    return aliased;
  }

  return normalized as ChartType;
}

function asNumber(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return 0;
}

function buildScatterClusteringOption({
  rows,
  xKey,
  yKey,
  title,
  labelKey,
}: {
  rows: Array<Record<string, unknown>>;
  xKey: string;
  yKey: string;
  title: string;
  labelKey: string | null;
}): Record<string, unknown> {
  const points = rows.map((row, index) => [
    asNumber(row[xKey]),
    asNumber(row[yKey]),
    labelKey ? String(row[labelKey] ?? `item-${index + 1}`) : `item-${index + 1}`,
  ]);
  const clusterCount = Math.min(6, Math.max(2, Math.round(Math.sqrt(Math.max(points.length, 2)))));
  const clusterDimension = 3;
  const colors = ["#37A2DA", "#e06343", "#37a354", "#b55dba", "#b5bd48", "#8378EA"];

  return {
    __requiresEchartsStat__: { transforms: ["clustering"] },
    title: { text: title, left: "center" },
    dataset: [
      { dimensions: [xKey, yKey, "label"], source: points },
      {
        transform: {
          type: "ecStat:clustering",
          config: {
            clusterCount,
            dimensions: [0, 1],
            outputType: "single",
            outputClusterIndexDimension: { index: clusterDimension, name: "cluster" },
            outputCentroidDimensions: [
              { index: 4, name: "centroid_x" },
              { index: 5, name: "centroid_y" },
            ],
          },
        },
      },
    ],
    tooltip: { position: "top" },
    visualMap: {
      type: "piecewise",
      top: "middle",
      min: 0,
      max: clusterCount,
      left: 10,
      splitNumber: clusterCount,
      dimension: clusterDimension,
      pieces: Array.from({ length: clusterCount }, (_, index) => ({
        value: index,
        label: `cluster ${index}`,
        color: colors[index % colors.length],
      })),
    },
    grid: { left: 120, right: 24, top: 56, bottom: 40 },
    xAxis: { type: "value", name: xKey },
    yAxis: { type: "value", name: yKey },
    series: [
      {
        type: "scatter",
        datasetIndex: 1,
        encode: { x: 0, y: 1, tooltip: [2, 0, 1, clusterDimension], itemName: 2 },
        symbolSize: 15,
        itemStyle: { borderColor: "#555" },
      },
    ],
  };
}
