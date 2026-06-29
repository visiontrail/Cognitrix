"use client";

import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { I18nProvider } from "@/lib/i18n/context";
import { ThemeProvider } from "@/lib/theme/context";
import { Toaster } from "sonner";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <I18nProvider>
          <TooltipProvider delayDuration={300}>
            {children}
            <Toaster
              position="bottom-right"
              toastOptions={{
                style: {
                  background: "var(--toast-background, #faf9f5)",
                  border: "1px solid var(--toast-border, #f0eee6)",
                  color: "var(--toast-foreground, #141413)",
                  fontFamily: "Inter, system-ui, sans-serif",
                },
              }}
            />
          </TooltipProvider>
        </I18nProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
