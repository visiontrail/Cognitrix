"use client";

import { KeyboardEvent, PointerEvent, useCallback, useEffect, useRef, useState } from "react";
import { GlobalSidebar } from "./global-sidebar";
import { WorkspaceOnboardingGate } from "./workspace-onboarding-gate";
import { ChatPanel } from "@/components/chat/chat-panel";
import { WorkspaceCatalogPage } from "@/components/workspace/workspace-catalog-page";
import { WorkspacePanel } from "@/components/workspace/workspace-panel";
import { useUIStore } from "@/stores/ui-store";
import { useChatSessions } from "@/hooks/use-chat";
import { useCreateWorkspace, useWorkspaceList } from "@/hooks/use-workspace";
import { useChartAssets } from "@/hooks/use-chart-assets";
import { useWorkspaceStore } from "@/stores/workspace-store";
import { useChatStore } from "@/stores/chat-store";
import { useAssetStore } from "@/stores/asset-store";
import { useSession } from "@/lib/auth/use-session";
import { hydrateWorkspaceStateFromServer } from "@/lib/chat/server-sync";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n/context";

const MIN_SPLIT_PANEL_WIDTH = 320;
const SPLIT_KEYBOARD_STEP = 0.02;

export function AppShell() {
  const { t } = useI18n();
  const { user } = useSession();
  const initChatForWorkspace = useChatStore((s) => s.initForWorkspace);
  const initAssetsForUser = useAssetStore((s) => s.initForUser);
  const activePanel = useUIStore((s) => s.activePanel);
  const chatSidebarOpen = useUIStore((s) => s.chatSidebarOpen);
  const chatCanvasSplitRatio = useUIStore((s) => s.chatCanvasSplitRatio);
  const setChatCanvasSplitRatio = useUIStore((s) => s.setChatCanvasSplitRatio);
  const catalogOverlayInWorkspace = useUIStore((s) => s.catalogOverlayInWorkspace);
  const setCatalogOverlayInWorkspace = useUIStore((s) => s.setCatalogOverlayInWorkspace);
  const workspaces = useWorkspaceStore((s) => s.workspaces);
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId);
  const setActiveWorkspace = useWorkspaceStore((s) => s.setActiveWorkspace);
  const splitContainerRef = useRef<HTMLDivElement>(null);
  const [isResizingSplit, setIsResizingSplit] = useState(false);

  useChatSessions();
  const workspaceListQuery = useWorkspaceList();
  const createWorkspace = useCreateWorkspace();
  useChartAssets();

  useEffect(() => {
    if (user?.id) {
      // Load the localStorage cache synchronously first, then merge the server's
      // durable cross-device copy on top. Order matters: hydration reads the
      // just-loaded local stores, so it must run after the inits.
      initChatForWorkspace(user.id, activeWorkspaceId);
      initAssetsForUser(user.id);
      if (activeWorkspaceId) {
        void hydrateWorkspaceStateFromServer(activeWorkspaceId);
      }
    }
  }, [activeWorkspaceId, user?.id, initChatForWorkspace, initAssetsForUser]);

  useEffect(() => {
    if (activeWorkspaceId || workspaces.length === 0) {
      return;
    }
    setActiveWorkspace(workspaces[0].id);
  }, [activeWorkspaceId, setActiveWorkspace, workspaces]);

  useEffect(() => {
    const handleKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey) {
        if (e.key === "1") {
          e.preventDefault();
          useUIStore.getState().setActivePanel("chat");
        } else if (e.key === "2") {
          e.preventDefault();
          useUIStore.getState().setActivePanel("workspace");
        } else if (e.key === "3") {
          e.preventDefault();
          useUIStore.getState().setActivePanel("both");
        } else if (e.key === "4") {
          e.preventDefault();
          useUIStore.getState().setActivePanel("catalog");
        } else if (e.key === "b") {
          e.preventDefault();
          useUIStore.getState().toggleChatSidebar();
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const clampSplitRatio = useCallback((ratio: number) => {
    const container = splitContainerRef.current;
    if (!container) {
      return Math.min(Math.max(ratio, 0.2), 0.8);
    }

    const width = container.getBoundingClientRect().width;
    if (width <= 0) {
      return Math.min(Math.max(ratio, 0.2), 0.8);
    }

    const minRatio = Math.min(MIN_SPLIT_PANEL_WIDTH / width, 0.5);
    return Math.min(Math.max(ratio, minRatio), 1 - minRatio);
  }, []);

  const updateSplitFromClientX = useCallback(
    (clientX: number) => {
      const container = splitContainerRef.current;
      if (!container) {
        return;
      }

      const rect = container.getBoundingClientRect();
      if (rect.width <= 0) {
        return;
      }

      setChatCanvasSplitRatio(clampSplitRatio((clientX - rect.left) / rect.width));
    },
    [clampSplitRatio, setChatCanvasSplitRatio]
  );

  useEffect(() => {
    if (!isResizingSplit) {
      return;
    }

    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const handlePointerMove = (event: globalThis.PointerEvent) => {
      event.preventDefault();
      updateSplitFromClientX(event.clientX);
    };
    const stopResizing = () => setIsResizingSplit(false);

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", stopResizing);
    window.addEventListener("pointercancel", stopResizing);

    return () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopResizing);
      window.removeEventListener("pointercancel", stopResizing);
    };
  }, [isResizingSplit, updateSplitFromClientX]);

  const handleSplitPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) {
      return;
    }

    event.preventDefault();
    setIsResizingSplit(true);
    updateSplitFromClientX(event.clientX);
  };

  const handleSplitKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
      return;
    }

    event.preventDefault();
    const direction = event.key === "ArrowLeft" ? -1 : 1;
    setChatCanvasSplitRatio(clampSplitRatio(chatCanvasSplitRatio + direction * SPLIT_KEYBOARD_STEP));
  };

  if (workspaceListQuery.isLoading && workspaces.length === 0) {
    return (
      <div className="flex h-[100dvh] w-screen items-center justify-center bg-parchment">
        <p className="text-body text-stone-gray">{t("app.loadingWorkspaces")}</p>
      </div>
    );
  }

  if (workspaceListQuery.isSuccess && workspaces.length === 0) {
    return (
      <WorkspaceOnboardingGate
        isSubmitting={createWorkspace.isPending}
        onCreate={(name) => createWorkspace.mutate({ title: name })}
      />
    );
  }

  return (
    <div className="flex h-[100dvh] w-screen overflow-hidden bg-parchment">
      {chatSidebarOpen && <GlobalSidebar />}

      <div ref={splitContainerRef} className="flex flex-1 min-w-0 overflow-hidden">
        {activePanel === "catalog" && (
          <div className="flex flex-1 flex-col overflow-hidden bg-parchment">
            <WorkspaceCatalogPage />
          </div>
        )}

        {(activePanel === "chat" || activePanel === "both") && (
          <div
            className={cn(
              "flex flex-col bg-ivory overflow-hidden",
              activePanel === "both" ? "min-w-0 shrink-0" : "flex-1"
            )}
            style={
              activePanel === "both"
                ? {
                    flexBasis: `${chatCanvasSplitRatio * 100}%`,
                  }
                : undefined
            }
          >
            <ChatPanel />
          </div>
        )}

        {activePanel === "both" && (
          <div
            aria-label={t("app.resizeChatCanvas")}
            aria-orientation="vertical"
            aria-valuemax={100}
            aria-valuemin={0}
            aria-valuenow={Math.round(chatCanvasSplitRatio * 100)}
            className={cn(
              "group relative z-20 flex w-3 shrink-0 cursor-col-resize items-stretch justify-center bg-ivory outline-none transition-colors focus-visible:ring-2 focus-visible:ring-focus-blue",
              isResizingSplit && "bg-warm-sand"
            )}
            data-testid="chat-canvas-resizer"
            onKeyDown={handleSplitKeyDown}
            onPointerDown={handleSplitPointerDown}
            role="separator"
            tabIndex={0}
          >
            <span
              className={cn(
                "h-full w-px bg-border-warm transition-colors group-hover:bg-terracotta group-focus-visible:bg-terracotta",
                isResizingSplit && "bg-terracotta"
              )}
            />
          </div>
        )}

        {(activePanel === "workspace" || activePanel === "both") && (
          <div
            className={cn(
              "flex flex-col bg-parchment overflow-hidden",
              activePanel === "both" ? "min-w-0 flex-1" : "flex-1"
            )}
          >
            {catalogOverlayInWorkspace ? (
              <WorkspaceCatalogPage onClose={() => setCatalogOverlayInWorkspace(false)} />
            ) : (
              <WorkspacePanel />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
