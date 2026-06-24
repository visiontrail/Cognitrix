import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatInput } from "../../components/chat/chat-input";
import { I18nProvider } from "../../lib/i18n/context";
import { I18N_STORAGE_KEY } from "../../lib/i18n/dictionary";
import { useChatStore } from "../../stores/chat-store";
import { useUIStore } from "../../stores/ui-store";
import { useWorkspaceStore } from "../../stores/workspace-store";

const { mutate, stopChatResponseMock, workspaceColumns } = vi.hoisted(() => ({
  mutate: vi.fn(),
  stopChatResponseMock: vi.fn(),
  workspaceColumns: [] as Array<{
    id: string;
    tableName: string;
    tableLabel: string;
    columnName: string;
    columnLabel: string;
    columnType: string;
  }>,
}));

vi.mock("../../hooks/use-chat", () => ({
  useSendMessage: () => ({ mutate }),
  stopChatResponse: stopChatResponseMock,
  useConfirmIngestionSetup: () => ({ mutate: vi.fn() }),
}));

vi.mock("../../hooks/use-workspace-columns", () => ({
  useWorkspaceColumns: () => workspaceColumns,
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
    useWorkspaceStore.setState({ activeWorkspaceId: null });
    workspaceColumns.splice(0, workspaceColumns.length);
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
    expect(screen.getAllByText("负数柱状图").length).toBeGreaterThan(0);
    expect(screen.getAllByText("分组条形图").length).toBeGreaterThan(0);
    expect(screen.getAllByText("聚类散点图").length).toBeGreaterThan(0);
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
    expect(screen.getAllByText("Negative bar").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Grouped bar").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Scatter clustering").length).toBeGreaterThan(0);
    expect(screen.getByText("chart_type: bar")).toBeInTheDocument();

    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");
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

  it("selects multi-chart generation from the action menu and sends the strategy", async () => {
    const user = userEvent.setup();
    render(React.createElement(ChatInput, { sessionId: "session-1" }));

    await user.click(screen.getByRole("button", { name: "Open chat actions" }));
    expect(screen.getByRole("menu", { name: "Chat actions" })).toBeInTheDocument();

    await user.click(screen.getByRole("menuitemcheckbox", { name: "Multi-chart generation" }));
    expect(screen.getByText("Multi-chart mode is on for this message. Include the grouping dimension, then press Enter.")).toBeInTheDocument();
    // The chip (distinct from the still-open menu item) carries the remove control.
    expect(screen.getByRole("button", { name: "Remove selected strategy" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("Chat Input"), "show headcount by department");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        content: "show headcount by department",
        generationStrategy: "multi_chart",
      })
    );
  });

  it("toggles data labels from the action menu and sends the flag", async () => {
    const user = userEvent.setup();
    render(React.createElement(ChatInput, { sessionId: "session-1" }));

    await user.click(screen.getByRole("button", { name: "Open chat actions" }));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Show data labels on chart" }));

    expect(
      screen.getByText(
        "Data labels are on for this message — the chart will print each value directly on the bars, slices, or points."
      )
    ).toBeInTheDocument();
    expect(screen.getByText("Data labels on")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Chat Input"), "headcount by department");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        content: "headcount by department",
        showDataLabels: true,
      })
    );
  });

  it("multi-selects several generation options and sends all of them together", async () => {
    const user = userEvent.setup();
    render(React.createElement(ChatInput, { sessionId: "session-1" }));

    await user.click(screen.getByRole("button", { name: "Open chat actions" }));
    // The menu stays open between toggles so multiple options can be picked.
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Multi-chart generation" }));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Show data labels on chart" }));

    expect(screen.getByRole("menuitemcheckbox", { name: "Multi-chart generation" })).toHaveAttribute(
      "aria-checked",
      "true"
    );
    expect(screen.getByRole("menuitemcheckbox", { name: "Show data labels on chart" })).toHaveAttribute(
      "aria-checked",
      "true"
    );

    // Both chips are present, and the hint switches to the combined form.
    expect(screen.getByRole("button", { name: "Remove selected strategy" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Turn off data labels" })).toBeInTheDocument();
    expect(
      screen.getByText("2 generation options are on for this message. Press Enter to send.")
    ).toBeInTheDocument();

    await user.type(screen.getByLabelText("Chat Input"), "headcount by department");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        content: "headcount by department",
        generationStrategy: "multi_chart",
        showDataLabels: true,
      })
    );
  });

  it("removes one selected option from its chip without affecting the others", async () => {
    const user = userEvent.setup();
    render(React.createElement(ChatInput, { sessionId: "session-1" }));

    await user.click(screen.getByRole("button", { name: "Open chat actions" }));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Multi-chart generation" }));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Show data labels on chart" }));

    // Drop multi-chart via its chip; data labels stays on.
    await user.click(screen.getByRole("button", { name: "Remove selected strategy" }));

    expect(screen.queryByRole("button", { name: "Remove selected strategy" })).not.toBeInTheDocument();
    expect(screen.getByText("Data labels on")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Chat Input"), "headcount by department");
    await user.click(screen.getByRole("button", { name: "Send" }));

    const payload = mutate.mock.calls.at(-1)?.[0] ?? {};
    expect(payload).toMatchObject({ showDataLabels: true });
    expect(payload).not.toHaveProperty("generationStrategy");
  });

  it("shows human-readable column labels in @ suggestions while inserting physical names", async () => {
    const user = userEvent.setup();
    workspaceColumns.push({
      id: "employee_master.c_1",
      tableName: "employee_master",
      tableLabel: "员工主数据",
      columnName: "c_1",
      columnLabel: "员工姓名",
      columnType: "VARCHAR",
    });
    useWorkspaceStore.setState({ activeWorkspaceId: "ws-1" });

    render(React.createElement(ChatInput, { sessionId: "session-1" }));

    const input = screen.getByLabelText("Chat Input");
    await user.type(input, "@");

    expect(screen.getByRole("listbox", { name: "Column mention picker" })).toBeInTheDocument();
    expect(screen.getByText("@员工姓名")).toBeInTheDocument();
    expect(screen.getByText("@c_1")).toBeInTheDocument();

    await user.keyboard("{Enter}");
    expect(input).toHaveValue("@c_1 ");
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
