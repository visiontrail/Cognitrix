"use client";

import { useEffect, useMemo, useState, type RefObject } from "react";
import { ChartPreview } from "@/components/charts/chart-preview";
import {
  fetchPublicChartData,
  type PublicChartData,
  type PublishedManifest,
  type PublishedTextZone,
  type PublishedZone,
} from "@/lib/public/api";
import {
  composeCanvasBackgroundStyle,
  type CanvasBackgroundPreset,
} from "@/lib/workspace/canvas-backgrounds";
import { getWebDesignGridTemplateColumns, getWebDesignGridWidth } from "@/lib/workspace/web-design-grid";
import type { ChartSpec } from "@/types/chart";
import { useI18n } from "@/lib/i18n/context";
import { useTheme } from "@/lib/theme/context";

export function PublicPageGrid({
  token,
  manifest,
  activePageId,
  captureRef,
  backgroundPreset,
  selectedChartId,
  onSelectChart,
}: {
  token: string;
  manifest: PublishedManifest;
  activePageId?: string;
  captureRef?: RefObject<HTMLDivElement>;
  backgroundPreset: CanvasBackgroundPreset;
  selectedChartId?: string;
  onSelectChart?: (chartId: string) => void;
}) {
  const { resolvedTheme } = useTheme();
  const backgroundStyle = composeCanvasBackgroundStyle(backgroundPreset);
  const pageLayout =
    manifest.layout.pages?.find((page) => page.id === activePageId) ??
    manifest.layout.pages?.[0] ?? {
      id: manifest.layout.activePageId ?? "section-1",
      title: "Section 1",
      grid: manifest.layout.grid,
      zones: manifest.layout.zones,
    };
  const grid = pageLayout.grid;
  return (
    <div className="min-w-0 flex-1 overflow-auto p-5">
      <div
        ref={captureRef}
        className="grid"
        data-testid="public-page-grid-canvas"
        style={{
          ...backgroundStyle,
          gridTemplateColumns: getWebDesignGridTemplateColumns(grid),
          gridTemplateRows: grid.rows.map((row) => `${row.height}px`).join(" "),
          minWidth: "100%",
          width: getWebDesignGridWidth(grid),
        }}
      >
        {grid.rows.map((row, rowIndex) => (
          <div key={row.id} id={row.id} style={{ gridColumn: "1 / -1", gridRow: rowIndex + 1 }} />
        ))}
        {pageLayout.zones.map((zone) => (
          <PublicChartZone
            key={zone.id}
            token={token}
            zone={zone}
            title={manifest.charts.find((chart) => chart.chart_id === chartIdFromZone(zone))?.title}
            theme={resolvedTheme}
            selected={selectedChartId === chartIdFromZone(zone)}
            onSelectChart={onSelectChart}
          />
        ))}
        {(pageLayout.textZones ?? []).map((zone) => (
          <PublicTextZoneBlock key={zone.id} zone={zone} />
        ))}
      </div>
    </div>
  );
}

function PublicChartZone({
  token,
  zone,
  title,
  theme,
  selected,
  onSelectChart,
}: {
  token: string;
  zone: PublishedZone;
  title?: string;
  theme: "light" | "dark";
  selected?: boolean;
  onSelectChart?: (chartId: string) => void;
}) {
  const { t } = useI18n();
  const chartId = chartIdFromZone(zone);
  const [spec, setSpec] = useState<ChartSpec | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!chartId) return;
    fetchPublicChartData(token, chartId)
      .then((payload) => {
        if (cancelled) return;
        setSpec(normalizeSpec(payload));
      })
      .catch(() => {
        // Snapshot-only read; failures render the loading placeholder.
      });
    return () => {
      cancelled = true;
    };
  }, [chartId, token]);

  const height = useMemo(() => Math.max(180, zone.rowSpan * 260), [zone.rowSpan]);

  return (
    <div
      className={`relative overflow-hidden rounded-md border bg-white text-left dark:bg-[#1c1c38]/80 ${
        selected ? "border-[#4b7f8c] ring-2 ring-[#4b7f8c]/30" : "border-[#d8d1c1] dark:border-white/10"
      }`}
      style={{
        gridColumn: `${zone.column + 1} / span ${zone.colSpan}`,
        gridRow: `${zone.row + 1} / span ${zone.rowSpan}`,
      }}
      role={onSelectChart ? "button" : undefined}
      tabIndex={onSelectChart ? 0 : undefined}
      onClick={() => {
        if (chartId) onSelectChart?.(chartId);
      }}
      onKeyDown={(event) => {
        if (!chartId || !onSelectChart) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelectChart(chartId);
        }
      }}
    >
      <div className="border-b border-[#eee8dc] px-3 py-2 text-sm font-semibold dark:border-white/10 dark:text-white">
        {title || chartId}
      </div>
      {spec ? (
        <ChartPreview spec={spec} height={height} theme={theme} />
      ) : (
        <div className="flex h-full items-center justify-center text-sm text-[#777166] dark:text-gray-300">
          {t("public.loadingChart")}
        </div>
      )}
    </div>
  );
}

const PUBLISHED_TEXT_STYLE_MAP: Record<"title" | "subtitle" | "body", string> = {
  title: "text-2xl font-bold leading-tight text-[#2f332f] dark:text-white",
  subtitle: "text-lg font-semibold leading-snug text-[#4a4842] dark:text-gray-100",
  body: "text-sm leading-relaxed text-[#555250] dark:text-gray-200",
};

function PublicTextZoneBlock({ zone }: { zone: PublishedTextZone }) {
  const className = PUBLISHED_TEXT_STYLE_MAP[zone.style] ?? PUBLISHED_TEXT_STYLE_MAP.body;
  return (
    <div
      className="overflow-hidden rounded-md border border-[#c8d8f0] bg-[#f5f9ff] p-4 dark:border-white/10 dark:bg-white/[0.06]"
      style={{
        gridColumn: `${zone.column + 1} / span ${zone.colSpan}`,
        gridRow: `${zone.row + 1} / span ${zone.rowSpan}`,
      }}
    >
      <p className={`whitespace-pre-wrap ${className}`}>{zone.content}</p>
    </div>
  );
}

function chartIdFromZone(zone: PublishedZone): string {
  return zone.chartId || zone.chart_id || "";
}

function normalizeSpec(payload: PublicChartData): ChartSpec {
  return {
    chartType: (payload.spec.chartType || payload.spec.chart_type || "bar") as ChartSpec["chartType"],
    title: payload.spec.title || payload.chart_id,
    echartsOption: {
      ...(payload.spec.echartsOption || {}),
      __rows__: payload.rows,
    },
  };
}
