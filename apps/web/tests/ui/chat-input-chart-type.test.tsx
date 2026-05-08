import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatInput } from "../../components/chat/chat-input";
import { I18nProvider } from "../../lib/i18n/context";
import { I18N_STORAGE_KEY } from "../../lib/i18n/dictionary";
import { useChatStore } from "../../stores/chat-store";
import { useUIStore } from "../../stores/ui-store";

const { mutate, stopChatResponseMock } = vi.hoisted(() => ({
  mutate: vi.fn(),
  stopChatResponseMock: vi.fn(),
}));

vi.mock("../../hooks/use-chat", () => ({
  useSendMessage: () => ({ mutate }),
  stopChatResponse: stopChatResponseMock,
}));

vi.mock("../../hooks/use-workspace-columns", () => ({
  useWorkspaceColumns: () => [],
}));

describe("ChatInput chart type picker", () => {
  beforeEach(() => {
    mutate.mockReset();
    window.localStorage.clear();
    useChatStore.setState({
      composerText: "",
      pendingIngestionBySession: {},
    });
    useUIStore.setState({
      isSending: false,
      sendingBySession: {},
    });
  });

  it("localizes chart type suggestions after switching to Chinese", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(I18N_STORAGE_KEY, "zh-CN");

    render(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(ChatInput, { sessionId: "session-1" })
      )
    );

    const input = await screen.findByLabelText("对话输入框");
    await user.type(input, "#");

    expect(await screen.findByRole("listbox", { name: "图表类型选择器" })).toBeInTheDocument();
    expect(screen.getAllByText("柱状图").length).toBeGreaterThan(0);
    expect(screen.getAllByText("比较").length).toBeGreaterThan(0);
    expect(screen.getByText("比较不同类别的数值。")).toBeInTheDocument();
  });

  it("opens chart type suggestions on # and sends the selected chart_type", async () => {
    const user = userEvent.setup();
    render(React.createElement(ChatInput, { sessionId: "session-1" }));

    const input = screen.getByLabelText("Chat Input");
    await user.type(input, "#");

    expect(screen.getByRole("listbox", { name: "Chart type picker" })).toBeInTheDocument();
    expect(screen.getAllByText("Bar").length).toBeGreaterThan(0);
    expect(screen.getByText("chart_type: bar")).toBeInTheDocument();

    await user.keyboard("{ArrowDown}{Enter}");
    expect(input).toHaveValue("#stacked_bar ");
    expect(screen.getByText("Selected chart_type: stacked_bar. Press Enter to send.")).toBeInTheDocument();

    await user.clear(input);
    await user.type(input, "#stacked_bar show headcount by department");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        content: "#stacked_bar show headcount by department",
        preferredChartType: "stacked_bar",
      })
    );
  });

  it("scrolls the chart type list as keyboard selection moves", async () => {
    const user = userEvent.setup();
    const scrollTo = vi.fn();
    const originalScrollTo = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollTo");
    const originalOffsetTop = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetTop");
    const originalOffsetHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetHeight");
    const originalClientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientHeight");

    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: scrollTo,
    });
    Object.defineProperty(HTMLElement.prototype, "offsetTop", {
      configurable: true,
      get() {
        const options = Array.from(document.querySelectorAll('[role="option"]'));
        return options.indexOf(this) * 40;
      },
    });
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
      configurable: true,
      get() {
        return this.getAttribute("role") === "option" ? 40 : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", {
      configurable: true,
      get() {
        return this.id === "chart-type-options" ? 120 : 0;
      },
    });

    try {
      render(React.createElement(ChatInput, { sessionId: "session-1" }));
      const input = screen.getByLabelText("Chat Input");

      await user.type(input, "#");
      scrollTo.mockClear();
      await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}");

      await waitFor(() => {
        expect(scrollTo).toHaveBeenCalledWith({ top: 40, behavior: "smooth" });
      });
    } finally {
      if (originalScrollTo) {
        Object.defineProperty(HTMLElement.prototype, "scrollTo", originalScrollTo);
      } else {
        Reflect.deleteProperty(HTMLElement.prototype, "scrollTo");
      }
      if (originalOffsetTop) {
        Object.defineProperty(HTMLElement.prototype, "offsetTop", originalOffsetTop);
      } else {
        Reflect.deleteProperty(HTMLElement.prototype, "offsetTop");
      }
      if (originalOffsetHeight) {
        Object.defineProperty(HTMLElement.prototype, "offsetHeight", originalOffsetHeight);
      } else {
        Reflect.deleteProperty(HTMLElement.prototype, "offsetHeight");
      }
      if (originalClientHeight) {
        Object.defineProperty(HTMLElement.prototype, "clientHeight", originalClientHeight);
      } else {
        Reflect.deleteProperty(HTMLElement.prototype, "clientHeight");
      }
    }
  });

  it("only locks and stops the active sending session", async () => {
    const user = userEvent.setup();
    useUIStore.setState({
      isSending: true,
      sendingBySession: { "session-1": true },
    });

    const { rerender } = render(React.createElement(ChatInput, { sessionId: "session-1" }));

    expect(screen.getByLabelText("Chat Input")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Stop response" }));
    expect(stopChatResponseMock).toHaveBeenCalledWith("session-1");

    useChatStore.setState({ composerText: "show headcount" });
    rerender(React.createElement(ChatInput, { sessionId: "session-2" }));

    expect(screen.getByLabelText("Chat Input")).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "Send" })).not.toBeDisabled();
  });
});
