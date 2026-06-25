import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { useChatStore } from "../../stores/chat-store";
import { AgentTrace } from "../../components/chat/agent-trace";
import type { MessageTrace } from "../../types/trace";

const MSG_ID = "msg-trace-test";

// jsdom doesn't implement scrollIntoView
window.HTMLElement.prototype.scrollIntoView = vi.fn();

function seedTrace(trace: MessageTrace) {
  useChatStore.setState((s) => ({
    traceByMessageId: { ...s.traceByMessageId, [MSG_ID]: trace },
  }));
}

function resetTrace() {
  useChatStore.setState({ traceByMessageId: {} });
}

// The i18n mock returns the key string with {{param}} substituted,
// so e.g. t("chat.trace.thoughtFor", { duration: "5.2s" }) → "chat.trace.thoughtFor"
// (key has no {{duration}} in it, so substitution is a no-op on the key string)
vi.mock("../../lib/i18n/context", () => ({
  useI18n: () => ({
    t: (key: string, params?: Record<string, string | number | null | undefined>) => {
      let str = key;
      if (params) {
        for (const [k, v] of Object.entries(params)) {
          str = str.replace(`{{${k}}}`, String(v ?? ""));
        }
      }
      return str;
    },
    locale: "en-US",
    setLocale: () => undefined,
  }),
}));

describe("AgentTrace component", () => {
  beforeEach(() => {
    resetTrace();
  });
  afterEach(() => {
    resetTrace();
  });

  it("shows pulsing dot on the running step when trace is live", () => {
    const now = Date.now();
    seedTrace({
      state: "live",
      startedAt: now - 500,
      steps: [
        {
          kind: "tool",
          id: "step-1",
          tool: "execute_readonly_sql",
          args: { sql: "SELECT 1" },
          startedAt: now - 400,
          status: "running",
        },
      ],
    });

    const { container } = render(<AgentTrace messageId={MSG_ID} />);
    // Pulsing dot has animate-pulse class
    const dot = container.querySelector(".animate-pulse");
    expect(dot).toBeInTheDocument();
  });

  it("renders collapsed chip with correct i18n key text", () => {
    const now = Date.now();
    seedTrace({
      state: "collapsed",
      startedAt: now - 4000,
      endedAt: now,
      steps: [
        {
          kind: "tool",
          id: "step-1",
          tool: "execute_readonly_sql",
          args: { sql: "SELECT 1" },
          startedAt: now - 3500,
          completedAt: now - 1000,
          status: "ok",
        },
        {
          kind: "tool",
          id: "step-2",
          tool: "describe_table",
          args: { table_name: "employees" },
          startedAt: now - 1000,
          completedAt: now - 500,
          status: "ok",
        },
      ],
    });

    render(<AgentTrace messageId={MSG_ID} />);
    // The i18n mock returns keys — chip should contain the key text
    const chip = screen.getByRole("button");
    expect(chip).toBeInTheDocument();
    // Should contain the thoughtFor key
    expect(chip.textContent).toContain("chat.trace.thoughtFor");
    // Should contain the toolCallsCount key
    expect(chip.textContent).toContain("chat.trace.toolCallsCount");
  });

  it("expands trace when collapsed chip is clicked", async () => {
    const user = userEvent.setup();
    const now = Date.now();
    seedTrace({
      state: "collapsed",
      startedAt: now - 2000,
      endedAt: now,
      steps: [
        {
          kind: "planning",
          id: "plan-0",
          text: "I will check the schema first.",
          startedAt: now - 1900,
        },
        {
          kind: "tool",
          id: "step-1",
          tool: "list_tables",
          args: {},
          startedAt: now - 1500,
          completedAt: now - 1000,
          status: "ok",
        },
      ],
    });

    render(<AgentTrace messageId={MSG_ID} />);
    // Click the collapsed chip button
    const chip = screen.getAllByRole("button")[0]!;
    await user.click(chip);

    // After click, trace state becomes "expanded"
    await waitFor(() => {
      const state = useChatStore.getState().traceByMessageId[MSG_ID]?.state;
      expect(state).toBe("expanded");
    });
  });

  it("collapses again when expanded chip is clicked", async () => {
    const user = userEvent.setup();
    const now = Date.now();
    seedTrace({
      state: "expanded",
      startedAt: now - 2000,
      endedAt: now,
      steps: [
        {
          kind: "tool",
          id: "step-1",
          tool: "list_tables",
          args: {},
          startedAt: now - 1500,
          completedAt: now - 1000,
          status: "ok",
        },
      ],
    });

    render(<AgentTrace messageId={MSG_ID} />);
    // First button is the chip toggle
    const chip = screen.getAllByRole("button")[0]!;
    await user.click(chip);

    await waitFor(() => {
      const state = useChatStore.getState().traceByMessageId[MSG_ID]?.state;
      expect(state).toBe("collapsed");
    });
  });

  it("renders post-reload chip when traceSummary exists but no in-memory trace", () => {
    // No trace in store, but traceSummary supplied as prop
    render(
      <AgentTrace
        messageId="msg-no-trace"
        traceSummary={{ stepCount: 3, durationMs: 5200, status: "ok" }}
      />
    );
    // Should show a non-clickable summary chip (no button role)
    expect(screen.queryByRole("button")).toBeNull();
    // Should display the thoughtFor i18n key text (mock returns key string)
    expect(screen.getByText(/chat\.trace\.(thoughtFor|toolCallsCount)/)).toBeInTheDocument();
  });

  it("renders selected generation-option pills on the post-reload summary chip", () => {
    render(
      <AgentTrace
        messageId="msg-no-trace-opts"
        traceSummary={{ stepCount: 2, durationMs: 3100, status: "ok" }}
        generationOptions={["multi_chart", "data_labels"]}
      />
    );
    // chip label keys come from the generation-options registry
    expect(screen.getByText("chat.strategy.multiChart")).toBeInTheDocument();
    expect(screen.getByText("chat.dataLabels.chip")).toBeInTheDocument();
  });

  it("renders generation-option pills next to the collapsed in-memory trace chip", () => {
    const now = Date.now();
    seedTrace({
      state: "collapsed",
      startedAt: now - 4000,
      endedAt: now,
      steps: [
        {
          kind: "tool",
          id: "step-1",
          tool: "run_semantic_query",
          args: {},
          startedAt: now - 3500,
          completedAt: now - 3000,
          status: "ok",
        },
      ],
    });
    render(<AgentTrace messageId={MSG_ID} generationOptions={["multi_chart"]} />);
    expect(screen.getByText("chat.strategy.multiChart")).toBeInTheDocument();
    expect(screen.queryByText("chat.dataLabels.chip")).toBeNull();
  });

  it("renders no pills when no generation options were selected", () => {
    render(
      <AgentTrace
        messageId="msg-no-trace-no-opts"
        traceSummary={{ stepCount: 1, durationMs: 1200, status: "ok" }}
      />
    );
    expect(screen.queryByText("chat.strategy.multiChart")).toBeNull();
    expect(screen.queryByText("chat.dataLabels.chip")).toBeNull();
  });
});
