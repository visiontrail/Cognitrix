import { create } from "zustand";

export type ActivePanel = "chat" | "workspace" | "both" | "catalog";

// Soft lock while an agent-canvas run is building a page (design D9): the
// web-design editor disables user editing and shows a banner + stop button.
export type ActiveAgentRun = {
  runId: string;
  pageId: string;
  workspaceId: string;
};

type UIState = {
  activePanel: ActivePanel;
  chatSidebarOpen: boolean;
  workspaceSidebarOpen: boolean;
  chatCanvasSplitRatio: number;
  isSending: boolean;
  sendingBySession: Record<string, boolean>;
  isSaving: boolean;
  catalogOverlayInWorkspace: boolean;
  activeAgentRun: ActiveAgentRun | null;

  setActivePanel: (panel: ActivePanel) => void;
  setChatSidebarOpen: (open: boolean) => void;
  setWorkspaceSidebarOpen: (open: boolean) => void;
  setChatCanvasSplitRatio: (ratio: number) => void;
  toggleChatSidebar: () => void;
  toggleWorkspaceSidebar: () => void;
  setIsSending: (value: boolean) => void;
  setSessionSending: (sessionId: string, value: boolean) => void;
  setIsSaving: (value: boolean) => void;
  setCatalogOverlayInWorkspace: (value: boolean) => void;
  setActiveAgentRun: (run: ActiveAgentRun | null) => void;
  /** Clear the soft lock only if it belongs to the given run. */
  clearAgentRun: (runId: string) => void;
};

export const useUIStore = create<UIState>((set) => ({
  activePanel: "both",
  chatSidebarOpen: true,
  workspaceSidebarOpen: false,
  chatCanvasSplitRatio: 0.5,
  isSending: false,
  sendingBySession: {},
  isSaving: false,
  catalogOverlayInWorkspace: false,
  activeAgentRun: null,

  setActivePanel: (panel) => set({ activePanel: panel, catalogOverlayInWorkspace: false }),
  setChatSidebarOpen: (open) => set({ chatSidebarOpen: open }),
  setWorkspaceSidebarOpen: (open) => set({ workspaceSidebarOpen: open }),
  setChatCanvasSplitRatio: (ratio) => set({ chatCanvasSplitRatio: ratio }),
  toggleChatSidebar: () => set((s) => ({ chatSidebarOpen: !s.chatSidebarOpen })),
  toggleWorkspaceSidebar: () => set((s) => ({ workspaceSidebarOpen: !s.workspaceSidebarOpen })),
  setIsSending: (value) => set({ isSending: value }),
  setSessionSending: (sessionId, value) =>
    set((state) => {
      const sendingBySession = { ...state.sendingBySession };
      if (value) {
        sendingBySession[sessionId] = true;
      } else {
        delete sendingBySession[sessionId];
      }
      return {
        sendingBySession,
        isSending: Object.keys(sendingBySession).length > 0,
      };
    }),
  setIsSaving: (value) => set({ isSaving: value }),
  setCatalogOverlayInWorkspace: (value) => set({ catalogOverlayInWorkspace: value }),
  setActiveAgentRun: (run) => set({ activeAgentRun: run }),
  clearAgentRun: (runId) =>
    set((state) =>
      state.activeAgentRun?.runId === runId ? { activeAgentRun: null } : {}
    ),
}));
