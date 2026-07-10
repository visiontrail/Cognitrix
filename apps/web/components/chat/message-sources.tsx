"use client";

import type { MessageSource } from "@/types/chat";
import { useI18n } from "@/lib/i18n/context";
import { ExternalLink } from "lucide-react";

function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function MessageSources({ sources }: { sources?: MessageSource[] }) {
  const { t } = useI18n();
  if (!sources || sources.length === 0) {
    return null;
  }
  const ordered = [...sources].sort((a, b) => a.id - b.id);

  return (
    <div className="w-full rounded-very border border-border-cream bg-ivory/60 px-3 py-2.5 shadow-whisper">
      <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-stone-gray">
        {t("chat.sources.title")}
      </p>
      <ol className="space-y-1">
        {ordered.map((source) => (
          <li key={`${source.id}-${source.url}`} className="flex items-baseline gap-2 text-body-sm">
            <span className="shrink-0 tabular-nums text-stone-gray">[{source.id}]</span>
            <a
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
              className="group inline-flex min-w-0 items-baseline gap-1 text-near-black hover:text-terracotta"
            >
              <span className="truncate">{source.title}</span>
              <span className="shrink-0 text-stone-gray">· {domainOf(source.url)}</span>
              <ExternalLink className="h-3 w-3 shrink-0 self-center opacity-0 transition-opacity group-hover:opacity-100" />
            </a>
          </li>
        ))}
      </ol>
    </div>
  );
}
