import { describe, expect, it } from "vitest";

import {
  chatStorageKeyForUser,
  chatStorageKeyForWorkspace,
  legacyChatMigrationStorageKeyForUser,
  safeLoadFromStorage,
  safeSaveToStorage,
  traceStorageKeyForUser,
  traceStorageKeyForWorkspace,
} from "../../lib/chat/session-storage";

describe("session-storage helpers", () => {
  it("loads and parses JSON payload", () => {
    window.localStorage.setItem("demo", JSON.stringify({ a: 1 }));
    expect(safeLoadFromStorage<{ a: number }>("demo")).toEqual({ a: 1 });
  });

  it("builds v1 user keys and v2 workspace keys", () => {
    expect(chatStorageKeyForUser("user-1")).toBe("cognitrix:chat:v1:user-1");
    expect(traceStorageKeyForUser("user-1")).toBe("cognitrix:chat-trace:v1:user-1");
    expect(chatStorageKeyForWorkspace("user-1", "ws-1")).toBe("cognitrix:chat:v2:user-1:ws-1");
    expect(traceStorageKeyForWorkspace("user-1", "ws-1")).toBe("cognitrix:chat-trace:v2:user-1:ws-1");
    expect(legacyChatMigrationStorageKeyForUser("user-1")).toBe("cognitrix:chat:v1-migration:user-1");
  });

  it("returns null for missing or malformed payloads", () => {
    expect(safeLoadFromStorage("missing")).toBeNull();

    window.localStorage.setItem("broken", "{invalid-json");
    expect(safeLoadFromStorage("broken")).toBeNull();
  });

  it("does not throw when storage write fails", () => {
    const originalStorage = window.localStorage;

    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: () => null,
        setItem: () => {
          throw new Error("quota_exceeded");
        },
        removeItem: () => undefined,
        clear: () => undefined
      }
    });

    expect(() => safeSaveToStorage("demo", { a: 1 })).not.toThrow();

    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: originalStorage
    });
  });
});
