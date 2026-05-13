"use client";

import { useRef, useEffect, useMemo, useState } from "react";
import * as echarts from "echarts";
import type { ChartSpec } from "@/types/chart";
import { validateChartSpec } from "@/types/chart";
import { ensureChinaMap, normaliseProvinceName } from "@/lib/genui/geo-loader";
import { useI18n } from "@/lib/i18n/context";
import { isRecord } from "@/lib/utils";
import { enhanceRichTreemapOption } from "@/lib/charts/treemap-option";

type ChartPreviewProps = {
  spec: ChartSpec;
  height?: number;
  className?: string;
};

const WARM_THEME = {
  backgroundColor: "transparent",
  textStyle: { fontFamily: "Inter, system-ui, sans-serif", color: "#4d4c48" },
};

let echartsStatClusteringRegistered = false;

export function ChartPreview({ spec, height = 320, className }: ChartPreviewProps) {
  if (spec.chartType === "table" || spec.echartsOption.__table__ === true) {
    return <TableView spec={spec} height={height} className={className} />;
  }

  return <EchartsChartPreview spec={spec} height={height} className={className} />;
}

function EchartsChartPreview({ spec, height = 320, className }: ChartPreviewProps) {
  const { t, locale } = useI18n();
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
      ...WARM_THEME,
      ...enhancedOption,
      animation: true,
      animationDuration: 600,
      animationEasing: "cubicInOut" as const,
    };
  }, [locale, spec.echartsOption, requiresChinaMap, validation.valid]);

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
}: {
  spec: ChartSpec;
  height: number;
  className?: string;
}) {
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
        暂无数据
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
        <thead className="sticky top-0 bg-warm-sand">
          <tr>
            {cols.map((col) => (
              <th
                key={col}
                className="px-3 py-2 text-left font-medium text-ink-dark border-b border-warm-sand whitespace-nowrap"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className={i % 2 === 0 ? "bg-white" : "bg-warm-sand/40"}>
              {cols.map((col) => (
                <td
                  key={col}
                  className="px-3 py-1.5 text-ink-light border-b border-warm-sand/60 whitespace-nowrap"
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
