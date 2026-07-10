import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MessageSources } from "../../components/chat/message-sources";
import { MessageItem } from "../../components/chat/message-item";
import { TooltipProvider } from "../../components/ui/tooltip";
import { I18nProvider } from "../../lib/i18n/context";
import type { ChatMessage, MessageSource } from "../../types/chat";

vi.mock("@/lib/clipboard", () => ({
  copyTextToClipboard: vi.fn(async () => true),
}));

vi.mock("@/lib/saved-prompts/api", () => ({
  SavedPromptApiError: class extends Error {},
  createSavedPrompt: vi.fn(),
  updateSavedPrompt: vi.fn(),
  listSavedPrompts: vi.fn(async () => []),
  archiveSavedPrompt: vi.fn(),
  markSavedPromptUsed: vi.fn(),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function renderComponent(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <TooltipProvider>{ui}</TooltipProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const SOURCES: MessageSource[] = [
  { id: 2, title: "Auto News", url: "https://www.b.example.com/ev?ref=1" },
  { id: 1, title: "EV Report", url: "https://a.example.com/ev" },
];

describe("MessageSources", () => {
  it("renders each source with number, title, domain, and safe external link", () => {
    renderComponent(<MessageSources sources={SOURCES} />);

    expect(screen.getByText("Sources")).toBeInTheDocument();

    const reportLink = screen.getByRole("link", { name: /EV Report/ });
    expect(reportLink).toHaveAttribute("href", "https://a.example.com/ev");
    expect(reportLink).toHaveAttribute("target", "_blank");
    expect(reportLink).toHaveAttribute("rel", "noopener noreferrer");

    // Domain is shown (www. stripped).
    expect(screen.getByText(/b\.example\.com/)).toBeInTheDocument();
    // Ordinal markers present.
    expect(screen.getByText("[1]")).toBeInTheDocument();
    expect(screen.getByText("[2]")).toBeInTheDocument();
  });

  it("orders sources ascending by id regardless of input order", () => {
    renderComponent(<MessageSources sources={SOURCES} />);
    const markers = screen.getAllByText(/^\[\d+\]$/).map((el) => el.textContent);
    expect(markers).toEqual(["[1]", "[2]"]);
  });

  it("renders nothing when there are no sources", () => {
    const { container } = renderComponent(<MessageSources sources={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when sources is undefined", () => {
    const { container } = renderComponent(<MessageSources sources={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("MessageItem source citations", () => {
  function assistantMessage(sources?: MessageSource[]): ChatMessage {
    return {
      id: "assistant-1",
      sessionId: "session-1",
      role: "assistant",
      content: "BYD leads with 100 vs Tesla 80 [1].",
      timestamp: "2026-06-26T00:00:00Z",
      sources,
    };
  }

  it("renders the citation区 for a persisted assistant message carrying sources", () => {
    renderComponent(<MessageItem message={assistantMessage([{ id: 1, title: "EV Report", url: "https://a.example.com/ev" }])} />);
    expect(screen.getByText("Sources")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /EV Report/ })).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
  });

  it("does not render a citation区 when the message has no sources", () => {
    renderComponent(<MessageItem message={assistantMessage(undefined)} />);
    expect(screen.queryByText("Sources")).not.toBeInTheDocument();
  });
});
