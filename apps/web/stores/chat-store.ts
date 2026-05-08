import { create } from "zustand";
import { normalizeSessionTitle } from "@/lib/chat/session-title";
import type { ChatSession, ChatMessage } from "@/types/chat";
import type { MessageTrace, TraceStep } from "@/types/trace";
import type { IngestionPlanAwaitingApproval, IngestionUploadResult } from "@/types/ingestion";
import {
  chatStorageKeyForUser,
  traceStorageKeyForUser,
  safeLoadFromStorage,
  safeSaveToStorage,
} from "@/lib/chat/session-storage";

export type PendingIngestionApproval = {
  upload: IngestionUploadResult;
  plan: IngestionPlanAwaitingApproval;
};

type ChatState = {
  sessions: ChatSession[];
  activeSessionId: string | null;
  messagesBySession: Record<string, ChatMessage[]>;
  pendingIngestionBySession: Record<string, PendingIngestionApproval | undefined>;
  isComposing: boolean;
  composerText: string;
  traceByMessageId: Record<string, MessageTrace>;

  setSessions: (sessions: ChatSession[]) => void;
  addSession: (session: ChatSession) => void;
  removeSession: (sessionId: string) => void;
  setActiveSession: (sessionId: string | null) => void;
  setMessages: (sessionId: string, messages: ChatMessage[]) => void;
  appendMessage: (sessionId: string, message: ChatMessage) => void;
  replaceMessage: (sessionId: string, messageId: string, message: ChatMessage) => void;
  setPendingIngestionApproval: (
    sessionId: string,
    pending: PendingIngestionApproval | null
  ) => void;
  clearPendingIngestionApproval: (sessionId: string) => void;
  touchSession: (
    sessionId: string,
    updates: { lastMessage?: string; messageDelta?: number; title?: string }
  ) => void;
  renameSession: (sessionId: string, title: string) => void;
  setComposerText: (text: string) => void;
  setIsComposing: (value: boolean) => void;

  startTrace: (messageId: string, startedAt: number) => void;
  pushTraceStep: (messageId: string, step: TraceStep) => void;
  patchTraceStep: (messageId: string, stepId: string, patch: Partial<Omit<TraceStep, "kind" | "id">>) => void;
  endTrace: (messageId: string, reason: "final" | "error" | "closed") => void;
  setTraceState: (messageId: string, state: MessageTrace["state"]) => void;

  getActiveMessages: () => ChatMessage[];
  initForUser: (userId: string) => void;
  clearForUser: () => void;
};

type PersistedChatState = {
  version: 1;
  sessions: ChatSession[];
  activeSessionId: string | null;
  messagesBySession: Record<string, ChatMessage[]>;
};

// Tracks the active user ID at module level — not in Zustand state to avoid re-renders.
let _currentUserId: string | null = null;
let _initializedUserId: string | null = null;

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

function loadPersistedChatState(userId: string): PersistedChatState | null {
  const state = safeLoadFromStorage<Partial<PersistedChatState>>(chatStorageKeyForUser(userId));
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
    version: 1,
    sessions,
    activeSessionId,
    messagesBySession: Object.fromEntries(
      Object.entries(messagesBySession).filter(([sessionId]) => sessionIds.has(sessionId))
    ),
  };
}

function loadPersistedTrace(userId: string): Record<string, MessageTrace> {
  const raw = safeLoadFromStorage<Record<string, MessageTrace>>(traceStorageKeyForUser(userId));
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  return raw;
}

function persistTrace(traceByMessageId: Record<string, MessageTrace>): void {
  if (!_currentUserId) return;
  const toSave = Object.fromEntries(
    Object.entries(traceByMessageId)
      .filter(([, trace]) => trace.state !== "live")
      .map(([id, trace]) => [id, stripResultFromTrace(trace)])
  );
  safeSaveToStorage(traceStorageKeyForUser(_currentUserId), toSave);
}

function persistChatState(state: Pick<ChatState, "sessions" | "activeSessionId" | "messagesBySession">): void {
  if (!_currentUserId) return;
  safeSaveToStorage<PersistedChatState>(chatStorageKeyForUser(_currentUserId), {
    version: 1,
    sessions: state.sessions,
    activeSessionId: state.activeSessionId,
    messagesBySession: state.messagesBySession,
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
  isComposing: false,
  composerText: "",
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
      const nextState = {
        sessions: normalizedSessions,
        activeSessionId,
        messagesBySession,
        pendingIngestionBySession,
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
      const nextState = { sessions, activeSessionId, messagesBySession, pendingIngestionBySession };
      persistChatState(nextState);
      return nextState;
    }),

  setActiveSession: (sessionId) =>
    set((state) => {
      const nextState = { ...state, activeSessionId: sessionId };
      persistChatState(nextState);
      return { activeSessionId: sessionId };
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

  initForUser: (userId: string) => {
    if (_initializedUserId === userId) return;
    _currentUserId = userId;
    _initializedUserId = userId;
    const persisted = loadPersistedChatState(userId);
    const traceByMessageId = loadPersistedTrace(userId);
    set({
      sessions: persisted?.sessions ?? [],
      activeSessionId: persisted?.activeSessionId ?? null,
      messagesBySession: persisted?.messagesBySession ?? {},
      pendingIngestionBySession: {},
      traceByMessageId,
    });
  },

  clearForUser: () => {
    if (_currentUserId) {
      safeSaveToStorage(traceStorageKeyForUser(_currentUserId), {});
    }
    _currentUserId = null;
    _initializedUserId = null;
    set({
      sessions: [],
      activeSessionId: null,
      messagesBySession: {},
      pendingIngestionBySession: {},
      traceByMessageId: {},
    });
  },
}));
