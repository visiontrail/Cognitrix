"use client";

import { PanelLeftOpen, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useI18n } from "@/lib/i18n/context";
import { useUIStore } from "@/stores/ui-store";
import { useWorkspaceStore } from "@/stores/workspace-store";
import { WorkspaceCatalogReadonly } from "./workspace-catalog-readonly";
import { WorkspaceEmptyState } from "./workspace-empty-state";

export function WorkspaceCatalogPage({ onClose }: { onClose?: () => void }) {
  const { t } = useI18n();
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId);
  const activeWorkspaceTitle = useWorkspaceStore((s) => {
    const workspace = s.workspaces.find((item) => item.id === s.activeWorkspaceId);
    return workspace?.title ?? null;
  });
  const chatSidebarOpen = useUIStore((s) => s.chatSidebarOpen);
  const setChatSidebarOpen = useUIStore((s) => s.setChatSidebarOpen);
  const setActivePanel = useUIStore((s) => s.setActivePanel);

  const handleClose = onClose ?? (() => setActivePanel("both"));

  if (!activeWorkspaceId) {
    return <WorkspaceEmptyState />;
  }

  return (
    <div className="flex h-full flex-col bg-parchment">
      <header className="flex shrink-0 items-center justify-between gap-4 border-b border-border-cream bg-ivory px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          {!chatSidebarOpen && (
            <Button variant="ghost" size="icon-sm" onClick={() => setChatSidebarOpen(true)}>
              <PanelLeftOpen className="h-4 w-4" />
            </Button>
          )}
          <div className="min-w-0">
            <h1 className="font-serif text-feature text-near-black">
              {t("workspace.catalog.title")}
            </h1>
            <p className="truncate text-label text-stone-gray">
              {t("workspace.catalog.boundWorkspace", {
                workspace: activeWorkspaceTitle ?? activeWorkspaceId,
              })}
            </p>
          </div>
        </div>

        <Button variant="ghost" size="icon-sm" onClick={handleClose} aria-label={t("workspace.catalog.close")}>
          <X className="h-4 w-4" />
        </Button>
      </header>

      <ScrollArea className="flex-1">
        <main className="mx-auto w-full max-w-6xl px-6 py-6">
          <WorkspaceCatalogReadonly workspaceId={activeWorkspaceId} showHeader={false} />
        </main>
      </ScrollArea>
    </div>
  );
}
