"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  MessageSquare,
  LayoutDashboard,
  Plus,
  PanelLeftClose,
  Pencil,
  Trash2,
  BarChart3,
  Columns2,
  Table2,
  LogOut,
  Globe,
  Monitor,
  Moon,
  Sun,
  ChevronUp,
  Check,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuGroup,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
} from "@/components/ui/dropdown-menu";
import { useChatStore } from "@/stores/chat-store";
import { useAssetStore } from "@/stores/asset-store";
import { useWorkspaceStore } from "@/stores/workspace-store";
import { useUIStore } from "@/stores/ui-store";
import { chatSessionsQueryKey, useCreateSession, useDeleteSession } from "@/hooks/use-chat";
import { syncSessionToServer } from "@/lib/chat/server-sync";
import { useCreateWorkspace, useDeleteWorkspace } from "@/hooks/use-workspace";
import { useI18n } from "@/lib/i18n/context";
import { useTheme, type ThemeMode } from "@/lib/theme/context";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/utils";
import { useSession } from "@/lib/auth/use-session";
import { apiLogout } from "@/lib/auth/auth-client";
import { clearInMemoryToken } from "@/lib/auth/session";

export function GlobalSidebar() {
  const { t, locale, setLocale } = useI18n();
  const { mode: themeMode, setMode: setThemeMode } = useTheme();
  const queryClient = useQueryClient();
  const { user } = useSession();

  async function handleLogout() {
    await apiLogout().catch(() => {});
    clearInMemoryToken();
    useChatStore.getState().clearForUser();
    useAssetStore.getState().clearForUser();
    window.location.href = "/login";
  }

  const sessions = useChatStore((s) => s.sessions);
  const activeSessionId = useChatStore((s) => s.activeSessionId);
  const setActiveSession = useChatStore((s) => s.setActiveSession);
  const renameSession = useChatStore((s) => s.renameSession);

  const workspaces = useWorkspaceStore((s) => s.workspaces);
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId);
  const setActiveWorkspace = useWorkspaceStore((s) => s.setActiveWorkspace);

  const activePanel = useUIStore((s) => s.activePanel);
  const setActivePanel = useUIStore((s) => s.setActivePanel);
  const toggleChatSidebar = useUIStore((s) => s.toggleChatSidebar);

  const createSession = useCreateSession();
  const deleteSession = useDeleteSession();
  const createWorkspace = useCreateWorkspace();
  const deleteWorkspace = useDeleteWorkspace();

  // Typed-confirmation modal for hard-delete. The user must retype the
  // workspace name; the server-side guardrail will also reject mismatches,
  // but we shortcut the round-trip here to keep the UX honest.
  const [deleteConfirmTarget, setDeleteConfirmTarget] = useState<{ id: string; title: string } | null>(null);
  const [deleteConfirmInput, setDeleteConfirmInput] = useState("");
  const deleteConfirmInputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (deleteConfirmTarget) {
      setDeleteConfirmInput("");
      requestAnimationFrame(() => deleteConfirmInputRef.current?.focus());
    }
  }, [deleteConfirmTarget?.id]);

  const handleNewChat = () => {
    createSession.mutate(undefined);
    if (activePanel === "workspace") setActivePanel("both");
    if (activePanel === "catalog") setActivePanel("chat");
  };

  const handleNewWorkspace = () => {
    createWorkspace.mutate({ title: t("workspace.defaultUntitled") });
    if (activePanel === "chat") setActivePanel("both");
  };

  const handleSelectSession = (sessionId: string) => {
    setActiveSession(sessionId);
    if (activePanel === "workspace") setActivePanel("both");
    if (activePanel === "catalog") setActivePanel("chat");
  };

  const handleSelectWorkspace = (workspaceId: string) => {
    setActiveWorkspace(workspaceId);
    if (activePanel === "chat") setActivePanel("both");
  };

  const handleRenameSession = (sessionId: string, nextTitle: string) => {
    renameSession(sessionId, nextTitle);
    if (activeWorkspaceId) {
      void syncSessionToServer(activeWorkspaceId, sessionId);
    }
    queryClient.invalidateQueries({ queryKey: chatSessionsQueryKey(activeWorkspaceId) });
  };

  return (
    <>
    <aside className="flex flex-col w-sidebar min-w-sidebar border-r border-border-cream bg-ivory h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-cream">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-terracotta" />
          <div className="flex flex-col leading-tight">
            <h1 className="font-serif text-feature text-near-black">Cognitrix</h1>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" onClick={toggleChatSidebar}>
                <PanelLeftClose className="w-4 h-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("sidebar.hideSidebar")}</TooltipContent>
          </Tooltip>
        </div>
      </div>

      <nav className="grid grid-cols-4 gap-1 border-b border-border-cream px-3 py-2">
        <PanelButton
          active={activePanel === "chat"}
          label={t("sidebar.panel.chat")}
          onClick={() => setActivePanel("chat")}
          icon={<MessageSquare className="h-4 w-4" />}
        />
        <PanelButton
          active={activePanel === "workspace"}
          label={t("sidebar.panel.canvas")}
          onClick={() => setActivePanel("workspace")}
          icon={<LayoutDashboard className="h-4 w-4" />}
        />
        <PanelButton
          active={activePanel === "both"}
          label={t("sidebar.panel.split")}
          onClick={() => setActivePanel("both")}
          icon={<Columns2 className="h-4 w-4" />}
        />
        <PanelButton
          active={activePanel === "catalog"}
          label={t("sidebar.panel.catalog")}
          onClick={() => setActivePanel("catalog")}
          icon={<Table2 className="h-4 w-4" />}
        />
      </nav>

      <div className="grid min-h-0 flex-1 grid-rows-[7fr_3fr]">
        {/* Chat Sessions — fixed upper ~70% with independent scroll */}
        <div className="flex min-h-0 min-w-0 flex-col border-b border-border-cream">
          <div className="flex shrink-0 items-center justify-between px-3 pr-5 pt-3 pb-2">
            <span className="text-label text-stone-gray uppercase tracking-wider font-medium">
              {t("sidebar.section.conversations")}
            </span>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t("sidebar.action.newConversation")}
                  onClick={handleNewChat}
                  disabled={createSession.isPending || !activeWorkspaceId}
                  className="h-6 w-6 rounded-subtle border border-ring-warm bg-ivory text-near-black shadow-ring-warm hover:bg-warm-sand hover:text-near-black"
                >
                  <Plus className="w-3.5 h-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("sidebar.action.newConversation")}</TooltipContent>
            </Tooltip>
          </div>
          <ScrollArea className="min-h-0 flex-1">
            <div className="space-y-0.5 px-3 pr-5 pb-3">
              {sessions.length === 0 ? (
                <p className="text-caption text-stone-gray px-2 py-3">{t("sidebar.emptyConversations")}</p>
              ) : (
                sessions.map((session) => (
                  <SidebarItem
                    key={session.id}
                    active={session.id === activeSessionId}
                    icon={<MessageSquare className="w-4 h-4" />}
                    title={session.title}
                    subtitle={formatRelativeTime(new Date(session.updatedAt), locale)}
                    onClick={() => handleSelectSession(session.id)}
                    onDelete={() => deleteSession.mutate(session.id)}
                    deleteAriaLabel={t("sidebar.deleteConversation", { title: session.title })}
                    onRename={(nextTitle) => handleRenameSession(session.id, nextTitle)}
                    renameAriaLabel={t("sidebar.renameConversation", { title: session.title })}
                    renameInputAriaLabel={t("sidebar.renameConversationInput")}
                    renameSaveAriaLabel={t("sidebar.renameConversationSave")}
                    renameCancelAriaLabel={t("sidebar.renameConversationCancel")}
                  />
                ))
              )}
            </div>
          </ScrollArea>
        </div>

        {/* Workspaces — fixed lower ~30% with independent scroll */}
        <div className="flex min-h-0 min-w-0 flex-col">
          <div className="flex shrink-0 items-center justify-between px-3 pr-5 pt-3 pb-2">
            <span className="text-label text-stone-gray uppercase tracking-wider font-medium">
              {t("sidebar.section.workspaces")}
            </span>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t("sidebar.action.newWorkspace")}
                  onClick={handleNewWorkspace}
                  disabled={createWorkspace.isPending}
                  className="h-6 w-6 rounded-subtle border border-ring-warm bg-ivory text-near-black shadow-ring-warm hover:bg-warm-sand hover:text-near-black"
                >
                  <Plus className="w-3.5 h-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("sidebar.action.newWorkspace")}</TooltipContent>
            </Tooltip>
          </div>
          <ScrollArea className="min-h-0 flex-1">
            <div className="space-y-0.5 px-3 pr-5 pb-3">
              {workspaces.length === 0 ? (
                <p className="text-caption text-stone-gray px-2 py-3">{t("sidebar.emptyWorkspaces")}</p>
              ) : (
                workspaces.map((ws) => (
                  <SidebarItem
                    key={ws.id}
                    active={ws.id === activeWorkspaceId}
                    icon={<LayoutDashboard className="w-4 h-4" />}
                    title={ws.title}
                    subtitle={t("sidebar.itemCount", { count: ws.nodeCount })}
                    onClick={() => handleSelectWorkspace(ws.id)}
                    onDelete={
                      canDeleteWorkspace(ws.role)
                        ? () => setDeleteConfirmTarget({ id: ws.id, title: ws.title })
                        : undefined
                    }
                    deleteAriaLabel={
                      canDeleteWorkspace(ws.role)
                        ? t("sidebar.deleteWorkspace", { title: ws.title })
                        : undefined
                    }
                  />
                ))
              )}
            </div>
          </ScrollArea>
        </div>
      </div>

      {/* Footer */}
      <div className="border-t border-border-cream px-3 py-2">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="w-full flex items-center gap-2.5 px-2 py-2 rounded-comfortable hover:bg-warm-sand transition-colors group"
            >
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-terracotta text-white text-body-sm font-semibold select-none">
                {user?.display_name ? user.display_name.charAt(0).toUpperCase() : "?"}
              </div>
              <div className="flex-1 min-w-0 text-left">
                <p className="text-body-sm font-medium truncate text-near-black">
                  {user?.display_name ?? ""}
                </p>
                <p className="text-label text-stone-gray truncate">{t("sidebar.footerTagline")}</p>
              </div>
              <ChevronUp className="w-4 h-4 text-stone-gray shrink-0 group-data-[state=open]:rotate-180 transition-transform" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            side="top"
            align="start"
            sideOffset={6}
            className="w-64"
          >
            {/* User email header */}
            <div className="px-2 py-1.5 mb-1">
              <p className="text-label text-stone-gray truncate">{user?.email ?? ""}</p>
            </div>
            <DropdownMenuSeparator />

            {/* Theme submenu */}
            <DropdownMenuSub>
              <DropdownMenuSubTrigger>
                <Monitor className="w-4 h-4" />
                {t("theme.label")}
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent className="w-64">
                <ThemeMenuItem
                  mode="system"
                  activeMode={themeMode}
                  label={t("theme.system")}
                  icon={<Monitor className="w-4 h-4" />}
                  onSelect={setThemeMode}
                />
                <ThemeMenuItem
                  mode="light"
                  activeMode={themeMode}
                  label={t("theme.light")}
                  icon={<Sun className="w-4 h-4" />}
                  onSelect={setThemeMode}
                />
                <ThemeMenuItem
                  mode="dark"
                  activeMode={themeMode}
                  label={t("theme.dark")}
                  icon={<Moon className="w-4 h-4" />}
                  onSelect={setThemeMode}
                />
              </DropdownMenuSubContent>
            </DropdownMenuSub>

            {/* Language submenu */}
            <DropdownMenuSub>
              <DropdownMenuSubTrigger>
                <Globe className="w-4 h-4" />
                {t("language.label")}
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent className="w-64">
                <DropdownMenuItem onSelect={() => setLocale("en-US")}>
                  {t("language.en")}
                  {locale === "en-US" && <Check className="ml-auto w-4 h-4" />}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => setLocale("zh-CN")}>
                  {t("language.zh")}
                  {locale === "zh-CN" && <Check className="ml-auto w-4 h-4" />}
                </DropdownMenuItem>
              </DropdownMenuSubContent>
            </DropdownMenuSub>

            <DropdownMenuSeparator />

            {/* Logout */}
            <DropdownMenuItem
              onSelect={handleLogout}
              className="text-error-crimson focus:text-error-crimson focus:bg-error-crimson/10"
            >
              <LogOut className="w-4 h-4" />
              {t("auth.logout")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </aside>
    <Dialog
      open={deleteConfirmTarget !== null}
      onOpenChange={(open) => {
        if (!open) {
          setDeleteConfirmTarget(null);
          setDeleteConfirmInput("");
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("workspace.delete.confirmTitle")}</DialogTitle>
          <DialogDescription>
            {t("workspace.delete.confirmBody", { title: deleteConfirmTarget?.title ?? "" })}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <label
            htmlFor="workspace-delete-confirm-input"
            className="text-caption text-stone-gray"
          >
            {t("workspace.delete.confirmPromptLabel")}
          </label>
          <input
            id="workspace-delete-confirm-input"
            ref={deleteConfirmInputRef}
            value={deleteConfirmInput}
            onChange={(e) => setDeleteConfirmInput(e.target.value)}
            placeholder={t("workspace.delete.confirmInputPlaceholder")}
            className="w-full rounded-subtle border border-border-cream bg-warm-sand/40 px-3 py-2 text-body-sm text-near-black focus:outline-none focus:ring-2 focus:ring-error-crimson/40"
          />
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <Button
            variant="outline"
            type="button"
            onClick={() => {
              setDeleteConfirmTarget(null);
              setDeleteConfirmInput("");
            }}
            disabled={deleteWorkspace.isPending}
          >
            {t("workspace.delete.cancelButton")}
          </Button>
          <Button
            variant="destructive"
            type="button"
            disabled={
              !deleteConfirmTarget ||
              deleteConfirmInput.trim() !== (deleteConfirmTarget?.title ?? "").trim() ||
              deleteWorkspace.isPending
            }
            onClick={() => {
              if (!deleteConfirmTarget) return;
              deleteWorkspace.mutate(
                {
                  workspaceId: deleteConfirmTarget.id,
                  confirmWorkspaceName: deleteConfirmTarget.title,
                },
                {
                  onSettled: () => {
                    setDeleteConfirmTarget(null);
                    setDeleteConfirmInput("");
                  },
                }
              );
            }}
          >
            {t("workspace.delete.confirmButton")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
    </>
  );
}

function ThemeMenuItem({
  mode,
  activeMode,
  label,
  icon,
  onSelect,
}: {
  mode: ThemeMode;
  activeMode: ThemeMode;
  label: string;
  icon: React.ReactNode;
  onSelect: (mode: ThemeMode) => void;
}) {
  return (
    <DropdownMenuItem onSelect={() => onSelect(mode)}>
      {icon}
      {label}
      {activeMode === mode && <Check className="ml-auto w-4 h-4" />}
    </DropdownMenuItem>
  );
}

function PanelButton({
  active,
  icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={label}
          aria-pressed={active}
          onClick={onClick}
          className={cn(
            "flex h-9 items-center justify-center rounded-comfortable border transition-colors",
            active
              ? "border-ring-warm bg-warm-sand text-terracotta shadow-ring-warm"
              : "border-transparent text-stone-gray hover:border-border-cream hover:bg-parchment hover:text-near-black"
          )}
        >
          {icon}
        </button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

function SidebarItem({
  active,
  icon,
  title,
  subtitle,
  onClick,
  onDelete,
  deleteAriaLabel,
  onRename,
  renameAriaLabel,
  renameInputAriaLabel,
  renameSaveAriaLabel,
  renameCancelAriaLabel,
}: {
  active: boolean;
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  onClick: () => void;
  onDelete?: () => void;
  deleteAriaLabel?: string;
  onRename?: (nextTitle: string) => void;
  renameAriaLabel?: string;
  renameInputAriaLabel?: string;
  renameSaveAriaLabel?: string;
  renameCancelAriaLabel?: string;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(title);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!isEditing) {
      setDraft(title);
    }
  }, [title, isEditing]);

  useEffect(() => {
    if (isEditing) {
      const node = inputRef.current;
      if (node) {
        node.focus();
        node.select();
      }
    }
  }, [isEditing]);

  const startRename = () => {
    setDraft(title);
    setIsEditing(true);
  };

  const cancelRename = () => {
    setDraft(title);
    setIsEditing(false);
  };

  const commitRename = () => {
    const trimmed = draft.trim();
    if (!trimmed || trimmed === title) {
      cancelRename();
      return;
    }
    onRename?.(trimmed);
    setIsEditing(false);
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => {
        if (isEditing) return;
        onClick();
      }}
      onKeyDown={(e) => {
        if (isEditing) return;
        if (e.key === "Enter" || e.key === " ") onClick();
      }}
      className={cn(
        "group grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2.5 px-2 py-2 rounded-comfortable transition-colors overflow-hidden",
        isEditing ? "cursor-default" : "cursor-pointer",
        active
          ? "bg-warm-sand text-near-black shadow-ring-warm"
          : "text-olive-gray hover:bg-border-cream hover:text-near-black"
      )}
    >
      <span className={cn("shrink-0", active ? "text-terracotta" : "text-stone-gray")}>
        {icon}
      </span>
      <div className="flex-1 min-w-0">
        {isEditing ? (
          <input
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              e.stopPropagation();
              if (e.key === "Enter") {
                e.preventDefault();
                commitRename();
              } else if (e.key === "Escape") {
                e.preventDefault();
                cancelRename();
              }
            }}
            onBlur={commitRename}
            aria-label={renameInputAriaLabel ?? "Rename"}
            className="w-full rounded-subtle border border-ring-warm bg-ivory px-1.5 py-0.5 text-body-sm font-medium text-near-black focus:outline-none focus:ring-1 focus:ring-terracotta"
            maxLength={120}
          />
        ) : (
          <p className="text-body-sm font-medium truncate" title={title}>
            {title}
          </p>
        )}
        <p className="text-label text-stone-gray truncate" title={subtitle}>
          {subtitle}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-0.5">
        {isEditing ? (
          <>
            <button
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={(e) => {
                e.stopPropagation();
                commitRename();
              }}
              className="p-1 rounded-subtle text-stone-gray hover:bg-warm-sand hover:text-terracotta focus-visible:text-terracotta transition-colors"
              aria-label={renameSaveAriaLabel ?? "Save"}
            >
              <Check className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={(e) => {
                e.stopPropagation();
                cancelRename();
              }}
              className="p-1 rounded-subtle text-stone-gray hover:bg-warm-sand hover:text-near-black focus-visible:text-near-black transition-colors"
              aria-label={renameCancelAriaLabel ?? "Cancel"}
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </>
        ) : (
          <>
            {onRename && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  startRename();
                }}
                className="p-1 rounded-subtle text-stone-gray hover:bg-warm-sand hover:text-terracotta focus-visible:text-terracotta transition-colors"
                aria-label={renameAriaLabel ?? "Rename"}
              >
                <Pencil className="w-3.5 h-3.5" />
              </button>
            )}
            {onDelete && deleteAriaLabel && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete();
                }}
                className="opacity-100 p-1 rounded-subtle text-stone-gray hover:bg-error-crimson/10 hover:text-error-crimson focus-visible:text-error-crimson transition-colors"
                aria-label={deleteAriaLabel}
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function canDeleteWorkspace(role: string | undefined): boolean {
  return role === "owner" || role === "admin";
}
