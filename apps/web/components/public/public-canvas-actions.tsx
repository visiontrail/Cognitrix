"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  Bot,
  Check,
  ChevronDown,
  Download,
  FileImage,
  FileText,
  Globe,
  Home,
  Loader2,
  LogIn,
  LogOut,
  Moon,
  Printer,
  Sun,
  UserRound,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  exportPublicCanvasToPdf,
  exportPublicCanvasToPng,
  printPublicCanvas,
} from "@/lib/public/canvas-export";
import { useI18n } from "@/lib/i18n/context";
import { useTheme } from "@/lib/theme/context";
import { cn } from "@/lib/utils";
import { apiGetMe, apiLogout, type UserInfo } from "@/lib/auth/auth-client";
import { clearInMemoryToken, getInMemoryToken } from "@/lib/auth/session";
import { useAssetStore } from "@/stores/asset-store";
import { useChatStore } from "@/stores/chat-store";

type PublicCanvasActionsProps = {
  getCanvasElement: () => HTMLElement | null;
  filenameBase: string;
  allowPdf?: boolean;
  captureOptions?: {
    backgroundColor?: string;
    width?: number;
    height?: number;
    style?: Partial<CSSStyleDeclaration>;
  };
  assistantAvailable?: boolean;
  onOpenAssistant?: () => void;
  assistantOffsetRight?: number;
  className?: string;
};

export function PublicCanvasActions({
  getCanvasElement,
  filenameBase,
  allowPdf = false,
  captureOptions,
  assistantAvailable = false,
  onOpenAssistant,
  assistantOffsetRight = 0,
  className,
}: PublicCanvasActionsProps) {
  const { t } = useI18n();
  const { mode, setMode } = useTheme();
  const [busyAction, setBusyAction] = useState<"png" | "pdf" | "print" | null>(null);
  const nextThemeMode = mode === "dark" ? "light" : "dark";
  const themeLabel =
    mode === "dark" ? t("public.canvas.themeSwitchToLight") : t("public.canvas.themeSwitchToDark");

  const withCanvas = useCallback(
    async (action: "png" | "pdf" | "print", run: (element: HTMLElement) => Promise<void>) => {
      const element = getCanvasElement();
      if (!element) {
        toast.error(t("public.canvas.exportError"));
        return;
      }
      setBusyAction(action);
      try {
        await run(element);
        if (action !== "print") {
          toast.success(t("public.canvas.exportSuccess"));
        }
      } catch {
        toast.error(action === "print" ? t("public.canvas.printError") : t("public.canvas.exportError"));
      } finally {
        setBusyAction(null);
      }
    },
    [getCanvasElement, t]
  );

  const handleExportPng = useCallback(() => {
    void withCanvas("png", (element) => exportPublicCanvasToPng(element, filenameBase, captureOptions));
  }, [captureOptions, filenameBase, withCanvas]);

  const handleExportPdf = useCallback(() => {
    void withCanvas("pdf", (element) => exportPublicCanvasToPdf(element, filenameBase, captureOptions));
  }, [captureOptions, filenameBase, withCanvas]);

  const handlePrint = useCallback(() => {
    void withCanvas("print", (element) => printPublicCanvas(element, filenameBase, captureOptions));
  }, [captureOptions, filenameBase, withCanvas]);

  const isBusy = busyAction !== null;
  const triggerIcon =
    busyAction === "png" || busyAction === "pdf" ? (
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
    ) : (
      <Download className="h-4 w-4" aria-hidden="true" />
    );

  return (
    <TooltipProvider delayDuration={300}>
      <div
        className={cn(
          "z-20 flex items-center gap-1 rounded-md border border-[#d8d1c1] bg-white/95 p-1 shadow-sm backdrop-blur dark:border-white/15 dark:bg-[#1c1c38]/90",
          className
        )}
        style={
          assistantOffsetRight > 0 ? { transform: `translateX(-${assistantOffsetRight}px)` } : undefined
        }
        data-public-canvas-control
        data-public-canvas-export-ignore
      >
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              asChild
              variant="ghost"
              size="sm"
              aria-label={t("public.canvas.backToApp")}
              className="h-8 px-2 text-[#3f3d39] hover:bg-[#f3eadc] dark:text-white dark:hover:bg-white/10"
            >
              <Link href="/">
                <Home className="h-4 w-4" aria-hidden="true" />
                <span className="hidden sm:inline">{t("public.canvas.backToAppShort")}</span>
              </Link>
            </Button>
          </TooltipTrigger>
          <TooltipContent>{t("public.canvas.backToApp")}</TooltipContent>
        </Tooltip>
        {allowPdf ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={isBusy}
                aria-label={t("public.canvas.export")}
                className="h-8 px-2 text-[#3f3d39] hover:bg-[#f3eadc] dark:text-white dark:hover:bg-white/10"
              >
                {triggerIcon}
                <span className="hidden sm:inline">
                  {isBusy && busyAction !== "print" ? t("public.canvas.exporting") : t("public.canvas.export")}
                </span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              <DropdownMenuItem onSelect={handleExportPng}>
                <FileImage className="mr-2 h-4 w-4" aria-hidden="true" />
                {t("public.canvas.exportPng")}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={handleExportPdf}>
                <FileText className="mr-2 h-4 w-4" aria-hidden="true" />
                {t("public.canvas.exportPdf")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={handleExportPng}
                disabled={isBusy}
                aria-label={t("public.canvas.exportPng")}
                className="h-8 px-2 text-[#3f3d39] hover:bg-[#f3eadc] dark:text-white dark:hover:bg-white/10"
              >
                {triggerIcon}
                <span className="hidden sm:inline">
                  {isBusy && busyAction !== "print" ? t("public.canvas.exporting") : t("public.canvas.export")}
                </span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("public.canvas.exportPng")}</TooltipContent>
          </Tooltip>
        )}
        {assistantAvailable ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={onOpenAssistant}
                aria-label={t("public.assistant.open")}
                className="h-8 px-2 text-[#3f3d39] hover:bg-[#f3eadc] dark:text-white dark:hover:bg-white/10"
              >
                <Bot className="h-4 w-4" aria-hidden="true" />
                <span className="hidden sm:inline">{t("public.assistant.button")}</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t("public.assistant.open")}</TooltipContent>
          </Tooltip>
        ) : null}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onClick={handlePrint}
              disabled={isBusy}
              aria-label={t("public.canvas.print")}
              className="h-8 w-8 text-[#3f3d39] hover:bg-[#f3eadc] dark:text-white dark:hover:bg-white/10"
            >
              {busyAction === "print" ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Printer className="h-4 w-4" aria-hidden="true" />
              )}
            </Button>
          </TooltipTrigger>
          <TooltipContent>{t("public.canvas.print")}</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onClick={() => setMode(nextThemeMode)}
              aria-label={themeLabel}
              aria-pressed={mode === "dark"}
              className="h-8 w-8 text-[#3f3d39] hover:bg-[#f3eadc] dark:text-white dark:hover:bg-white/10"
            >
              {mode === "dark" ? (
                <Moon className="h-4 w-4" aria-hidden="true" />
              ) : (
                <Sun className="h-4 w-4" aria-hidden="true" />
              )}
            </Button>
          </TooltipTrigger>
          <TooltipContent>{themeLabel}</TooltipContent>
        </Tooltip>
        <PublishedUserMenu />
      </div>
    </TooltipProvider>
  );
}

function PublishedUserMenu() {
  const { t, locale, setLocale } = useI18n();
  const [user, setUser] = useState<UserInfo | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loginHref, setLoginHref] = useState("/login");
  const displayName = user?.display_name?.trim() || user?.email || t("public.account.guest");
  const avatarLabel = user?.display_name?.trim() || user?.email || "?";
  const initial = avatarLabel.charAt(0).toUpperCase();

  useEffect(() => {
    let cancelled = false;
    setLoginHref(`/login?next=${encodeURIComponent(`${window.location.pathname}${window.location.search}`)}`);
    const token = getInMemoryToken();
    if (!token) {
      setUser(null);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    apiGetMe(token)
      .then((nextUser) => {
        if (!cancelled) setUser(nextUser);
      })
      .catch(() => {
        if (!cancelled) setUser(null);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleLogout() {
    await apiLogout().catch(() => {});
    clearInMemoryToken();
    useChatStore.getState().clearForUser();
    useAssetStore.getState().clearForUser();
    const next = encodeURIComponent(`${window.location.pathname}${window.location.search}`);
    window.location.href = `/login?next=${next}`;
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label={t("public.account.menu")}
          className="h-8 gap-2 px-2 text-[#3f3d39] hover:bg-[#f3eadc] dark:text-white dark:hover:bg-white/10"
        >
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[#c96442] text-[10px] font-semibold leading-none text-white">
            {isLoading ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> : initial}
          </span>
          <span className="hidden max-w-[120px] truncate text-xs font-medium sm:inline">{displayName}</span>
          <ChevronDown className="h-3.5 w-3.5 text-[#777166] dark:text-gray-300" aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" sideOffset={8} className="w-64">
        <div className="px-2 py-1.5">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#c96442] text-sm font-semibold text-white">
              {user ? initial : <UserRound className="h-4 w-4" aria-hidden="true" />}
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-[#2f332f] dark:text-white">{displayName}</p>
              <p className="truncate text-xs text-[#777166] dark:text-gray-300">
                {user?.email ?? t("public.account.guestDesc")}
              </p>
            </div>
          </div>
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={(event) => event.preventDefault()}>
          <Globe className="h-4 w-4" aria-hidden="true" />
          {t("language.label")}
        </DropdownMenuItem>
        <DropdownMenuItem inset onSelect={() => setLocale("en-US")}>
          {t("language.en")}
          {locale === "en-US" && <Check className="ml-auto h-4 w-4" aria-hidden="true" />}
        </DropdownMenuItem>
        <DropdownMenuItem inset onSelect={() => setLocale("zh-CN")}>
          {t("language.zh")}
          {locale === "zh-CN" && <Check className="ml-auto h-4 w-4" aria-hidden="true" />}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {user ? (
          <DropdownMenuItem
            onSelect={handleLogout}
            className="text-error-crimson focus:bg-error-crimson/10 focus:text-error-crimson"
          >
            <LogOut className="h-4 w-4" aria-hidden="true" />
            {t("auth.logout")}
          </DropdownMenuItem>
        ) : (
          <DropdownMenuItem asChild>
            <Link href={loginHref}>
              <LogIn className="h-4 w-4" aria-hidden="true" />
              {t("auth.login")}
            </Link>
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
