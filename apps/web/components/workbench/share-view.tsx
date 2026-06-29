"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Moon, Sun } from "lucide-react";

import { GenUIRegistry } from "../genui/registry";
import { EmptyPanel, ErrorPanel, SkeletonPanel } from "../genui/state-panels";
import { getAuthorizationHeader } from "../../lib/auth/session";
import { useI18n } from "@/lib/i18n/context";
import { useTheme } from "@/lib/theme/context";

type ShareViewProps = {
  apiBaseUrl: string;
  viewId: string;
};

type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
};

type SharePayload = {
  view_id: string;
  title: string;
  current_version: number;
  owner_user_id: string;
  updated_at: string;
  ai_state: Record<string, unknown>;
};

export function ShareView({ apiBaseUrl, viewId }: ShareViewProps) {
  const { t } = useI18n();
  const [payload, setPayload] = useState<SharePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchPayload() {
      setLoading(true);
      setError(null);
      try {
        const authorizationHeader = await getAuthorizationHeader(apiBaseUrl, {
          userId: "share-viewer",
          projectId: "shared-views",
          role: "viewer",
          department: null,
          clearance: 0
        });
        const response = await fetch(`${apiBaseUrl}/share/${encodeURIComponent(viewId)}`, {
          headers: authorizationHeader
        });
        const body = (await response.json()) as SharePayload | { detail?: { message?: string } };

        if (!response.ok) {
          if (!cancelled) {
            const detail =
              isRecord(body) && "detail" in body && isRecord((body as { detail?: unknown }).detail)
                ? ((body as { detail: { message?: string } }).detail ?? null)
                : null;
            setError(String(detail?.message ?? `load_failed_${response.status}`));
          }
          return;
        }

        if (!cancelled) {
          setPayload(body as SharePayload);
        }
      } catch (fetchError) {
        if (!cancelled) {
          setError(fetchError instanceof Error ? fetchError.message : "load_failed");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void fetchPayload();

    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl, viewId]);

  const activeSpec = useMemo(() => {
    if (!payload || !isRecord(payload.ai_state)) {
      return null;
    }
    return payload.ai_state.active_spec ?? payload.ai_state.chart_spec ?? null;
  }, [payload]);

  const messages = useMemo<Message[]>(() => {
    if (!payload || !isRecord(payload.ai_state)) {
      return [];
    }

    const raw = payload.ai_state.messages;
    if (!Array.isArray(raw)) {
      return [];
    }

    return raw
      .filter(isRecord)
      .map((item, index) => {
        const role: Message["role"] = item.role === "user" ? "user" : "assistant";
        return {
          id: String(item.id ?? `msg-${index}`),
          role,
          text: String(item.text ?? "")
        };
      })
      .filter((item) => item.text.length > 0);
  }, [payload]);

  if (loading) {
    return (
      <ShareViewShell title={t("share.title")} description={t("share.loading")}>
        <SkeletonPanel />
      </ShareViewShell>
    );
  }

  if (error) {
    return (
      <ShareViewShell title={t("share.title")}>
        <ErrorPanel description={error} />
      </ShareViewShell>
    );
  }

  if (!payload) {
    return (
      <ShareViewShell title={t("share.title")}>
        <EmptyPanel title={t("share.notFound")} />
      </ShareViewShell>
    );
  }

  return (
    <ShareViewShell
      title={payload.title}
      description={t("share.viewMeta", { viewId: payload.view_id, version: payload.current_version })}
    >
      <section className="rounded-md border border-border-cream bg-ivory/80 px-4 py-3 text-body-sm text-olive-gray shadow-ring-border dark:border-white/10 dark:bg-white/[0.06] dark:text-gray-300">
        <strong>{t("share.owner")}</strong> {payload.owner_user_id}
        <br />
        <strong>{t("share.updated")}</strong> {payload.updated_at}
      </section>

      {activeSpec ? <GenUIRegistry rawSpec={activeSpec} /> : <EmptyPanel title={t("share.noSpec")} />}

      <section className="space-y-3 rounded-md border border-border-cream bg-ivory/80 p-4 shadow-ring-border dark:border-white/10 dark:bg-white/[0.06]">
        <h2 className="text-xl">{t("share.savedConversation")}</h2>
        {messages.length ? (
          <ul className="space-y-2 text-body-sm text-charcoal-warm dark:text-gray-200">
            {messages.map((message) => (
              <li key={message.id} className="rounded-md bg-parchment/60 px-3 py-2 dark:bg-black/20">
                <strong className="text-near-black dark:text-white">
                  {message.role === "user" ? t("share.you") : t("share.ai")}:
                </strong>{" "}
                {message.text}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-body-sm text-stone-gray dark:text-gray-300">{t("share.noMessages")}</p>
        )}
      </section>
    </ShareViewShell>
  );
}

function ShareViewShell({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <main className="min-h-screen bg-parchment px-4 py-6 text-near-black dark:bg-[#111115] dark:text-white sm:px-8">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
        <header className="flex flex-wrap items-start justify-between gap-4 border-b border-border-cream pb-5 dark:border-white/10">
          <div className="min-w-0 space-y-1">
            <h1 className="break-words text-3xl sm:text-4xl">{title}</h1>
            {description ? <p className="text-body-sm text-olive-gray dark:text-gray-300">{description}</p> : null}
          </div>
          <ShareThemeToggle />
        </header>
        {children}
      </div>
    </main>
  );
}

function ShareThemeToggle() {
  const { t } = useI18n();
  const { mode, setMode } = useTheme();
  const nextMode = mode === "dark" ? "light" : "dark";
  const label = mode === "dark" ? t("share.themeSwitchToLight") : t("share.themeSwitchToDark");

  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={mode === "dark"}
      title={label}
      onClick={() => setMode(nextMode)}
      className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-border-cream bg-ivory text-olive-gray shadow-ring-border transition-colors hover:bg-warm-sand hover:text-near-black dark:border-white/15 dark:bg-white/[0.08] dark:text-gray-200 dark:hover:bg-white/[0.14] dark:hover:text-white"
    >
      {mode === "dark" ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
    </button>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
