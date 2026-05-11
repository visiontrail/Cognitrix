import { beforeEach, describe, expect, it } from "vitest";

import {
  chatStorageKeyForUser,
  chatStorageKeyForWorkspace,
  legacyChatMigrationStorageKeyForUser,
  traceStorageKeyForWorkspace,
} from "../../lib/chat/session-storage";
import { useChatStore } from "../../stores/chat-store";
import type { ChatMessage, ChatSession } from "../../types/chat";

function session(id: string, title: string): ChatSession {
  return {
    id,
    title,
    createdAt: "2026-05-11T00:00:00.000Z",
    updatedAt: "2026-05-11T00:00:00.000Z",
    messageCount: 0,
  };
}

function message(id: string, sessionId: string, content: string): ChatMessage {
  return {
    id,
    sessionId,
    role: "user",
    content,
    timestamp: "2026-05-11T00:00:00.000Z",
  };
}

describe("chat store workspace scoping", () => {
  beforeEach(() => {
    useChatStore.getState().clearForUser();
    window.localStorage.clear();
  });

  it("restores sessions, messages, and completed traces per workspace", () => {
    const store = useChatStore.getState();

    store.initForWorkspace("user-1", "ws-a");
    store.addSession(session("session-a", "Workspace A"));
    store.setActiveSession("session-a");
    store.setMessages("session-a", [message("msg-a", "session-a", "A question")]);
    store.startTrace("msg-a", 1000);
    store.pushTraceStep("msg-a", { kind: "planning", id: "plan-1", text: "Thinking", startedAt: 1000 });
    store.endTrace("msg-a", "final");
    store.setPendingIngestionApproval("session-a", {} as never);

    store.initForWorkspace("user-1", "ws-b");
    expect(useChatStore.getState().sessions).toEqual([]);
    expect(useChatStore.getState().activeSessionId).toBeNull();
    expect(useChatStore.getState().pendingIngestionBySession).toEqual({});
    expect(useChatStore.getState().traceByMessageId).toEqual({});

    useChatStore.getState().addSession(session("session-b", "Workspace B"));
    useChatStore.getState().setActiveSession("session-b");
    useChatStore.getState().setMessages("session-b", [message("msg-b", "session-b", "B question")]);

    useChatStore.getState().initForWorkspace("user-1", "ws-a");
    expect(useChatStore.getState().sessions.map((item) => item.id)).toEqual(["session-a"]);
    expect(useChatStore.getState().activeSessionId).toBe("session-a");
    expect(useChatStore.getState().messagesBySession["session-a"]?.[0]?.content).toBe("A question");
    expect(useChatStore.getState().traceByMessageId["msg-a"]?.state).toBe("collapsed");

    useChatStore.getState().initForWorkspace("user-1", "ws-b");
    expect(useChatStore.getState().sessions.map((item) => item.id)).toEqual(["session-b"]);
    expect(useChatStore.getState().messagesBySession["session-b"]?.[0]?.content).toBe("B question");
    expect(window.localStorage.getItem(chatStorageKeyForUser("user-1"))).toBeNull();
    expect(window.localStorage.getItem(chatStorageKeyForWorkspace("user-1", "ws-a"))).toContain("session-a");
    expect(window.localStorage.getItem(traceStorageKeyForWorkspace("user-1", "ws-a"))).toContain("msg-a");
  });

  it("considers legacy v1 chat data only once for a user", () => {
    window.localStorage.setItem(
      chatStorageKeyForUser("user-1"),
      JSON.stringify({
        version: 1,
        sessions: [session("legacy-session", "Legacy")],
        activeSessionId: "legacy-session",
        messagesBySession: {
          "legacy-session": [message("legacy-msg", "legacy-session", "old")],
        },
      })
    );

    useChatStore.getState().initForWorkspace("user-1", "ws-a");
    expect(useChatStore.getState().sessions.map((item) => item.id)).toEqual(["legacy-session"]);
    expect(window.localStorage.getItem(legacyChatMigrationStorageKeyForUser("user-1"))).toContain("ws-a");

    useChatStore.getState().initForWorkspace("user-1", "ws-b");
    expect(useChatStore.getState().sessions).toEqual([]);
    expect(window.localStorage.getItem(chatStorageKeyForWorkspace("user-1", "ws-b"))).toBeNull();
  });

  it("ignores malformed legacy v1 chat data and records that it was considered", () => {
    window.localStorage.setItem(chatStorageKeyForUser("user-1"), "{not-json");

    useChatStore.getState().initForWorkspace("user-1", "ws-a");

    expect(useChatStore.getState().sessions).toEqual([]);
    expect(window.localStorage.getItem(legacyChatMigrationStorageKeyForUser("user-1"))).toContain("ws-a");
    expect(window.localStorage.getItem(chatStorageKeyForWorkspace("user-1", "ws-a"))).toBeNull();
  });

  it("resets to an empty state when no workspace is active", () => {
    const store = useChatStore.getState();

    store.initForWorkspace("user-1", "ws-a");
    store.addSession(session("session-a", "Workspace A"));
    store.initForWorkspace("user-1", null);

    expect(useChatStore.getState().sessions).toEqual([]);
    expect(useChatStore.getState().activeSessionId).toBeNull();
    expect(useChatStore.getState().messagesBySession).toEqual({});
  });
});
