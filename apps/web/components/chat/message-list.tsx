"use client";

import { useRef, useEffect } from "react";
import { useChatStore } from "@/stores/chat-store";
import { MessageItem } from "./message-item";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useUIStore } from "@/stores/ui-store";
import { Brain } from "lucide-react";
import { useI18n } from "@/lib/i18n/context";

const EMPTY_MESSAGES: ReturnType<typeof useChatStore.getState>["messagesBySession"][string] = [];

function ThinkingDots() {
  return (
    <span className="flex items-center gap-0.5">
      <span className="w-1 h-1 rounded-full bg-stone-gray animate-bounce" style={{ animationDelay: "0ms" }} />
      <span className="w-1 h-1 rounded-full bg-stone-gray animate-bounce" style={{ animationDelay: "160ms" }} />
      <span className="w-1 h-1 rounded-full bg-stone-gray animate-bounce" style={{ animationDelay: "320ms" }} />
    </span>
  );
}

export function MessageList({ sessionId }: { sessionId: string }) {
  const { t } = useI18n();
  const messages = useChatStore((s) => s.messagesBySession[sessionId] ?? EMPTY_MESSAGES);
  const isSending = useUIStore((s) => Boolean(s.sendingBySession[sessionId]));
  // Hide the fallback indicator once AgentTrace is live in the placeholder message
  const hasLiveTrace = useChatStore((s) => {
    const msgs = s.messagesBySession[sessionId] ?? EMPTY_MESSAGES;
    return msgs.some((m) => s.traceByMessageId[m.id]?.state === "live");
  });
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, isSending]);

  return (
    <ScrollArea className="h-full">
      <div className="flex flex-col gap-1 px-4 py-4">
        {messages.length === 0 && !isSending ? (
          <div className="text-center py-12">
            <p className="text-body text-stone-gray">
              {t("chat.messagesEmpty")}
            </p>
          </div>
        ) : (
          messages.map((message) => (
            <MessageItem key={message.id} message={message} />
          ))
        )}

        {isSending && !hasLiveTrace && (
          <div className="flex items-center gap-3 py-3">
            <div className="w-8 h-8 rounded-full bg-warm-sand flex items-center justify-center shrink-0">
              <Brain className="w-4 h-4 text-terracotta" />
            </div>
            <span className="text-[11px] text-stone-gray select-none">{t("chat.thinking")}</span>
            <ThinkingDots />
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </ScrollArea>
  );
}
