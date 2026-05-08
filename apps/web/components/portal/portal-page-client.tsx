"use client";

import { useEffect, useState, useCallback } from "react";
import { PortalChatWindow } from "@/components/portal/portal-chat-window";
import { PortalWorkspaceSidebar } from "@/components/portal/portal-workspace-sidebar";
import { PublishedPageGrid } from "@/components/portal/published-page-grid";
import { PublishedPageSidebar } from "@/components/portal/published-page-sidebar";
import {
  fetchPortalManifest,
  fetchPortalWorkspaces,
  PortalError,
  type PortalManifestResponse,
  type PortalWorkspace,
} from "@/lib/portal/api";
import { useI18n } from "@/lib/i18n/context";
import { setStoredAppMode } from "@/lib/auth/session";

export function PortalPageClient({ initialPageId }: { initialPageId?: string }) {
  const { t } = useI18n();
  const [workspaces, setWorkspaces] = useState<PortalWorkspace[]>([]);
  const [pageId, setPageId] = useState<string | null>(initialPageId || null);
  const [page, setPage] = useState<PortalManifestResponse | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [activePublishedPageId, setActivePublishedPageId] = useState<string | undefined>();
  const [activeChartId, setActiveChartId] = useState<string | null>(null);
  const [activeChartTitle, setActiveChartTitle] = useState<string | undefined>();
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [showChat, setShowChat] = useState(false);

  const openDesigner = () => {
    setStoredAppMode("designer");
    window.location.href = "/";
  };

  const openChat = useCallback(() => setShowChat(true), []);

  useEffect(() => {
    setStoredAppMode("viewer");
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "o") {
        e.preventDefault();
        setShowChat(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  useEffect(() => {
    fetchPortalWorkspaces()
      .then((items) => {
        setWorkspaces(items);
        setWorkspaceError(null);
        if (!pageId && items[0]) setPageId(items[0].latest_page_id);
      })
      .catch((err) => {
        if (err instanceof PortalError && err.status === 401) {
          window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
        } else {
          setWorkspaceError(t("portal.loadError"));
        }
      });
  }, [pageId]);

  useEffect(() => {
    if (!pageId) return;
    setPageError(null);
    fetchPortalManifest(pageId)
      .then((payload) => {
        setPage(payload);
        const firstSidebarPageId = payload.manifest.sidebar?.[0]?.pageId ?? payload.manifest.sidebar?.[0]?.id;
        setActivePublishedPageId(
          payload.manifest.layout.activePageId ??
            payload.manifest.layout.pages?.[0]?.id ??
            firstSidebarPageId
        );
        setActiveChartId(null);
        setActiveChartTitle(undefined);
      })
      .catch((err) => {
        if (err instanceof PortalError && err.code === "page_not_visible") {
          setPageError("no_access");
        } else {
          setPageError("error");
        }
        setPage(null);
      });
  }, [pageId]);

  return (
    <div className="flex h-screen min-h-0 overflow-hidden bg-[#f7f4eb] text-[#2f332f]">
      <PortalWorkspaceSidebar
        workspaces={workspaces}
        activePageId={pageId}
        onSelect={setPageId}
        onOpenDesigner={openDesigner}
        onOpenChat={openChat}
      />
      <main className="relative flex min-h-0 min-w-0 flex-1">
        {workspaces.length === 0 && !workspaceError ? (
          <div className="flex flex-1 items-center justify-center text-sm text-[#777166]">
            {t("portal.emptyList")}
          </div>
        ) : pageError === "no_access" ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2">
            <p className="font-medium text-[#777166]">{t("portal.noAccess")}</p>
            <p className="text-sm text-[#777166]">{t("portal.noAccessDesc")}</p>
          </div>
        ) : !page ? (
          <div className="flex flex-1 items-center justify-center text-sm text-[#777166]">
            {t("portal.selectWorkspace")}
          </div>
        ) : (
          <>
            {showChat ? (
              <PortalChatWindow
                pageId={page.page_id}
                activeChartId={activeChartId}
                activeChartTitle={activeChartTitle}
                onClearChart={() => {
                  setActiveChartId(null);
                  setActiveChartTitle(undefined);
                }}
                onClose={() => setShowChat(false)}
              />
            ) : (
              <>
                <PublishedPageSidebar
                  items={page.manifest.sidebar || []}
                  activePageId={activePublishedPageId}
                  onSelectPage={(nextPageId) => {
                    setActivePublishedPageId(nextPageId);
                    setActiveChartId(null);
                    setActiveChartTitle(undefined);
                  }}
                />
                <PublishedPageGrid
                  pageId={page.page_id}
                  manifest={page.manifest}
                  activePageId={activePublishedPageId}
                  activeChartId={activeChartId}
                  onSelectChart={(chartId, title) => {
                    setActiveChartId(chartId);
                    setActiveChartTitle(title);
                  }}
                />
              </>
            )}
          </>
        )}
      </main>
    </div>
  );
}
