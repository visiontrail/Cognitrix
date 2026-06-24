import { describe, expect, it } from "vitest";

import { mergeAssets, mergeMessages, mergeSessions } from "../../lib/chat/persistence-api";
import type { ChatMessage, ChatSession } from "../../types/chat";
import type { ChartAsset } from "../../types/chart";

function session(id: string, updatedAt: string, title = id): ChatSession {
  return { id, title, createdAt: "2026-01-01T00:00:00.000Z", updatedAt, messageCount: 0 };
}

function message(id: string): ChatMessage {
  return { id, sessionId: "s1", role: "assistant", content: id, timestamp: "t" };
}

function asset(id: string): ChartAsset {
  return {
    id,
    title: id,
    chartType: "bar",
    spec: { chartType: "bar", title: id, echartsOption: {} },
    sourceMeta: { sessionId: "s1", messageId: "m1", prompt: "p" },
    createdAt: "2026-01-01T00:00:00.000Z",
    updatedAt: "2026-01-01T00:00:00.000Z",
  };
}

describe("mergeSessions", () => {
  it("unions by id and prefers the newer updatedAt on conflict", () => {
    const server = [session("a", "2026-02-01T00:00:00.000Z", "server-a"), session("b", "2026-01-01T00:00:00.000Z")];
    const local = [session("a", "2026-03-01T00:00:00.000Z", "local-a"), session("c", "2026-01-01T00:00:00.000Z")];

    const merged = mergeSessions(server, local);

    expect(merged.map((s) => s.id).sort()).toEqual(["a", "b", "c"]);
    // local "a" is newer, so its title wins
    expect(merged.find((s) => s.id === "a")?.title).toBe("local-a");
  });

  it("returns sessions sorted newest-first", () => {
    const merged = mergeSessions(
      [session("old", "2026-01-01T00:00:00.000Z")],
      [session("new", "2026-05-01T00:00:00.000Z")]
    );
    expect(merged.map((s) => s.id)).toEqual(["new", "old"]);
  });

  it("a fresh device (empty local) takes the full server set", () => {
    const server = [session("a", "2026-01-01T00:00:00.000Z"), session("b", "2026-02-01T00:00:00.000Z")];
    expect(mergeSessions(server, []).map((s) => s.id).sort()).toEqual(["a", "b"]);
  });
});

describe("mergeMessages", () => {
  it("takes the server set on a fresh device (more messages than local)", () => {
    const server = [message("m1"), message("m2")];
    expect(mergeMessages(server, [])).toBe(server);
  });

  it("keeps the local set mid-turn when it has more than the last committed server set", () => {
    const local = [message("m1"), message("m2"), message("m3")];
    const server = [message("m1"), message("m2")];
    expect(mergeMessages(server, local)).toBe(local);
  });
});

describe("mergeAssets", () => {
  it("unions by id without duplicating", () => {
    const merged = mergeAssets([asset("a1"), asset("a2")], [asset("a2"), asset("a3")]);
    expect(merged.map((a) => a.id).sort()).toEqual(["a1", "a2", "a3"]);
  });
});
