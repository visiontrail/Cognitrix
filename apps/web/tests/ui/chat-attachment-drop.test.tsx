import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatPanel } from "../../components/chat/chat-panel";
import { I18nProvider } from "../../lib/i18n/context";
import { useChatStore } from "../../stores/chat-store";
import { useUIStore } from "../../stores/ui-store";
import { useWorkspaceStore } from "../../stores/workspace-store";

const { toastMock } = vi.hoisted(() => ({
  toastMock: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}));

vi.mock("sonner", () => ({ toast: toastMock }));

vi.mock("../../hooks/use-chat", () => ({
  useChatMessages: () => ({ isLoading: false }),
  useCreateSession: () => ({ mutate: vi.fn(), isPending: false }),
  useSendMessage: () => ({ mutate: vi.fn() }),
  useConfirmIngestionSetup: () => ({ mutate: vi.fn() }),
  stopChatResponse: vi.fn(),
}));

vi.mock("../../components/chat/message-list", () => ({
  MessageList: () => React.createElement("div", null, "messages"),
}));

vi.mock("../../hooks/use-workspace-columns", () => ({
  useWorkspaceColumns: () => [],
}));

vi.mock("../../hooks/use-backend-capabilities", () => ({
  useBackendCapabilities: () => ({ agentCanvasModeEnabled: false, webSearchEnabled: false }),
}));

vi.mock("../../hooks/use-saved-prompts", () => ({
  useSavedPrompts: () => ({ data: [], isLoading: false, isError: false }),
  useMarkSavedPromptUsed: () => ({ mutate: vi.fn() }),
  useCreateSavedPrompt: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateSavedPrompt: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useArchiveSavedPrompt: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

function makeFile(name: string, size = 2048): File {
  const file = new File(["x"], name);
  Object.defineProperty(file, "size", { value: size });
  return file;
}

function dataTransferWith(files: File[]) {
  return { files, items: [], types: ["Files"] };
}

function renderPanel() {
  return render(React.createElement(I18nProvider, null, React.createElement(ChatPanel)));
}

function dropZone(): HTMLElement {
  return screen.getByTestId("chat-drop-zone");
}

describe("Chat panel Excel drag-and-drop", () => {
  beforeEach(() => {
    toastMock.error.mockReset();
    toastMock.warning.mockReset();
    toastMock.info.mockReset();
    window.localStorage.clear();

    useChatStore.setState({
      sessions: [
        {
          id: "s1",
          title: "Session",
          createdAt: "2026-07-31T00:00:00.000Z",
          updatedAt: "2026-07-31T00:00:00.000Z",
          messageCount: 0,
        },
      ],
      activeSessionId: "s1",
      messagesBySession: { s1: [] },
      pendingIngestionBySession: {},
      pendingIngestionSetupBySession: {},
      composerText: "",
      composerAttachment: null,
    });
    useUIStore.setState({ activePanel: "chat", isSending: false, sendingBySession: {} });
    useWorkspaceStore.setState({ activeWorkspaceId: "ws-1" });
  });

  it("shows the drop overlay while a file drag hovers the panel", () => {
    renderPanel();

    fireEvent.dragEnter(dropZone(), { dataTransfer: dataTransferWith([makeFile("a.xlsx")]) });

    expect(screen.getByTestId("chat-drop-overlay")).toBeInTheDocument();
    expect(screen.getByText("Drop the Excel file to import it")).toBeInTheDocument();
    expect(screen.getByText("One .xlsx workbook at a time · up to 10 MB")).toBeInTheDocument();
  });

  it("attaches a single dropped .xlsx file and hides the overlay", () => {
    renderPanel();
    const file = makeFile("headcount.xlsx");

    fireEvent.dragEnter(dropZone(), { dataTransfer: dataTransferWith([file]) });
    fireEvent.drop(dropZone(), { dataTransfer: dataTransferWith([file]) });

    expect(useChatStore.getState().composerAttachment).toBe(file);
    expect(screen.getByText("Attached: headcount.xlsx")).toBeInTheDocument();
    expect(screen.queryByTestId("chat-drop-overlay")).not.toBeInTheDocument();
    expect(toastMock.warning).not.toHaveBeenCalled();
    expect(toastMock.error).not.toHaveBeenCalled();
  });

  it("keeps the first workbook and explains the one-file limit for a multi-file drop", () => {
    renderPanel();
    const first = makeFile("q1.xlsx");

    fireEvent.drop(dropZone(), {
      dataTransfer: dataTransferWith([first, makeFile("q2.xlsx"), makeFile("q3.xlsx")]),
    });

    expect(useChatStore.getState().composerAttachment).toBe(first);
    expect(toastMock.warning).toHaveBeenCalledWith(
      'One Excel file per message. Kept "q1.xlsx" and skipped 2 other file(s) — import them one after another.'
    );
  });

  it("rejects unsupported file types with an explanation", () => {
    renderPanel();

    fireEvent.drop(dropZone(), { dataTransfer: dataTransferWith([makeFile("report.pdf")]) });

    expect(useChatStore.getState().composerAttachment).toBeNull();
    expect(toastMock.error).toHaveBeenCalledWith(
      '"report.pdf" isn\'t supported. Only .xlsx workbooks can be imported.'
    );
  });

  it("rejects oversized workbooks", () => {
    renderPanel();

    fireEvent.drop(dropZone(), {
      dataTransfer: dataTransferWith([makeFile("huge.xlsx", 11 * 1024 * 1024)]),
    });

    expect(useChatStore.getState().composerAttachment).toBeNull();
    expect(toastMock.error).toHaveBeenCalledWith(
      '"huge.xlsx" is over the 10 MB limit. Split the workbook or remove unused sheets, then try again.'
    );
  });

  it("refuses drops while the assistant is streaming", () => {
    useUIStore.setState({ sendingBySession: { s1: true } });
    renderPanel();

    fireEvent.dragEnter(dropZone(), { dataTransfer: dataTransferWith([makeFile("a.xlsx")]) });
    expect(screen.getByText("Can't add a file right now")).toBeInTheDocument();

    fireEvent.drop(dropZone(), { dataTransfer: dataTransferWith([makeFile("a.xlsx")]) });

    expect(useChatStore.getState().composerAttachment).toBeNull();
    expect(toastMock.info).toHaveBeenCalledWith(
      "The assistant is still answering — wait for it to finish before adding a file."
    );
  });

  it("ignores drags that carry no files", () => {
    renderPanel();

    fireEvent.dragEnter(dropZone(), { dataTransfer: { files: [], items: [], types: ["text/plain"] } });

    expect(screen.queryByTestId("chat-drop-overlay")).not.toBeInTheDocument();
  });
});
