"use client";

import type { ChatMessage } from "@/types/chat";
import { ChartMessageCard } from "./chart-message-card";
import { AgentTrace } from "./agent-trace";
import { User, Bot } from "lucide-react";
import { cn } from "@/lib/utils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function MessageItem({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

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
          "max-w-[85%] space-y-3",
          isUser ? "items-end" : "items-start"
        )}
      >
        {/* Agent Trace — shown above the text bubble for assistant messages */}
        {!isUser && (
          <AgentTrace messageId={message.id} traceSummary={message.traceSummary} />
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
                  code: ({ inline, children, ...props }: { inline?: boolean; children?: React.ReactNode }) =>
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

        {/* Chart Card */}
        {message.chartAsset && !isUser && (
          <ChartMessageCard
            assetId={message.chartAsset.assetId}
            title={message.chartAsset.title}
            chartType={message.chartAsset.chartType}
          />
        )}
      </div>
    </div>
  );
}
