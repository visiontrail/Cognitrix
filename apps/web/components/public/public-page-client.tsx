"use client";

import { useEffect, useState } from "react";
import { PublicPageGrid } from "@/components/public/public-page-grid";
import { PublicPageSidebar } from "@/components/public/public-page-sidebar";
import {
  fetchPublicManifest,
  type PublicManifestResponse,
} from "@/lib/public/api";
import { useI18n } from "@/lib/i18n/context";

type LoadState = "loading" | "ready" | "invalid";

export function PublicPageClient({ token }: { token: string }) {
  const { t } = useI18n();
  const [state, setState] = useState<LoadState>("loading");
  const [page, setPage] = useState<PublicManifestResponse | null>(null);
  const [activePageId, setActivePageId] = useState<string | undefined>();

  useEffect(() => {
    let cancelled = false;
    setState("loading");
    fetchPublicManifest(token)
      .then((payload) => {
        if (cancelled) return;
        setPage(payload);
        const firstSidebarPageId =
          payload.manifest.sidebar?.[0]?.pageId ?? payload.manifest.sidebar?.[0]?.id;
        setActivePageId(
          payload.manifest.layout.activePageId ??
            payload.manifest.layout.pages?.[0]?.id ??
            firstSidebarPageId
        );
        setState("ready");
      })
      .catch(() => {
        if (cancelled) return;
        // Neutral failure: never reveal whether the link ever existed.
        setState("invalid");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (state === "loading") {
    return (
      <div className="flex h-screen items-center justify-center bg-[#f7f4eb] text-sm text-[#777166]">
        {t("public.loading")}
      </div>
    );
  }

  if (state === "invalid" || !page) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-2 bg-[#f7f4eb] text-center">
        <p className="font-medium text-[#2f332f]">{t("public.invalidTitle")}</p>
        <p className="text-sm text-[#777166]">{t("public.invalidDesc")}</p>
      </div>
    );
  }

  return (
    <div className="flex h-screen min-h-0 overflow-hidden bg-[#f7f4eb] text-[#2f332f]">
      <PublicPageSidebar
        items={page.manifest.sidebar || []}
        activePageId={activePageId}
        onSelectPage={setActivePageId}
      />
      <main className="relative flex min-h-0 min-w-0 flex-1">
        <PublicPageGrid token={token} manifest={page.manifest} activePageId={activePageId} />
      </main>
    </div>
  );
}
