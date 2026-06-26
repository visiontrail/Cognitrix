"use client";

import type { ChatMessage } from "@/types/chat";
import { ChartMessageCard, MultiChartMessageGroup } from "./chart-message-card";
import { MultiChartConfirmationBox } from "./multi-chart-confirmation-box";
import { AgentTrace } from "./agent-trace";
import { SavedPromptEditorDialog } from "./saved-prompts/saved-prompt-editor-dialog";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { copyTextToClipboard } from "@/lib/clipboard";
import { useI18n } from "@/lib/i18n/context";
import { Bot, BookmarkPlus, Copy, User } from "lucide-react";
import { cn } from "@/lib/utils";
import { useMemo, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";

export function MessageItem({ message }: { message: ChatMessage }) {
  const { t } = useI18n();
  const isUser = message.role === "user";
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const derivedPromptName = useMemo(
    () => derivePromptName(message.content, t("savedPrompts.history.defaultName")),
    [message.content, t]
  );

  const handleCopyPrompt = async () => {
    const copied = await copyTextToClipboard(message.content);
    if (copied) {
      toast.success(t("savedPrompts.history.copySuccess"));
      return;
    }
    toast.error(t("savedPrompts.history.copyFailed"));
  };

  return (
    <div
      className={cn(
        "flex gap-3 py-3 animate-fade-in",
        isUser ? "flex-row-reverse" : "flex-row"
      )}
    >
      {/* Avatar */}
      <div
        className={cn(
          "shrink-0 w-8 h-8 rounded-full flex items-center justify-center",
          isUser ? "bg-near-black" : "bg-warm-sand"
        )}
      >
        {isUser ? (
          <User className="w-4 h-4 text-ivory" />
        ) : (
          <Bot className="w-4 h-4 text-terracotta" />
        )}
      </div>

      {/* Content */}
      <div
        className={cn(
          "group/message max-w-[85%] flex flex-col space-y-3",
          isUser ? "items-end" : "items-start"
        )}
      >
        {/* Agent Trace — shown above the text bubble for assistant messages */}
        {!isUser && (
          <AgentTrace
            messageId={message.id}
            traceSummary={message.traceSummary}
            generationOptions={message.generationOptions}
          />
        )}

        {/* Text Bubble — hidden while content is empty (placeholder during streaming) */}
        {message.content && (
          <div
            className={cn(
              "rounded-very px-4 py-3",
              isUser
                ? "bg-near-black text-ivory rounded-tr-subtle"
                : "bg-ivory border border-border-cream text-near-black rounded-tl-subtle shadow-whisper"
            )}
          >
            {isUser ? (
              <p className="text-body-sm leading-relaxed whitespace-pre-wrap">
                {message.content}
              </p>
            ) : (
              <div className="text-body-sm leading-relaxed">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                  h1: ({ children }) => <h1 className="text-lg font-semibold mb-2 mt-3 first:mt-0">{children}</h1>,
                  h2: ({ children }) => <h2 className="text-base font-semibold mb-2 mt-3 first:mt-0">{children}</h2>,
                  h3: ({ children }) => <h3 className="text-sm font-semibold mb-1 mt-2 first:mt-0">{children}</h3>,
                  ul: ({ children }) => <ul className="list-disc list-outside pl-4 mb-2 space-y-0.5">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal list-outside pl-4 mb-2 space-y-0.5">{children}</ol>,
                  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
                  code: ({ inline, children, ...props }: { inline?: boolean; children?: ReactNode }) =>
                    inline ? (
                      <code className="bg-warm-sand/60 text-terracotta rounded px-1 py-0.5 text-[0.8em] font-mono" {...props}>
                        {children}
                      </code>
                    ) : (
                      <code className="block bg-near-black text-ivory rounded-md px-3 py-2 text-[0.8em] font-mono overflow-x-auto my-2" {...props}>
                        {children}
                      </code>
                    ),
                  pre: ({ children }) => <>{children}</>,
                  blockquote: ({ children }) => (
                    <blockquote className="border-l-2 border-terracotta/40 pl-3 italic text-stone-gray my-2">
                      {children}
                    </blockquote>
                  ),
                  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                  em: ({ children }) => <em className="italic">{children}</em>,
                  hr: () => <hr className="border-border-cream my-3" />,
                  table: ({ children }) => (
                    <div className="overflow-x-auto my-2">
                      <table className="text-xs border-collapse w-full">{children}</table>
                    </div>
                  ),
                  th: ({ children }) => (
                    <th className="border border-border-cream bg-warm-sand/40 px-2 py-1 text-left font-semibold">
                      {children}
                    </th>
                  ),
                  td: ({ children }) => (
                    <td className="border border-border-cream px-2 py-1">{children}</td>
                  ),
                }}
              >
                {message.content}
              </ReactMarkdown>
              </div>
            )}
          </div>
        )}

        {isUser && message.content ? (
          <div
            className={cn(
              "flex h-7 items-center justify-end gap-1 pr-1",
              "opacity-0 transition-opacity duration-150",
              "group-hover/message:opacity-100 group-focus-within/message:opacity-100"
            )}
          >
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  className="h-7 w-7 rounded-full text-stone-gray hover:bg-parchment hover:text-near-black"
                  onClick={() => setSaveDialogOpen(true)}
                  aria-label={t("savedPrompts.history.saveAria")}
                >
                  <BookmarkPlus className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("savedPrompts.history.saveTooltip")}</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  className="h-7 w-7 rounded-full text-stone-gray hover:bg-parchment hover:text-near-black"
                  onClick={handleCopyPrompt}
                  aria-label={t("savedPrompts.history.copyAria")}
                >
                  <Copy className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("savedPrompts.history.copyTooltip")}</TooltipContent>
            </Tooltip>
          </div>
        ) : null}

        {message.multiChartConfirmation && !isUser && (
          <MultiChartConfirmationBox
            sessionId={message.sessionId}
            confirmation={message.multiChartConfirmation}
          />
        )}

        {/* Chart Card */}
        {message.chartAssets && message.chartAssets.length > 1 && !isUser ? (
          <MultiChartMessageGroup assets={message.chartAssets} />
        ) : message.chartAsset && !isUser ? (
          <ChartMessageCard
            assetId={message.chartAsset.assetId}
            title={message.chartAsset.title}
            chartType={message.chartAsset.chartType}
          />
        ) : null}
      </div>

      {isUser && saveDialogOpen ? (
        <SavedPromptEditorDialog
          open={saveDialogOpen}
          prompt={null}
          initialName={derivedPromptName}
          initialBody={message.content}
          onOpenChange={setSaveDialogOpen}
          onSaved={() => toast.success(t("savedPrompts.history.saveSuccess"))}
        />
      ) : null}
    </div>
  );
}

function derivePromptName(content: string, fallback: string) {
  const normalized = content.trim().replace(/\s+/g, " ");
  if (!normalized) return fallback;
  return normalized.length > 56 ? `${normalized.slice(0, 56).trimEnd()}...` : normalized;
}
