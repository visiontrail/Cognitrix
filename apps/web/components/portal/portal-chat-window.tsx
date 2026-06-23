"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  BotMessageSquare,
  ArrowUp,
  X,
  Plus,
  Trash2,
  MessageSquare,
  ChevronLeft,
  Sparkles,
} from "lucide-react";
import { sendPortalChatMessage } from "@/lib/portal/chat";
import { useI18n } from "@/lib/i18n/context";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/utils";
import { generateId } from "@/lib/utils";

// ─── Types ───────────────────────────────────────────────────────────────────

type ChatMessage = {
  role: "user" | "assistant";
  text: string;
  createdAt: string;
};

type ChatSession = {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: string;
  updatedAt: string;
  pageId: string;
};

// ─── localStorage helpers ─────────────────────────────────────────────────────

function storageKey(pageId: string) {
  return `portal:chat-sessions:${pageId}`;
}

function loadSessions(pageId: string): ChatSession[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(storageKey(pageId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? (parsed as ChatSession[]) : [];
  } catch {
    return [];
  }
}

function persistSessions(pageId: string, sessions: ChatSession[]) {
  try {
    localStorage.setItem(storageKey(pageId), JSON.stringify(sessions));
  } catch {}
}

function createSession(pageId: string): ChatSession {
  const now = new Date().toISOString();
  return { id: generateId(), title: "", messages: [], createdAt: now, updatedAt: now, pageId };
}

// ─── Component ────────────────────────────────────────────────────────────────

export function PortalChatWindow({
  pageId,
  activeChartId,
  activeChartTitle,
  onClearChart,
  onClose,
}: {
  pageId: string;
  activeChartId: string | null;
  activeChartTitle?: string;
  onClearChart: () => void;
  onClose: () => void;
}) {
  const { t, locale } = useI18n();

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [hoveredSessionId, setHoveredSessionId] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Load / initialise sessions from localStorage on mount or pageId change
  useEffect(() => {
    const stored = loadSessions(pageId);
    if (stored.length > 0) {
      setSessions(stored);
      setActiveSessionId(stored[0].id);
    } else {
      const fresh = createSession(pageId);
      setSessions([fresh]);
      setActiveSessionId(fresh.id);
      persistSessions(pageId, [fresh]);
    }
    setDraft("");
  }, [pageId]);

  const activeSession = sessions.find((s) => s.id === activeSessionId) ?? null;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeSession?.messages, sending]);

  // ── Session management ──────────────────────────────────────────────────────

  const handleNewSession = useCallback(() => {
    const fresh = createSession(pageId);
    setSessions((prev) => {
      const next = [fresh, ...prev];
      persistSessions(pageId, next);
      return next;
    });
    setActiveSessionId(fresh.id);
    setDraft("");
    textareaRef.current?.focus();
  }, [pageId]);

  const handleDeleteSession = useCallback(
    (sessionId: string, e: React.MouseEvent) => {
      e.stopPropagation();
      setSessions((prev) => {
        const next = prev.filter((s) => s.id !== sessionId);
        persistSessions(pageId, next);

        if (activeSessionId === sessionId) {
          if (next.length > 0) {
            setActiveSessionId(next[0].id);
          } else {
            const fresh = createSession(pageId);
            persistSessions(pageId, [fresh]);
            setSessions([fresh]);
            setActiveSessionId(fresh.id);
            return [fresh];
          }
        }
        return next;
      });
    },
    [pageId, activeSessionId],
  );

  const updateSession = useCallback(
    (sessionId: string, updater: (s: ChatSession) => ChatSession) => {
      setSessions((prev) => {
        const next = prev.map((s) => (s.id === sessionId ? updater(s) : s));
        // bubble updated session to top
        const idx = next.findIndex((s) => s.id === sessionId);
        if (idx > 0) {
          const [item] = next.splice(idx, 1);
          next.unshift(item);
        }
        persistSessions(pageId, next);
        return next;
      });
    },
    [pageId],
  );

  // ── Sending ─────────────────────────────────────────────────────────────────

  const send = useCallback(async () => {
    const message = draft.trim();
    if (!message || sending || !activeSessionId) return;

    setDraft("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    setSending(true);

    const userMsg: ChatMessage = { role: "user", text: message, createdAt: new Date().toISOString() };

    updateSession(activeSessionId, (s) => ({
      ...s,
      title: s.title || message.slice(0, 50),
      messages: [...s.messages, userMsg],
      updatedAt: new Date().toISOString(),
    }));

    try {
      const events = await sendPortalChatMessage(pageId, message, { chartId: activeChartId });
      const final = events.find((e) => e.type === "final");
      const text = typeof final?.payload.text === "string" ? final.payload.text : t("portal.chatDone");
      const assistantMsg: ChatMessage = { role: "assistant", text, createdAt: new Date().toISOString() };
      updateSession(activeSessionId, (s) => ({
        ...s,
        messages: [...s.messages, assistantMsg],
        updatedAt: new Date().toISOString(),
      }));
    } catch {
      const errMsg: ChatMessage = {
        role: "assistant",
        text: t("portal.chatUnableToAnswer"),
        createdAt: new Date().toISOString(),
      };
      updateSession(activeSessionId, (s) => ({
        ...s,
        messages: [...s.messages, errMsg],
        updatedAt: new Date().toISOString(),
      }));
    } finally {
      setSending(false);
    }
  }, [draft, sending, activeSessionId, pageId, activeChartId, t, updateSession]);

  // ─── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full min-h-0 w-full min-w-0 flex-1">
      {/* ── Left: Session history sidebar ───────────────────────────────── */}
      <aside className="flex h-full w-60 shrink-0 flex-col border-r border-[#e2dccf] bg-[#f0ece2]">
        {/* Sidebar header */}
        <div className="flex shrink-0 items-center gap-2.5 border-b border-[#e2dccf] px-4 py-3.5">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[#996b35]/15">
            <Sparkles className="h-3.5 w-3.5 text-[#996b35]" />
          </div>
          <span className="text-sm font-semibold text-[#2f332f]">{t("portal.aiAssistant")}</span>
        </div>

        {/* New chat button */}
        <div className="shrink-0 px-3 pt-3 pb-2">
          <button
            type="button"
            onClick={handleNewSession}
            className="flex w-full items-center gap-2 rounded-lg border border-[#d8d1c1] bg-white px-3 py-2 text-sm font-medium text-[#2f332f] shadow-sm transition-colors hover:border-[#ad7d3d] hover:bg-[#faf6f0]"
          >
            <Plus className="h-3.5 w-3.5 shrink-0 text-[#996b35]" />
            {t("portal.newChat")}
          </button>
        </div>

        {/* Session list label */}
        <div className="shrink-0 px-4 pb-1 pt-2">
          <span className="text-[11px] font-medium uppercase tracking-wider text-[#9e9383]">
            {t("portal.chatHistory")}
          </span>
        </div>

        {/* Session list */}
        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
          {sessions.length === 0 ? (
            <p className="px-2 py-4 text-center text-xs text-[#b0a898]">{t("portal.chatNoHistory")}</p>
          ) : (
            sessions.map((session) => {
              const isActive = session.id === activeSessionId;
              const isHovered = session.id === hoveredSessionId;
              const displayTitle = session.title || t("portal.chatSessionDefault");

              return (
                <div
                  key={session.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => setActiveSessionId(session.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") setActiveSessionId(session.id);
                  }}
                  onMouseEnter={() => setHoveredSessionId(session.id)}
                  onMouseLeave={() => setHoveredSessionId(null)}
                  className={cn(
                    "group relative mb-0.5 flex w-full cursor-pointer items-start gap-2.5 rounded-lg px-3 py-2.5 text-left transition-colors",
                    isActive
                      ? "bg-white shadow-sm"
                      : "hover:bg-[#e8e2d6]",
                  )}
                >
                  <MessageSquare
                    className={cn(
                      "mt-0.5 h-3.5 w-3.5 shrink-0",
                      isActive ? "text-[#996b35]" : "text-[#b0a898]",
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <p
                      className={cn(
                        "truncate text-sm leading-snug",
                        isActive ? "font-medium text-[#2f332f]" : "text-[#4a4a3f]",
                      )}
                    >
                      {displayTitle}
                    </p>
                    <p className="mt-0.5 text-[11px] text-[#b0a898]">
                      {formatRelativeTime(new Date(session.updatedAt), locale)}
                    </p>
                  </div>
                  {/* Delete button */}
                  {(isActive || isHovered) && (
                    <button
                      type="button"
                      onClick={(e) => handleDeleteSession(session.id, e)}
                      aria-label={t("portal.chatDeleteSession")}
                      className="mt-0.5 shrink-0 rounded p-0.5 text-[#b0a898] opacity-0 transition-opacity group-hover:opacity-100 hover:bg-[#f0ece2] hover:text-[#e05a5a]"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Back to workspace */}
        <div className="shrink-0 border-t border-[#e2dccf] px-3 py-2.5">
          <button
            type="button"
            onClick={onClose}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-[#777166] transition-colors hover:bg-[#e8e2d6] hover:text-[#2f332f]"
          >
            <ChevronLeft className="h-4 w-4 shrink-0" />
            {t("portal.chatBackToPortal")}
          </button>
        </div>
      </aside>

      {/* ── Right: Chat conversation ─────────────────────────────────────── */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-white">
        {/* Conversation header */}
        <header className="flex shrink-0 items-center gap-3 border-b border-[#eee8dc] px-5 py-3">
          <div className="min-w-0 flex-1">
            {activeChartId ? (
              <p className="flex items-center gap-1.5 truncate text-sm text-[#777166]">
                <span className="font-medium text-[#2f332f]">{t("portal.chatContextChart")}</span>
                <span className="truncate">{activeChartTitle || activeChartId}</span>
                <button
                  onClick={onClearChart}
                  className="ml-1 shrink-0 text-xs underline underline-offset-2 hover:text-[#2f332f]"
                >
                  {t("portal.chatClearChart")}
                </button>
              </p>
            ) : (
              <p className="text-sm font-medium text-[#2f332f]">{t("portal.chatContextPage")}</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="shrink-0 rounded-md p-1.5 text-[#777166] transition-colors hover:bg-[#f3eadb] hover:text-[#2f332f]"
            aria-label={t("portal.chatCloseAriaLabel")}
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {/* Messages */}
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
          {!activeSession || activeSession.messages.length === 0 ? (
            /* Empty state */
            <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
              <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-[#996b35]/10">
                <BotMessageSquare className="h-8 w-8 text-[#996b35]" />
              </div>
              <div className="space-y-1">
                <p className="text-base font-semibold text-[#2f332f]">{t("portal.chatEmptyTitle")}</p>
                <p className="max-w-xs text-sm leading-relaxed text-[#777166]">
                  {t("portal.chatEmptyDesc")}
                </p>
              </div>
            </div>
          ) : (
            <div className="mx-auto max-w-2xl space-y-6">
              {activeSession.messages.map((msg, i) => (
                <div
                  key={i}
                  className={cn(
                    "flex items-end gap-3",
                    msg.role === "user" ? "flex-row-reverse" : "flex-row",
                  )}
                >
                  {msg.role === "assistant" && (
                    <div className="mb-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#996b35]/10">
                      <BotMessageSquare className="h-3.5 w-3.5 text-[#996b35]" />
                    </div>
                  )}
                  <div
                    className={cn(
                      "max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed",
                      msg.role === "user"
                        ? "rounded-br-sm bg-[#2f332f] text-white whitespace-pre-wrap"
                        : "rounded-bl-sm border border-[#eee8dc] bg-[#f7f4eb] text-[#2f332f]",
                    )}
                  >
                    {msg.role === "user" ? (
                      msg.text
                    ) : (
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                          h1: ({ children }) => <h1 className="text-base font-semibold mb-2 mt-2 first:mt-0">{children}</h1>,
                          h2: ({ children }) => <h2 className="text-sm font-semibold mb-1 mt-2 first:mt-0">{children}</h2>,
                          h3: ({ children }) => <h3 className="text-sm font-semibold mb-1 mt-2 first:mt-0">{children}</h3>,
                          ul: ({ children }) => <ul className="list-disc list-outside pl-4 mb-2 space-y-0.5">{children}</ul>,
                          ol: ({ children }) => <ol className="list-decimal list-outside pl-4 mb-2 space-y-0.5">{children}</ol>,
                          li: ({ children }) => <li>{children}</li>,
                          code: ({ inline, children, ...props }: { inline?: boolean; children?: React.ReactNode }) =>
                            inline ? (
                              <code className="bg-[#eee8dc] text-[#996b35] rounded px-1 text-[0.8em] font-mono" {...props}>{children}</code>
                            ) : (
                              <code className="block bg-[#2f332f] text-white rounded px-3 py-2 text-[0.8em] font-mono overflow-x-auto my-2" {...props}>{children}</code>
                            ),
                          pre: ({ children }) => <>{children}</>,
                          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                        }}
                      >
                        {msg.text}
                      </ReactMarkdown>
                    )}
                  </div>
                </div>
              ))}

              {/* Typing indicator */}
              {sending && (
                <div className="flex items-end gap-3">
                  <div className="mb-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#996b35]/10">
                    <BotMessageSquare className="h-3.5 w-3.5 text-[#996b35]" />
                  </div>
                  <div className="rounded-2xl rounded-bl-sm border border-[#eee8dc] bg-[#f7f4eb] px-4 py-3.5">
                    <span className="flex items-center gap-1.5">
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#996b35]/60 [animation-delay:0ms]" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#996b35]/60 [animation-delay:150ms]" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#996b35]/60 [animation-delay:300ms]" />
                    </span>
                  </div>
                </div>
              )}

              <div ref={bottomRef} />
            </div>
          )}
        </div>

        {/* Input area */}
        <div className="shrink-0 border-t border-[#eee8dc] px-6 py-4">
          <div className="mx-auto max-w-2xl">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void send();
              }}
              className="relative rounded-xl border border-[#d8d1c1] bg-[#fbfaf5] px-4 py-3 transition-colors focus-within:border-[#ad7d3d] focus-within:bg-white"
            >
              <textarea
                ref={textareaRef}
                value={draft}
                onChange={(e) => {
                  setDraft(e.target.value);
                  e.target.style.height = "auto";
                  e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send();
                  }
                }}
                placeholder={t("portal.chatPlaceholder")}
                rows={1}
                className="w-full resize-none bg-transparent pr-10 text-sm text-[#2f332f] placeholder:text-[#b0a898] focus:outline-none"
                autoFocus
              />
              <button
                type="submit"
                disabled={sending || !draft.trim()}
                className="absolute bottom-2.5 right-3 flex h-7 w-7 items-center justify-center rounded-lg bg-[#2f332f] text-white transition-all hover:bg-[#444a44] disabled:opacity-25"
                aria-label={t("chat.send")}
              >
                <ArrowUp className="h-3.5 w-3.5" />
              </button>
            </form>
            <p className="mt-2 text-center text-[10px] text-[#b0a898]">{t("portal.chatHint")}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
