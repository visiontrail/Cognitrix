"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { PublicCanvasActions } from "@/components/public/public-canvas-actions";
import { PublicPageGrid } from "@/components/public/public-page-grid";
import { PublicPageSidebar } from "@/components/public/public-page-sidebar";
import { PublishedFixedCanvas, PublishedFreeCanvas } from "@/components/public/published-canvas-renderers";
import {
  fetchPublicManifest,
  PublicPageError,
  type PublicManifestResponse,
} from "@/lib/public/api";
import { useI18n } from "@/lib/i18n/context";
import { useTheme } from "@/lib/theme/context";
import { Button } from "@/components/ui/button";

type LoadState = "loading" | "ready" | "invalid" | "auth_required" | "forbidden";

export function PublicPageClient({ token }: { token: string }) {
  const { t } = useI18n();
  const { resolvedTheme } = useTheme();
  const webPageCanvasRef = useRef<HTMLDivElement | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [page, setPage] = useState<PublicManifestResponse | null>(null);
  const [activePageId, setActivePageId] = useState<string | undefined>();

  useEffect(() => {
    let cancelled = false;
    setState("loading");
    fetchPublicManifest(token)
      .then((payload) => {
        if (cancelled) return;
        if (!isSupportedManifest(payload.manifest)) {
          setState("invalid");
          return;
        }
        setPage(payload);
        if ((payload.manifest.canvas?.kind ?? "web_page") === "web_page") {
          const firstSidebarPageId =
            payload.manifest.sidebar?.[0]?.pageId ?? payload.manifest.sidebar?.[0]?.id;
          setActivePageId(
            payload.manifest.layout.activePageId ??
              payload.manifest.layout.pages?.[0]?.id ??
              firstSidebarPageId
          );
        }
        setState("ready");
      })
      .catch((error) => {
        if (cancelled) return;
        if (error instanceof PublicPageError) {
          if (error.code === "authentication_required") {
            setState("auth_required");
            return;
          }
          if (error.code === "forbidden") {
            setState("forbidden");
            return;
          }
        }
        // Neutral failure: never reveal whether the link ever existed.
        setState("invalid");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (state === "loading") {
    return (
      <div className="flex h-screen items-center justify-center bg-[#f7f4eb] text-sm text-[#777166] dark:bg-[#111115] dark:text-gray-300">
        {t("public.loading")}
      </div>
    );
  }

  if (state === "invalid" || !page) {
    if (state === "auth_required") {
      const next = encodeURIComponent(`/p/${token}`);
      return (
        <div className="flex h-screen flex-col items-center justify-center gap-3 bg-[#f7f4eb] text-center dark:bg-[#111115]">
          <p className="font-medium text-[#2f332f] dark:text-white">{t("public.loginRequiredTitle")}</p>
          <p className="max-w-sm text-sm text-[#777166] dark:text-gray-300">{t("public.loginRequiredDesc")}</p>
          <Button asChild>
            <Link href={`/login?next=${next}`}>{t("public.loginAction")}</Link>
          </Button>
        </div>
      );
    }

    if (state === "forbidden") {
      return (
        <div className="flex h-screen flex-col items-center justify-center gap-3 bg-[#f7f4eb] text-center dark:bg-[#111115]">
          <p className="font-medium text-[#2f332f] dark:text-white">{t("public.forbiddenTitle")}</p>
          <p className="max-w-sm text-sm text-[#777166] dark:text-gray-300">{t("public.forbiddenDesc")}</p>
          <Button asChild>
            <Link href="/">{t("public.backToWorkspace")}</Link>
          </Button>
        </div>
      );
    }

    return (
      <div className="flex h-screen flex-col items-center justify-center gap-2 bg-[#f7f4eb] text-center dark:bg-[#111115]">
        <p className="font-medium text-[#2f332f] dark:text-white">{t("public.invalidTitle")}</p>
        <p className="text-sm text-[#777166] dark:text-gray-300">{t("public.invalidDesc")}</p>
      </div>
    );
  }

  const canvasKind = page.manifest.canvas?.kind ?? "web_page";
  const filenameBase = `published-canvas-v${page.version}`;
  if (canvasKind === "free_layout") {
    return <PublishedFreeCanvas token={token} manifest={page.manifest} filenameBase={filenameBase} />;
  }
  if (canvasKind === "fixed_size") {
    return <PublishedFixedCanvas token={token} manifest={page.manifest} filenameBase={filenameBase} />;
  }

  return (
    <div className="flex h-screen min-h-0 overflow-hidden bg-[#f7f4eb] text-[#2f332f] dark:bg-[#111115] dark:text-white">
      <PublicPageSidebar
        items={page.manifest.sidebar || []}
        activePageId={activePageId}
        onSelectPage={setActivePageId}
      />
      <main className="relative flex min-h-0 min-w-0 flex-1">
        <PublicCanvasActions
          getCanvasElement={() => webPageCanvasRef.current}
          filenameBase={filenameBase}
          className="absolute right-5 top-5"
          captureOptions={{ backgroundColor: resolvedTheme === "dark" ? "#111115" : "#ffffff" }}
        />
        <PublicPageGrid
          token={token}
          manifest={page.manifest}
          activePageId={activePageId}
          captureRef={webPageCanvasRef}
        />
      </main>
    </div>
  );
}

function isSupportedManifest(manifest: PublicManifestResponse["manifest"]): boolean {
  const kind = manifest.canvas?.kind ?? "web_page";
  const supportedKinds = ["free_layout", "fixed_size", "web_page"];
  if (!supportedKinds.includes(kind)) return false;
  if (kind === "fixed_size") {
    return Boolean(manifest.canvas?.page?.width && manifest.canvas.page.height);
  }
  if (kind === "web_page") {
    return Boolean(manifest.layout?.grid?.rows);
  }
  return Array.isArray(manifest.content?.nodes);
}
