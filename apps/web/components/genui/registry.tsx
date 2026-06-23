"use client";

import { ChartRenderer } from "./chart-renderer";
import { useI18n } from "@/lib/i18n/context";

type GenUIRegistryProps = {
  rawSpec: unknown;
  isStreaming?: boolean;
};

export function GenUIRegistry({ rawSpec, isStreaming = false }: GenUIRegistryProps) {
  const { t } = useI18n();

  if (!rawSpec && isStreaming) {
    return (
      <div className="space-y-3 p-4">
        <div className="h-4 w-3/4 bg-warm-sand rounded animate-pulse" />
        <div className="h-4 w-full bg-warm-sand rounded animate-pulse" />
        <div className="h-4 w-1/2 bg-warm-sand rounded animate-pulse" />
      </div>
    );
  }

  if (!rawSpec || typeof rawSpec !== "object") {
    return (
      <div className="p-4 text-center text-stone-gray">
        <p>{t("genui.invalidChartSpec")}</p>
      </div>
    );
  }

  const spec = rawSpec as Record<string, unknown>;
  return (
    <ChartRenderer
      spec={{
        engine: spec.engine as string,
        chart_type: spec.chart_type as string,
        title: (spec.title as string) ?? "Chart",
        data: spec.data as Array<Record<string, unknown>>,
        config: spec.config as Record<string, unknown>,
      }}
    />
  );
}

export function hasRegistryEntry(_key: string): boolean {
  return true;
}
