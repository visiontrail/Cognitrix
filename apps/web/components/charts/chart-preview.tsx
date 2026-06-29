"use client";

import { useRef, useEffect, useMemo, useState } from "react";
import * as echarts from "echarts";
import type { ChartSpec } from "@/types/chart";
import { validateChartSpec } from "@/types/chart";
import { ensureChinaMap, normaliseProvinceName } from "@/lib/genui/geo-loader";
import { useI18n } from "@/lib/i18n/context";
import { useTheme, type ResolvedTheme } from "@/lib/theme/context";
import { isRecord } from "@/lib/utils";
import { enhanceRichTreemapOption } from "@/lib/charts/treemap-option";

type ChartPreviewProps = {
  spec: ChartSpec;
  height?: number;
  className?: string;
  theme?: ResolvedTheme;
};

const CHART_THEME_BY_MODE: Record<ResolvedTheme, Record<string, unknown>> = {
  light: {
    backgroundColor: "transparent",
    textStyle: { fontFamily: "Inter, system-ui, sans-serif", color: "#4d4c48" },
  },
  dark: {
    backgroundColor: "transparent",
    textStyle: { fontFamily: "Inter, system-ui, sans-serif", color: "#f5f4ed" },
    legend: { textStyle: { color: "#e5e7eb" } },
  },
};

const AXIS_THEME_BY_MODE: Record<ResolvedTheme, Record<string, unknown>> = {
  light: {
    axisLabel: { color: "#5e5d59" },
    axisLine: { lineStyle: { color: "#d1cfc5" } },
    splitLine: { lineStyle: { color: "#e8e6dc" } },
  },
  dark: {
    axisLabel: { color: "#c7c9d1" },
    axisLine: { lineStyle: { color: "rgba(255, 255, 255, 0.2)" } },
    splitLine: { lineStyle: { color: "rgba(255, 255, 255, 0.1)" } },
  },
};

const TABLE_THEME_BY_MODE: Record<
  ResolvedTheme,
  { header: string; row: string; altRow: string; headerText: string; text: string; border: string }
> = {
  light: {
    header: "bg-[#e8e6dc]",
    row: "bg-[#ffffff]",
    altRow: "bg-[#f2f0e7]",
    headerText: "text-[#141413]",
    text: "text-[#4d4c48]",
    border: "border-[#e8e6dc]",
  },
  dark: {
    header: "bg-[#25254d]",
    row: "bg-[#1c1c38]",
    altRow: "bg-[#25254d]/65",
    headerText: "text-white",
    text: "text-gray-200",
    border: "border-white/10",
  },
};

let echartsStatClusteringRegistered = false;

export function ChartPreview({ spec, height = 320, className, theme }: ChartPreviewProps) {
  if (spec.chartType === "table" || spec.echartsOption.__table__ === true) {
    return <TableView spec={spec} height={height} className={className} theme={theme} />;
  }

  return <EchartsChartPreview spec={spec} height={height} className={className} theme={theme} />;
}

function EchartsChartPreview({ spec, height = 320, className, theme }: ChartPreviewProps) {
  const { t, locale } = useI18n();
  const { resolvedTheme } = useTheme();
  const chartTheme = theme ?? resolvedTheme;
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);
  const [geoReady, setGeoReady] = useState(true);
  const [geoError, setGeoError] = useState<string | null>(null);

  const validation = useMemo(() => validateChartSpec(spec), [spec]);
  const requiresChinaMap = useMemo(() => requiresMapRegistration(spec.echartsOption), [spec.echartsOption]);

  const option = useMemo(() => {
    if (!validation.valid) return null;
    const baseOption = requiresChinaMap
      ? normaliseMapOption(spec.echartsOption)
      : spec.echartsOption;
    const enhancedOption = enhanceRichTreemapOption(baseOption, locale);
    return {
      ...CHART_THEME_BY_MODE[chartTheme],
      ...enhancedOption,
      xAxis: applyAxisTheme(enhancedOption.xAxis, chartTheme),
      yAxis: applyAxisTheme(enhancedOption.yAxis, chartTheme),
      animation: true,
      animationDuration: 600,
      animationEasing: "cubicInOut" as const,
    };
  }, [chartTheme, locale, spec.echartsOption, requiresChinaMap, validation.valid]);

  useEffect(() => {
    if (!requiresChinaMap) {
      setGeoReady(true);
      setGeoError(null);
      return;
    }

    let cancelled = false;
    setGeoReady(false);
    setGeoError(null);

    ensureChinaMap().then((ok) => {
      if (cancelled) {
        return;
      }
      if (!ok) {
        setGeoError(t("chart.mapLoadFailed"));
        return;
      }
      setGeoReady(true);
    });

    return () => {
      cancelled = true;
    };
  }, [requiresChinaMap, t]);

  useEffect(() => {
    if (!chartRef.current || !option || !geoReady) return;

    let cancelled = false;

    Promise.all([
      import("echarts-wordcloud"),
      ensureEchartsStatTransforms(option),
    ]).then(() => {
      if (cancelled || !chartRef.current) return;

      const instance = echarts.init(chartRef.current, undefined, { renderer: "canvas" });
      instanceRef.current = instance;

      try {
        instance.setOption(option);
      } catch {
        instance.dispose();
        instanceRef.current = null;
        return;
      }

      const observer = new ResizeObserver(() => {
        instance.resize();
      });
      observer.observe(chartRef.current);
    }).catch(() => {
      // Keep the existing compact failure behavior: invalid extension setup leaves the chart blank.
    });

    return () => {
      cancelled = true;
      instanceRef.current?.dispose();
      instanceRef.current = null;
    };
  }, [geoReady, option]);

  if (!validation.valid || geoError) {
    return (
      <div
        className="flex items-center justify-center bg-warm-sand rounded-comfortable"
        style={{ height }}
      >
        <div className="text-center px-4">
          <p className="text-body-sm text-error-crimson font-medium">{t("chart.renderFailed")}</p>
          <p className="text-caption text-stone-gray mt-1">
            {geoError ?? validation.errors[0] ?? t("chart.invalidConfig")}
          </p>
        </div>
      </div>
    );
  }

  if (requiresChinaMap && !geoReady) {
    return (
      <div
        className="flex items-center justify-center bg-warm-sand rounded-comfortable"
        style={{ height }}
      >
        <p className="text-caption text-stone-gray">{t("chart.mapLoading")}</p>
      </div>
    );
  }

  return (
    <div
      data-testid="echarts-chart"
      ref={chartRef}
      className={className}
      style={{ width: "100%", height }}
    />
  );
}

function TableView({
  spec,
  height,
  className,
  theme,
}: {
  spec: ChartSpec;
  height: number;
  className?: string;
  theme?: ResolvedTheme;
}) {
  const { t } = useI18n();
  const { resolvedTheme } = useTheme();
  const tableTheme = TABLE_THEME_BY_MODE[theme ?? resolvedTheme];
  const opt = spec.echartsOption;
  const columns = Array.isArray(opt.__columns__)
    ? (opt.__columns__ as string[])
    : [];
  const rows = Array.isArray(opt.__rows__)
    ? (opt.__rows__ as Record<string, unknown>[])
    : [];

  if (!columns.length && !rows.length) {
    return (
      <div
        className="flex items-center justify-center text-stone-gray text-body-sm"
        style={{ height }}
      >
        {t("chart.noData")}
      </div>
    );
  }

  const cols = columns.length ? columns : rows.length ? Object.keys(rows[0]) : [];

  return (
    <div
      className={`overflow-auto rounded-comfortable ${className ?? ""}`}
      style={{ maxHeight: height }}
    >
      <table className="w-full text-body-sm border-collapse">
        <thead className={`sticky top-0 ${tableTheme.header}`}>
          <tr>
            {cols.map((col) => (
              <th
                key={col}
                className={`px-3 py-2 text-left font-medium border-b whitespace-nowrap ${tableTheme.headerText} ${tableTheme.border}`}
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className={i % 2 === 0 ? tableTheme.row : tableTheme.altRow}>
              {cols.map((col) => (
                <td
                  key={col}
                  className={`px-3 py-1.5 border-b whitespace-nowrap ${tableTheme.border} ${tableTheme.text}`}
                >
                  {row[col] == null ? "—" : String(row[col])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function applyAxisTheme(axis: unknown, theme: ResolvedTheme): unknown {
  if (theme === "light") return axis;
  if (!axis) return axis;
  if (Array.isArray(axis)) {
    return axis.map((entry) => mergeAxisTheme(entry, theme));
  }
  return mergeAxisTheme(axis, theme);
}

function mergeAxisTheme(axis: unknown, theme: ResolvedTheme): unknown {
  if (!isRecord(axis)) return axis;
  const axisTheme = AXIS_THEME_BY_MODE[theme];
  return {
    ...axisTheme,
    ...axis,
    axisLabel: { ...(axisTheme.axisLabel as Record<string, unknown>), ...asRecord(axis.axisLabel) },
    axisLine: {
      ...(axisTheme.axisLine as Record<string, unknown>),
      ...asRecord(axis.axisLine),
      lineStyle: {
        ...asRecord((axisTheme.axisLine as Record<string, unknown>).lineStyle),
        ...asRecord(asRecord(axis.axisLine).lineStyle),
      },
    },
    splitLine: {
      ...(axisTheme.splitLine as Record<string, unknown>),
      ...asRecord(axis.splitLine),
      lineStyle: {
        ...asRecord((axisTheme.splitLine as Record<string, unknown>).lineStyle),
        ...asRecord(asRecord(axis.splitLine).lineStyle),
      },
    },
  };
}

function asRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function requiresMapRegistration(option: Record<string, unknown>): boolean {
  const series = option.series;
  if (!Array.isArray(series)) {
    return false;
  }

  return series.some((item) => isRecord(item) && item.type === "map");
}

function normaliseMapOption(option: Record<string, unknown>): Record<string, unknown> {
  const series = option.series;
  if (!Array.isArray(series)) {
    return option;
  }

  const nextSeries = series.map((item) => {
    if (!isRecord(item) || item.type !== "map") {
      return item;
    }

    const data = item.data;
    if (!Array.isArray(data)) {
      return item;
    }

    return {
      ...item,
      data: data.map((datum) => {
        if (!isRecord(datum)) {
          return datum;
        }
        const name = datum.name;
        return {
          ...datum,
          name: typeof name === "string" ? normaliseProvinceName(name) : name,
        };
      }),
    };
  });

  return { ...option, series: nextSeries };
}

async function ensureEchartsStatTransforms(option: Record<string, unknown>): Promise<void> {
  if (!requiresEchartsStatClustering(option) || echartsStatClusteringRegistered) {
    return;
  }

  const ecStatModule = await import("echarts-stat");
  const ecStat = ("default" in ecStatModule ? ecStatModule.default : ecStatModule) as {
    transform?: { clustering?: unknown };
  };
  const clusteringTransform = ecStat.transform?.clustering;
  if (clusteringTransform) {
    echarts.registerTransform(clusteringTransform as Parameters<typeof echarts.registerTransform>[0]);
    echartsStatClusteringRegistered = true;
  }
}

function requiresEchartsStatClustering(option: Record<string, unknown>): boolean {
  const marker = option.__requiresEchartsStat__;
  if (isRecord(marker) && Array.isArray(marker.transforms) && marker.transforms.includes("clustering")) {
    return true;
  }

  return hasClusteringTransform(option.dataset);
}

function hasClusteringTransform(value: unknown): boolean {
  if (Array.isArray(value)) {
    return value.some(hasClusteringTransform);
  }
  if (!isRecord(value)) {
    return false;
  }
  const transform = value.transform;
  if (transform === "ecStat:clustering") {
    return true;
  }
  if (isRecord(transform) && transform.type === "ecStat:clustering") {
    return true;
  }
  return false;
}
