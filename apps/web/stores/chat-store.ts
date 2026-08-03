import { create } from "zustand";
import { normalizeSessionTitle } from "@/lib/chat/session-title";
import type { ChatSession, ChatMessage, MultiChartConfirmation } from "@/types/chat";
import type { MessageTrace, TraceStep } from "@/types/trace";
import type { IngestionPlanAwaitingApproval, IngestionPlanAwaitingSetup, IngestionUploadResult } from "@/types/ingestion";
import {
  chatStorageKeyForWorkspace,
  chatStorageKeyForUser,
  legacyChatMigrationStorageKeyForUser,
  traceStorageKeyForWorkspace,
  safeLoadFromStorage,
  safeSaveToStorage,
} from "@/lib/chat/session-storage";

export type PendingIngestionApproval = {
  upload: IngestionUploadResult;
  plan: IngestionPlanAwaitingApproval;
};

export type PendingIngestionSetup = {
  upload: IngestionUploadResult;
  plan: IngestionPlanAwaitingSetup;
};

type ChatState = {
  sessions: ChatSession[];
  activeSessionId: string | null;
  messagesBySession: Record<string, ChatMessage[]>;
  pendingIngestionBySession: Record<string, PendingIngestionApproval | undefined>;
  pendingIngestionSetupBySession: Record<string, PendingIngestionSetup | undefined>;
  pendingMultiChartBySession: Record<string, MultiChartConfirmation | undefined>;
  /**
   * Agent (dashboard-building) mode, per conversation. It is a sticky mode, not
   * a per-message option: once the user flips it on in a conversation it stays
   * on for every following turn there — and only there — until they flip it off.
   * Persisted with the rest of the chat state so a reload keeps the mode.
   */
  agentModeBySession: Record<string, boolean>;
  isComposing: boolean;
  composerText: string;
  /**
   * Single pending workbook for the composer. Lives in the store (not in
   * `ChatInput`) so the panel-wide drag-and-drop zone and the composer chip
   * stay in sync. Never persisted — a `File` handle is session-scoped.
   */
  composerAttachment: File | null;
  traceByMessageId: Record<string, MessageTrace>;

  setSessions: (sessions: ChatSession[]) => void;
  addSession: (session: ChatSession) => void;
  removeSession: (sessionId: string) => void;
  setActiveSession: (sessionId: string | null) => void;
  setMessages: (sessionId: string, messages: ChatMessage[]) => void;
  appendMessage: (sessionId: string, message: ChatMessage) => void;
  replaceMessage: (sessionId: string, messageId: string, message: ChatMessage) => void;
  resetConversation: (sessionId: string) => void;
  setPendingIngestionApproval: (
    sessionId: string,
    pending: PendingIngestionApproval | null
  ) => void;
  clearPendingIngestionApproval: (sessionId: string) => void;
  setPendingIngestionSetup: (
    sessionId: string,
    pending: PendingIngestionSetup | null
  ) => void;
  clearPendingIngestionSetup: (sessionId: string) => void;
  setPendingMultiChartConfirmation: (
    sessionId: string,
    pending: MultiChartConfirmation | null
  ) => void;
  clearPendingMultiChartConfirmation: (sessionId: string) => void;
  setAgentMode: (sessionId: string, enabled: boolean) => void;
  touchSession: (
    sessionId: string,
    updates: { lastMessage?: string; messageDelta?: number; title?: string }
  ) => void;
  renameSession: (sessionId: string, title: string) => void;
  setComposerText: (text: string) => void;
  setComposerAttachment: (file: File | null) => void;
  setIsComposing: (value: boolean) => void;

  startTrace: (messageId: string, startedAt: number) => void;
  pushTraceStep: (messageId: string, step: TraceStep) => void;
  patchTraceStep: (messageId: string, stepId: string, patch: Partial<Omit<TraceStep, "kind" | "id">>) => void;
  endTrace: (messageId: string, reason: "final" | "error" | "closed") => void;
  setTraceState: (messageId: string, state: MessageTrace["state"]) => void;

  getActiveMessages: () => ChatMessage[];
  hasSessionInCurrentScope: (sessionId: string) => boolean;
  getScopeWorkspaceId: () => string | null;
  initForWorkspace: (userId: string, workspaceId: string | null) => void;
  initForUser: (userId: string) => void;
  clearForUser: () => void;
};

type PersistedChatState = {
  version: 1 | 2;
  sessions: ChatSession[];
  activeSessionId: string | null;
  messagesBySession: Record<string, ChatMessage[]>;
  // Added after v2 shipped; absent in states written by older builds, so it is
  // optional rather than a version bump (a missing map just means "all off").
  agentModeBySession?: Record<string, boolean>;
};

type LegacyMigrationMarker = {
  version: 1;
  consideredAt: string;
  workspaceId: string;
};

// Tracks the active scope at module level, not in Zustand state to avoid re-renders.
let _currentUserId: string | null = null;
let _currentWorkspaceId: string | null = null;
let _initializedScopeKey: string | null = null;

function normalizeSession(session: ChatSession): ChatSession {
  return {
    ...session,
    title: normalizeSessionTitle(session.title),
  };
}

function normalizeSessions(sessions: ChatSession[]): ChatSession[] {
  return sessions.map(normalizeSession);
}

function stripResultFromTrace(trace: MessageTrace): MessageTrace {
  return {
    ...trace,
    state: trace.state === "live" ? "collapsed" : trace.state,
    steps: trace.steps.map((step) => {
      if (step.kind !== "tool") return step;
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { result: _dropped, ...rest } = step;
      return rest as typeof step;
    }),
  };
}

function normalizePersistedChatState(state: Partial<PersistedChatState> | null): PersistedChatState | null {
  if (!state || !Array.isArray(state.sessions)) {
    return null;
  }

  const sessions = normalizeSessions(state.sessions);
  const messagesBySession = isMessageMap(state.messagesBySession) ? state.messagesBySession : {};
  const sessionIds = new Set(sessions.map((session) => session.id));
  const activeSessionId =
    typeof state.activeSessionId === "string" && sessionIds.has(state.activeSessionId)
      ? state.activeSessionId
      : sessions[0]?.id ?? null;

  return {
    version: 2,
    sessions,
    activeSessionId,
    messagesBySession: Object.fromEntries(
      Object.entries(messagesBySession).filter(([sessionId]) => sessionIds.has(sessionId))
    ),
    agentModeBySession: normalizeAgentModeMap(state.agentModeBySession, sessionIds),
  };
}

function normalizeAgentModeMap(
  value: unknown,
  sessionIds: Set<string>
): Record<string, boolean> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).filter(
      ([sessionId, enabled]) => sessionIds.has(sessionId) && enabled === true
    )
  ) as Record<string, boolean>;
}

function hasLegacyMigrationMarker(userId: string): boolean {
  const marker = safeLoadFromStorage<Partial<LegacyMigrationMarker>>(legacyChatMigrationStorageKeyForUser(userId));
  return marker?.version === 1 && typeof marker.consideredAt === "string";
}

function markLegacyMigrationConsidered(userId: string, workspaceId: string): void {
  safeSaveToStorage<LegacyMigrationMarker>(legacyChatMigrationStorageKeyForUser(userId), {
    version: 1,
    consideredAt: new Date().toISOString(),
    workspaceId,
  });
}

function loadPersistedChatState(userId: string, workspaceId: string): PersistedChatState | null {
  const workspaceKey = chatStorageKeyForWorkspace(userId, workspaceId);
  const workspaceState = normalizePersistedChatState(
    safeLoadFromStorage<Partial<PersistedChatState>>(workspaceKey)
  );
  if (workspaceState) {
    return workspaceState;
  }

  if (hasLegacyMigrationMarker(userId)) {
    return null;
  }

  markLegacyMigrationConsidered(userId, workspaceId);
  const legacyState = normalizePersistedChatState(
    safeLoadFromStorage<Partial<PersistedChatState>>(chatStorageKeyForUser(userId))
  );
  if (!legacyState) {
    return null;
  }

  safeSaveToStorage<PersistedChatState>(workspaceKey, {
    ...legacyState,
    version: 2,
  });
  return legacyState;
}

function loadPersistedTrace(userId: string, workspaceId: string): Record<string, MessageTrace> {
  const raw = safeLoadFromStorage<Record<string, MessageTrace>>(traceStorageKeyForWorkspace(userId, workspaceId));
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  return raw;
}

function pruneTraceByMessages(
  traceByMessageId: Record<string, MessageTrace>,
  messagesBySession: Record<string, ChatMessage[]>
): Record<string, MessageTrace> {
  const messageIds = new Set(
    Object.values(messagesBySession)
      .flat()
      .map((message) => message.id)
  );
  return Object.fromEntries(Object.entries(traceByMessageId).filter(([messageId]) => messageIds.has(messageId)));
}

function persistTrace(traceByMessageId: Record<string, MessageTrace>): void {
  if (!_currentUserId || !_currentWorkspaceId) return;
  const toSave = Object.fromEntries(
    Object.entries(traceByMessageId)
      .filter(([, trace]) => trace.state !== "live")
      .map(([id, trace]) => [id, stripResultFromTrace(trace)])
  );
  safeSaveToStorage(traceStorageKeyForWorkspace(_currentUserId, _currentWorkspaceId), toSave);
}

function persistChatState(
  state: Pick<ChatState, "sessions" | "activeSessionId" | "messagesBySession" | "agentModeBySession">
): void {
  if (!_currentUserId || !_currentWorkspaceId) return;
  safeSaveToStorage<PersistedChatState>(chatStorageKeyForWorkspace(_currentUserId, _currentWorkspaceId), {
    version: 2,
    sessions: state.sessions,
    activeSessionId: state.activeSessionId,
    messagesBySession: state.messagesBySession,
    agentModeBySession: state.agentModeBySession,
  });
}

function isMessageMap(value: unknown): value is Record<string, ChatMessage[]> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  return Object.values(value).every((messages) => Array.isArray(messages));
}

export const useChatStore = create<ChatState>((set, get) => ({
  sessions: [],
  activeSessionId: null,
  messagesBySession: {},
  pendingIngestionBySession: {},
  pendingIngestionSetupBySession: {},
  pendingMultiChartBySession: {},
  agentModeBySession: {},
  isComposing: false,
  composerText: "",
  composerAttachment: null,
  traceByMessageId: {},

  setSessions: (sessions) =>
    set((state) => {
      const normalizedSessions = normalizeSessions(sessions);
      const sessionIds = new Set(normalizedSessions.map((session) => session.id));
      const activeSessionId =
        state.activeSessionId && sessionIds.has(state.activeSessionId)
          ? state.activeSessionId
          : normalizedSessions[0]?.id ?? null;
      const messagesBySession = Object.fromEntries(
        Object.entries(state.messagesBySession).filter(([sessionId]) => sessionIds.has(sessionId))
      );
      const pendingIngestionBySession = Object.fromEntries(
        Object.entries(state.pendingIngestionBySession).filter(([sessionId]) => sessionIds.has(sessionId))
      );
      const pendingIngestionSetupBySession = Object.fromEntries(
        Object.entries(state.pendingIngestionSetupBySession).filter(([sessionId]) => sessionIds.has(sessionId))
      );
      const pendingMultiChartBySession = Object.fromEntries(
        Object.entries(state.pendingMultiChartBySession).filter(([sessionId]) => sessionIds.has(sessionId))
      );
      const agentModeBySession = normalizeAgentModeMap(state.agentModeBySession, sessionIds);
      const nextState = {
        sessions: normalizedSessions,
        activeSessionId,
        messagesBySession,
        pendingIngestionBySession,
        pendingIngestionSetupBySession,
        pendingMultiChartBySession,
        agentModeBySession,
      };
      persistChatState(nextState);
      return nextState;
    }),

  addSession: (session) =>
    set((state) => {
      const normalizedSession = normalizeSession(session);
      const sessions = [
        normalizedSession,
        ...state.sessions.filter((item) => item.id !== normalizedSession.id),
      ];
      const nextState = {
        sessions,
        activeSessionId: state.activeSessionId,
        messagesBySession: {
          ...state.messagesBySession,
          [normalizedSession.id]: state.messagesBySession[normalizedSession.id] ?? [],
        },
        agentModeBySession: state.agentModeBySession,
      };
      persistChatState(nextState);
      return nextState;
    }),

  removeSession: (sessionId) =>
    set((state) => {
      const sessions = state.sessions.filter((s) => s.id !== sessionId);
      const activeSessionId =
        state.activeSessionId === sessionId ? sessions[0]?.id ?? null : state.activeSessionId;
      const messagesBySession = (() => {
        const next = { ...state.messagesBySession };
        delete next[sessionId];
        return next;
      })();
      const pendingIngestionBySession = (() => {
        const next = { ...state.pendingIngestionBySession };
        delete next[sessionId];
        return next;
      })();
      const pendingIngestionSetupBySession = (() => {
        const next = { ...state.pendingIngestionSetupBySession };
        delete next[sessionId];
        return next;
      })();
      const pendingMultiChartBySession = (() => {
        const next = { ...state.pendingMultiChartBySession };
        delete next[sessionId];
        return next;
      })();
      const agentModeBySession = (() => {
        const next = { ...state.agentModeBySession };
        delete next[sessionId];
        return next;
      })();
      const nextState = {
        sessions,
        activeSessionId,
        messagesBySession,
        pendingIngestionBySession,
        pendingIngestionSetupBySession,
        pendingMultiChartBySession,
        agentModeBySession,
      };
      persistChatState(nextState);
      return nextState;
    }),

  setActiveSession: (sessionId) =>
    set((state) => {
      const activeSessionId = sessionId && state.sessions.some((session) => session.id === sessionId)
        ? sessionId
        : null;
      const nextState = { ...state, activeSessionId };
      persistChatState(nextState);
      return { activeSessionId };
    }),

  setMessages: (sessionId, messages) =>
    set((state) => {
      const nextState = {
        ...state,
        messagesBySession: { ...state.messagesBySession, [sessionId]: messages },
      };
      persistChatState(nextState);
      return { messagesBySession: nextState.messagesBySession };
    }),

  appendMessage: (sessionId, message) =>
    set((state) => {
      const nextState = {
        ...state,
        messagesBySession: {
          ...state.messagesBySession,
          [sessionId]: [...(state.messagesBySession[sessionId] ?? []), message],
        },
      };
      persistChatState(nextState);
      return {
        messagesBySession: nextState.messagesBySession,
      };
    }),

  replaceMessage: (sessionId, messageId, message) =>
    set((state) => {
      const existing = state.messagesBySession[sessionId] ?? [];
      const idx = existing.findIndex((m) => m.id === messageId);
      const updated = idx >= 0
        ? [...existing.slice(0, idx), message, ...existing.slice(idx + 1)]
        : [...existing, message];
      const nextState = {
        ...state,
        messagesBySession: { ...state.messagesBySession, [sessionId]: updated },
      };
      persistChatState(nextState);
      return { messagesBySession: nextState.messagesBySession };
    }),

  resetConversation: (sessionId) =>
    set((state) => {
      const existingMessages = state.messagesBySession[sessionId] ?? [];
      const messageIds = new Set(existingMessages.map((message) => message.id));
      const traceByMessageId = Object.fromEntries(
        Object.entries(state.traceByMessageId).filter(([messageId]) => !messageIds.has(messageId))
      );
      const pendingIngestionBySession = { ...state.pendingIngestionBySession };
      const pendingIngestionSetupBySession = { ...state.pendingIngestionSetupBySession };
      const pendingMultiChartBySession = { ...state.pendingMultiChartBySession };
      delete pendingIngestionBySession[sessionId];
      delete pendingIngestionSetupBySession[sessionId];
      delete pendingMultiChartBySession[sessionId];
      const sessions = state.sessions.map((session) =>
        session.id === sessionId
          ? {
              ...session,
              lastMessage: "",
              messageCount: 0,
              updatedAt: new Date().toISOString(),
            }
          : session
      );
      const messagesBySession = {
        ...state.messagesBySession,
        [sessionId]: [],
      };
      const nextState = {
        ...state,
        sessions,
        messagesBySession,
        pendingIngestionBySession,
        pendingIngestionSetupBySession,
        pendingMultiChartBySession,
        traceByMessageId,
      };
      persistChatState(nextState);
      persistTrace(traceByMessageId);
      return {
        sessions,
        messagesBySession,
        pendingIngestionBySession,
        pendingIngestionSetupBySession,
        pendingMultiChartBySession,
        traceByMessageId,
      };
    }),

  setPendingIngestionApproval: (sessionId, pending) =>
    set((state) => {
      const next = { ...state.pendingIngestionBySession };
      if (pending) {
        next[sessionId] = pending;
      } else {
        delete next[sessionId];
      }
      return { pendingIngestionBySession: next };
    }),

  clearPendingIngestionApproval: (sessionId) =>
    set((state) => {
      if (!state.pendingIngestionBySession[sessionId]) {
        return state;
      }
      const next = { ...state.pendingIngestionBySession };
      delete next[sessionId];
      return { pendingIngestionBySession: next };
    }),

  setPendingIngestionSetup: (sessionId, pending) =>
    set((state) => {
      const next = { ...state.pendingIngestionSetupBySession };
      if (pending) {
        next[sessionId] = pending;
      } else {
        delete next[sessionId];
      }
      return { pendingIngestionSetupBySession: next };
    }),

  clearPendingIngestionSetup: (sessionId) =>
    set((state) => {
      if (!state.pendingIngestionSetupBySession[sessionId]) {
        return state;
      }
      const next = { ...state.pendingIngestionSetupBySession };
      delete next[sessionId];
      return { pendingIngestionSetupBySession: next };
    }),

  setPendingMultiChartConfirmation: (sessionId, pending) =>
    set((state) => {
      const next = { ...state.pendingMultiChartBySession };
      if (pending) {
        next[sessionId] = pending;
      } else {
        delete next[sessionId];
      }
      return { pendingMultiChartBySession: next };
    }),

  clearPendingMultiChartConfirmation: (sessionId) =>
    set((state) => {
      if (!state.pendingMultiChartBySession[sessionId]) {
        return state;
      }
      const next = { ...state.pendingMultiChartBySession };
      delete next[sessionId];
      return { pendingMultiChartBySession: next };
    }),

  // Sticky per-conversation mode: written only on an explicit user toggle, and
  // persisted so the conversation reopens in the mode it was left in.
  setAgentMode: (sessionId, enabled) =>
    set((state) => {
      const current = state.agentModeBySession[sessionId] === true;
      if (current === enabled) {
        return state;
      }
      const agentModeBySession = { ...state.agentModeBySession };
      if (enabled) {
        agentModeBySession[sessionId] = true;
      } else {
        delete agentModeBySession[sessionId];
      }
      persistChatState({ ...state, agentModeBySession });
      return { agentModeBySession };
    }),

  touchSession: (sessionId, updates) =>
    set((state) => {
      const sessions = state.sessions.map((session) => {
        if (session.id !== sessionId) {
          return session;
        }

        const nextMessageCount = Math.max(
          0,
          session.messageCount + Math.max(0, Math.trunc(updates.messageDelta ?? 0))
        );
        return {
          ...session,
          ...(updates.title ? { title: normalizeSessionTitle(updates.title) } : {}),
          ...(updates.lastMessage ? { lastMessage: updates.lastMessage } : {}),
          messageCount: nextMessageCount,
          updatedAt: new Date().toISOString(),
        };
      });
      const nextState = {
        ...state,
        sessions,
      };
      persistChatState(nextState);
      return { sessions };
    }),

  renameSession: (sessionId, title) =>
    set((state) => {
      const normalizedTitle = normalizeSessionTitle(title);
      let changed = false;
      const sessions = state.sessions.map((session) => {
        if (session.id !== sessionId || session.title === normalizedTitle) {
          return session;
        }
        changed = true;
        return { ...session, title: normalizedTitle };
      });
      if (!changed) {
        return state;
      }
      const nextState = { ...state, sessions };
      persistChatState(nextState);
      return { sessions };
    }),

  setComposerText: (text) => set({ composerText: text }),
  setComposerAttachment: (file) => set({ composerAttachment: file }),
  setIsComposing: (value) => set({ isComposing: value }),

  startTrace: (messageId, startedAt) =>
    set((state) => ({
      traceByMessageId: {
        ...state.traceByMessageId,
        [messageId]: { state: "live", steps: [], startedAt },
      },
    })),

  pushTraceStep: (messageId, step) =>
    set((state) => {
      const trace = state.traceByMessageId[messageId];
      if (!trace) return state;
      // Orphan tool_result: if a tool step with this id already exists as a stub, skip adding a duplicate
      const existing = trace.steps.find((s) => s.kind === "tool" && s.id === (step as { id: string }).id);
      if (existing && step.kind === "tool" && step.id === (existing as { id: string }).id) {
        return state;
      }
      return {
        traceByMessageId: {
          ...state.traceByMessageId,
          [messageId]: { ...trace, steps: [...trace.steps, step] },
        },
      };
    }),

  patchTraceStep: (messageId, stepId, patch) =>
    set((state) => {
      const trace = state.traceByMessageId[messageId];
      if (!trace) return state;
      let found = false;
      const steps = trace.steps.map((s) => {
        if (s.kind === "tool" && s.id === stepId) {
          found = true;
          return { ...s, ...patch };
        }
        return s;
      });
      if (!found) {
        // Orphan tool_result — create a stub step
        const stubStep: TraceStep = {
          kind: "tool",
          id: stepId,
          tool: (patch as Record<string, unknown>).tool as string ?? "unknown",
          args: {},
          startedAt: Date.now(),
          ...(patch as Partial<TraceStep>),
        } as TraceStep;
        steps.push(stubStep);
      }
      return {
        traceByMessageId: {
          ...state.traceByMessageId,
          [messageId]: { ...trace, steps },
        },
      };
    }),

  endTrace: (messageId, reason) =>
    set((state) => {
      const trace = state.traceByMessageId[messageId];
      if (!trace) return state;
      const updatedTrace: MessageTrace = {
        ...trace,
        state: "collapsed",
        endedAt: Date.now(),
        terminationReason: reason,
      };
      const traceByMessageId = {
        ...state.traceByMessageId,
        [messageId]: updatedTrace,
      };
      persistTrace(traceByMessageId);
      return { traceByMessageId };
    }),

  setTraceState: (messageId, traceState) =>
    set((state) => {
      const trace = state.traceByMessageId[messageId];
      if (!trace) return state;
      const traceByMessageId = {
        ...state.traceByMessageId,
        [messageId]: { ...trace, state: traceState },
      };
      if (traceState !== "live") {
        persistTrace(traceByMessageId);
      }
      return { traceByMessageId };
    }),

  getActiveMessages: () => {
    const { activeSessionId, messagesBySession } = get();
    if (!activeSessionId) return [];
    return messagesBySession[activeSessionId] ?? [];
  },

  hasSessionInCurrentScope: (sessionId: string) => get().sessions.some((session) => session.id === sessionId),

  // Which workspace the store's current state belongs to. Server-sync callers
  // must check this against their target workspace: during a workspace switch
  // the store briefly still holds the previous workspace's sessions, and
  // pushing those to the new workspace would leak chat history across
  // workspaces (and used to 500 on the server's message-id uniqueness).
  getScopeWorkspaceId: () => _currentWorkspaceId,

  initForWorkspace: (userId: string, workspaceId: string | null) => {
    const scopeKey = `${userId}:${workspaceId ?? ""}`;
    if (_initializedScopeKey === scopeKey) return;
    _currentUserId = userId;
    _currentWorkspaceId = workspaceId;
    _initializedScopeKey = scopeKey;

    if (!workspaceId) {
      set({
        sessions: [],
        activeSessionId: null,
        messagesBySession: {},
        pendingIngestionBySession: {},
        pendingIngestionSetupBySession: {},
        pendingMultiChartBySession: {},
        agentModeBySession: {},
        traceByMessageId: {},
      });
      return;
    }

    const persisted = loadPersistedChatState(userId, workspaceId);
    const messagesBySession = persisted?.messagesBySession ?? {};
    const traceByMessageId = pruneTraceByMessages(loadPersistedTrace(userId, workspaceId), messagesBySession);
    set({
      sessions: persisted?.sessions ?? [],
      activeSessionId: persisted?.activeSessionId ?? null,
      messagesBySession,
      pendingIngestionBySession: {},
      pendingIngestionSetupBySession: {},
      pendingMultiChartBySession: {},
      agentModeBySession: persisted?.agentModeBySession ?? {},
      traceByMessageId,
    });
  },

  initForUser: (userId: string) => {
    get().initForWorkspace(userId, null);
  },

  clearForUser: () => {
    if (_currentUserId && _currentWorkspaceId) {
      safeSaveToStorage(traceStorageKeyForWorkspace(_currentUserId, _currentWorkspaceId), {});
    }
    _currentUserId = null;
    _currentWorkspaceId = null;
    _initializedScopeKey = null;
    set({
      sessions: [],
      activeSessionId: null,
      messagesBySession: {},
      pendingIngestionBySession: {},
      pendingIngestionSetupBySession: {},
      pendingMultiChartBySession: {},
      agentModeBySession: {},
      traceByMessageId: {},
    });
  },
}));
