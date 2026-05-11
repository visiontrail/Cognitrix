"use client";

import { useChatStore } from "@/stores/chat-store";
import { useChatMessages, useCreateSession } from "@/hooks/use-chat";
import { MessageList } from "./message-list";
import { ChatInput } from "./chat-input";
import { ChatEmptyState } from "./chat-empty-state";
import { PanelLeftOpen, MessageSquarePlus, LayoutDashboard } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useUIStore } from "@/stores/ui-store";
import { useWorkspaceStore } from "@/stores/workspace-store";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/lib/i18n/context";

export function ChatPanel() {
  const { t } = useI18n();
  const activeSessionId = useChatStore((s) => s.activeSessionId);
  const activePanel = useUIStore((s) => s.activePanel);
  const chatSidebarOpen = useUIStore((s) => s.chatSidebarOpen);
  const setChatSidebarOpen = useUIStore((s) => s.setChatSidebarOpen);
  const setActivePanel = useUIStore((s) => s.setActivePanel);
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId);
  const activeWorkspaceTitle = useWorkspaceStore((s) => {
    const workspace = s.workspaces.find((item) => item.id === s.activeWorkspaceId);
    return workspace?.title ?? null;
  });
  const createSession = useCreateSession();
  const isCanvasVisible = activePanel === "both";

  const { isLoading } = useChatMessages(activeSessionId);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-border-cream bg-ivory shrink-0">
        <div className="flex items-center gap-2">
          {!chatSidebarOpen && (
            <Button variant="ghost" size="icon-sm" onClick={() => setChatSidebarOpen(true)}>
              <PanelLeftOpen className="w-4 h-4" />
            </Button>
          )}
          <div>
            <h2 className="font-serif text-feature text-near-black">
              {activeSessionId ? <SessionTitle sessionId={activeSessionId} /> : t("chat.title")}
            </h2>
            <p className="text-label text-stone-gray">
              {t("chat.subtitle")}
            </p>
            <p className="text-label text-stone-gray/90">
              {t("chat.workspaceLabel", {
                name: activeWorkspaceTitle ?? (activeWorkspaceId ? activeWorkspaceId : t("chat.workspaceUnselected")),
              })}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setActivePanel(isCanvasVisible ? "chat" : "both")}
          >
            <LayoutDashboard className="w-4 h-4" />
            {isCanvasVisible ? t("chat.hideCanvas") : t("chat.showCanvas")}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => createSession.mutate(undefined)}
            disabled={createSession.isPending || !activeWorkspaceId}
          >
            <MessageSquarePlus className="w-4 h-4" />
            {t("chat.newChat")}
          </Button>
        </div>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-hidden">
        {!activeSessionId ? (
          <ChatEmptyState />
        ) : isLoading ? (
          <div className="p-6 space-y-4">
            <Skeleton className="h-16 w-3/4" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-16 w-2/3" />
          </div>
        ) : (
          <MessageList sessionId={activeSessionId} />
        )}
      </div>

      {/* Input */}
      {activeSessionId && <ChatInput sessionId={activeSessionId} />}
    </div>
  );
}

function SessionTitle({ sessionId }: { sessionId: string }) {
  const { t } = useI18n();
  const session = useChatStore((s) => s.sessions.find((s) => s.id === sessionId));
  return <>{session?.title ?? t("chat.sessionFallbackTitle")}</>;
}
