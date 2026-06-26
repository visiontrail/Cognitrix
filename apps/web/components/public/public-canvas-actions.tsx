"use client";

import { useCallback, useState } from "react";
import { Download, FileImage, FileText, Loader2, Printer } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  exportPublicCanvasToPdf,
  exportPublicCanvasToPng,
  printPublicCanvas,
} from "@/lib/public/canvas-export";
import { useI18n } from "@/lib/i18n/context";
import { cn } from "@/lib/utils";

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
  className?: string;
};

export function PublicCanvasActions({
  getCanvasElement,
  filenameBase,
  allowPdf = false,
  captureOptions,
  className,
}: PublicCanvasActionsProps) {
  const { t } = useI18n();
  const [busyAction, setBusyAction] = useState<"png" | "pdf" | "print" | null>(null);

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
          "z-20 flex items-center gap-1 rounded-md border border-[#d8d1c1] bg-white/95 p-1 shadow-sm backdrop-blur",
          className
        )}
        data-public-canvas-control
        data-public-canvas-export-ignore
      >
        {allowPdf ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={isBusy}
                aria-label={t("public.canvas.export")}
                className="h-8 px-2 text-[#3f3d39] hover:bg-[#f3eadc]"
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
                className="h-8 px-2 text-[#3f3d39] hover:bg-[#f3eadc]"
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
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onClick={handlePrint}
              disabled={isBusy}
              aria-label={t("public.canvas.print")}
              className="h-8 w-8 text-[#3f3d39] hover:bg-[#f3eadc]"
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
      </div>
    </TooltipProvider>
  );
}
