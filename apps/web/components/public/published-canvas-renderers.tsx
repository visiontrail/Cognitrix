"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent, type WheelEvent } from "react";
import { Minus, Plus, RotateCcw } from "lucide-react";
import { ChartPreview } from "@/components/charts/chart-preview";
import { PublicCanvasActions } from "@/components/public/public-canvas-actions";
import {
  fetchPublicChartData,
  type PublicChartData,
  type PublishedCanvasNode,
  type PublishedManifest,
} from "@/lib/public/api";
import { useI18n } from "@/lib/i18n/context";
import type { ChartSpec } from "@/types/chart";

const FREE_CANVAS_PADDING = 32;
const MIN_FREE_CANVAS_ZOOM = 0.25;
const MAX_FREE_CANVAS_ZOOM = 2;
const FREE_CANVAS_ZOOM_STEP = 1.1;

type FreeCanvasTransform = {
  x: number;
  y: number;
  zoom: number;
};

type ChartCanvasNode = PublishedCanvasNode & {
  data: Extract<PublishedCanvasNode["data"], { type: "chart" }>;
};
type TextCanvasNode = PublishedCanvasNode & {
  data: Extract<PublishedCanvasNode["data"], { type: "text" }>;
};
type StickyCanvasNode = PublishedCanvasNode & {
  data: Extract<PublishedCanvasNode["data"], { type: "stickyNote" }>;
};
type DividerCanvasNode = PublishedCanvasNode & {
  data: Extract<PublishedCanvasNode["data"], { type: "divider" }>;
};
type SectionCanvasNode = PublishedCanvasNode & {
  data: Extract<PublishedCanvasNode["data"], { type: "section" }>;
};

export function PublishedFreeCanvas({
  token,
  manifest,
  filenameBase = "published-canvas",
}: {
  token: string;
  manifest: PublishedManifest;
  filenameBase?: string;
}) {
  const { t } = useI18n();
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
  } | null>(null);
  const nodes = (manifest.content?.nodes ?? []).filter((node) => !node.hidden);
  const bounds = manifest.canvas?.bounds ?? computeBounds(nodes);
  const left = Math.min(bounds.x, ...nodes.map((node) => node.position.x), 0);
  const top = Math.min(bounds.y, ...nodes.map((node) => node.position.y), 0);
  const width = Math.max(bounds.width + Math.abs(left) + 96, 960);
  const height = Math.max(bounds.height + Math.abs(top) + 96, 640);
  const offsetX = left < 0 ? Math.abs(left) + FREE_CANVAS_PADDING : FREE_CANVAS_PADDING;
  const offsetY = top < 0 ? Math.abs(top) + FREE_CANVAS_PADDING : FREE_CANVAS_PADDING;
  const initialTransform = useMemo<FreeCanvasTransform>(
    () => ({
      x: 0,
      y: 0,
      zoom: clampFreeCanvasZoom(Number(manifest.canvas?.viewport?.zoom ?? 1)),
    }),
    [manifest.canvas?.viewport?.zoom, token]
  );
  const [transform, setTransform] = useState<FreeCanvasTransform>(initialTransform);
  const [isDragging, setIsDragging] = useState(false);

  useEffect(() => {
    setTransform(initialTransform);
  }, [initialTransform]);

  const zoomAtPoint = useCallback((nextZoom: number, point?: { x: number; y: number }) => {
    setTransform((current) => {
      const zoom = clampFreeCanvasZoom(nextZoom);
      if (zoom === current.zoom) return current;
      const rect = viewportRef.current?.getBoundingClientRect();
      const focalPoint = point ?? {
        x: rect ? rect.width / 2 : 0,
        y: rect ? rect.height / 2 : 0,
      };
      return {
        zoom,
        x: roundFreeCanvasTransformValue(focalPoint.x - ((focalPoint.x - current.x) / current.zoom) * zoom),
        y: roundFreeCanvasTransformValue(focalPoint.y - ((focalPoint.y - current.y) / current.zoom) * zoom),
      };
    });
  }, []);

  const handleWheel = useCallback(
    (event: WheelEvent<HTMLDivElement>) => {
      event.preventDefault();
      const rect = event.currentTarget.getBoundingClientRect();
      const zoomMultiplier = event.deltaY > 0 ? 1 / FREE_CANVAS_ZOOM_STEP : FREE_CANVAS_ZOOM_STEP;
      zoomAtPoint(transform.zoom * zoomMultiplier, {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      });
    },
    [transform.zoom, zoomAtPoint]
  );

  const handlePointerDown = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement | null;
    if (target?.closest("[data-public-canvas-control]")) return;
    event.preventDefault();
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: transform.x,
      originY: transform.y,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setIsDragging(true);
  }, [transform.x, transform.y]);

  const handlePointerMove = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    setTransform((current) => ({
      ...current,
      x: roundFreeCanvasTransformValue(drag.originX + event.clientX - drag.startX),
      y: roundFreeCanvasTransformValue(drag.originY + event.clientY - drag.startY),
    }));
  }, []);

  const endDrag = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setIsDragging(false);
  }, []);

  const resetView = useCallback(() => {
    dragRef.current = null;
    setIsDragging(false);
    setTransform(initialTransform);
  }, [initialTransform]);

  return (
    <div
      ref={viewportRef}
      className={`relative h-screen overflow-hidden bg-[#f7f4eb] text-[#2f332f] ${
        isDragging ? "cursor-grabbing" : "cursor-grab"
      }`}
      aria-label={t("public.canvas.viewport")}
      data-testid="published-free-canvas-viewport"
      onPointerCancel={endDrag}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      onWheel={handleWheel}
      style={{ touchAction: "none" }}
    >
      <div
        ref={stageRef}
        className="relative will-change-transform"
        data-testid="published-free-canvas-stage"
        style={{
          width,
          height,
          transform: `matrix(${transform.zoom}, 0, 0, ${transform.zoom}, ${transform.x}, ${transform.y})`,
          transformOrigin: "top left",
        }}
      >
        {nodes.map((node) => (
          <PublishedNode
            key={node.id}
            token={token}
            node={node}
            offsetX={offsetX}
            offsetY={offsetY}
          />
        ))}
      </div>
      <PublicCanvasActions
        getCanvasElement={() => stageRef.current}
        filenameBase={filenameBase}
        className="absolute right-4 top-4"
        captureOptions={{ backgroundColor: "#f7f4eb", width, height }}
      />
      <div
        className="absolute bottom-4 left-4 flex items-center gap-1 rounded-md border border-[#d8d1c1] bg-white/90 p-1 shadow-sm backdrop-blur"
        data-public-canvas-control
      >
        <button
          type="button"
          className="flex h-8 w-8 items-center justify-center rounded hover:bg-[#f3eadc] focus:outline-none focus:ring-2 focus:ring-[#c96442]/40"
          aria-label={t("public.canvas.zoomOut")}
          title={t("public.canvas.zoomOut")}
          onClick={() => zoomAtPoint(transform.zoom / FREE_CANVAS_ZOOM_STEP)}
        >
          <Minus className="h-4 w-4" aria-hidden="true" />
        </button>
        <output
          className="min-w-12 px-1 text-center text-xs tabular-nums text-[#555250]"
          aria-label={t("public.canvas.zoomLevel")}
        >
          {Math.round(transform.zoom * 100)}%
        </output>
        <button
          type="button"
          className="flex h-8 w-8 items-center justify-center rounded hover:bg-[#f3eadc] focus:outline-none focus:ring-2 focus:ring-[#c96442]/40"
          aria-label={t("public.canvas.zoomIn")}
          title={t("public.canvas.zoomIn")}
          onClick={() => zoomAtPoint(transform.zoom * FREE_CANVAS_ZOOM_STEP)}
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
        </button>
        <button
          type="button"
          className="ml-1 flex h-8 w-8 items-center justify-center rounded border-l border-[#e8dfcf] pl-1 hover:bg-[#f3eadc] focus:outline-none focus:ring-2 focus:ring-[#c96442]/40"
          aria-label={t("public.canvas.resetView")}
          title={t("public.canvas.resetView")}
          onClick={resetView}
        >
          <RotateCcw className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}

export function PublishedFixedCanvas({
  token,
  manifest,
  filenameBase = "published-canvas",
}: {
  token: string;
  manifest: PublishedManifest;
  filenameBase?: string;
}) {
  const page = manifest.canvas?.page;
  const pageRef = useRef<HTMLDivElement | null>(null);
  const [scale, setScale] = useState(1);
  useEffect(() => {
    if (!page?.width) return;
    function updateScale() {
      setScale(Math.min(1, Math.max(0.25, (window.innerWidth - 48) / page!.width)));
    }
    updateScale();
    window.addEventListener("resize", updateScale);
    return () => window.removeEventListener("resize", updateScale);
  }, [page?.width]);
  if (!page || page.width <= 0 || page.height <= 0) {
    return null;
  }
  const nodes = (manifest.content?.nodes ?? []).filter((node) => !node.hidden);
  return (
    <div className="relative h-screen overflow-auto bg-[#ebe7dc] p-6 text-[#2f332f]">
      <PublicCanvasActions
        getCanvasElement={() => pageRef.current}
        filenameBase={filenameBase}
        allowPdf
        className="fixed right-4 top-4"
        captureOptions={{ backgroundColor: "#ffffff", width: page.width, height: page.height }}
      />
      <div className="mx-auto" style={{ width: page.width * scale, height: page.height * scale }}>
        <div
          ref={pageRef}
          className="relative origin-top overflow-hidden bg-white shadow-sm ring-1 ring-[#d8d1c1]"
          style={{
            width: page.width,
            height: page.height,
            transform: `scale(${scale})`,
            transformOrigin: "top left",
          }}
        >
          {nodes.map((node) => (
            <PublishedNode key={node.id} token={token} node={node} offsetX={0} offsetY={0} />
          ))}
        </div>
      </div>
    </div>
  );
}

function PublishedNode({
  token,
  node,
  offsetX,
  offsetY,
}: {
  token: string;
  node: PublishedCanvasNode;
  offsetX: number;
  offsetY: number;
}) {
  const width = Number(node.width ?? node.data.width ?? 240);
  const height = Number("height" in node.data ? node.height ?? node.data.height ?? 160 : node.height ?? 24);
  return (
    <div
      className="absolute"
      style={{
        left: node.position.x + offsetX,
        top: node.position.y + offsetY,
        width,
        height,
        zIndex: node.zIndex ?? 1,
      }}
    >
      {isChartNode(node) && <PublishedChartNode token={token} node={node} height={height} />}
      {isTextNode(node) && <PublishedTextNode node={node} />}
      {isStickyNode(node) && <PublishedStickyNode node={node} />}
      {isDividerNode(node) && <PublishedDividerNode node={node} />}
      {isSectionNode(node) && <PublishedSectionNode node={node} />}
    </div>
  );
}

function PublishedChartNode({
  token,
  node,
  height,
}: {
  token: string;
  node: ChartCanvasNode;
  height: number;
}) {
  const chartId = node.data.assetId;
  const title = node.data.title;
  const [spec, setSpec] = useState<ChartSpec | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchPublicChartData(token, chartId)
      .then((payload) => {
        if (!cancelled) setSpec(normalizeSpec(payload));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [chartId, token]);

  return (
    <section className="h-full overflow-hidden rounded-md border border-[#d8d1c1] bg-white">
      <div className="border-b border-[#eee8dc] px-3 py-2 text-sm font-semibold">
        {title || chartId}
      </div>
      {spec ? (
        <ChartPreview spec={spec} height={Math.max(120, height - 40)} />
      ) : (
        <PublishedChartLoading />
      )}
    </section>
  );
}

function PublishedChartLoading() {
  const { t } = useI18n();
  return (
    <div className="flex h-full items-center justify-center text-sm text-[#777166]">
      {t("public.loadingChart")}
    </div>
  );
}

function PublishedTextNode({ node }: { node: TextCanvasNode }) {
  return (
    <div
      className="w-full bg-transparent"
      data-testid={`published-text-node-${node.id}`}
      style={{
        color: node.data.color || "#3f3d39",
        fontSize: node.data.fontSize || 18,
        fontWeight: node.data.fontWeight || "normal",
        lineHeight: 1.45,
      }}
    >
      <p className="whitespace-pre-wrap break-words">{node.data.content}</p>
    </div>
  );
}

function PublishedStickyNode({ node }: { node: StickyCanvasNode }) {
  const palette = {
    yellow: "#fff5b8",
    blue: "#dff0ff",
    green: "#e0f4cf",
    pink: "#ffdfea",
  };
  return (
    <div
      className="h-full overflow-hidden rounded-md border border-black/10 p-4 shadow-sm"
      style={{
        background: palette[node.data.color || "yellow"],
        transform: `rotate(${node.data.rotation || 0}deg)`,
      }}
    >
      <p className="whitespace-pre-wrap text-sm leading-relaxed">{node.data.content}</p>
    </div>
  );
}

function PublishedDividerNode({ node }: { node: DividerCanvasNode }) {
  return (
    <div className="flex h-full items-center">
      <div
        className="w-full border-t border-[#777166]"
        style={{
          borderTopStyle: node.data.lineStyle || "solid",
          transform: `rotate(${node.data.rotation || 0}deg)`,
        }}
      />
      {node.data.label && <span className="ml-2 text-xs text-[#777166]">{node.data.label}</span>}
    </div>
  );
}

function PublishedSectionNode({ node }: { node: SectionCanvasNode }) {
  return (
    <section className="h-full rounded-md border border-dashed border-[#cfc5b2] bg-white/50 p-3">
      <h2 className="text-sm font-semibold text-[#555250]">{node.data.title}</h2>
    </section>
  );
}

function computeBounds(nodes: PublishedCanvasNode[]): { x: number; y: number; width: number; height: number } {
  if (!nodes.length) return { x: 0, y: 0, width: 0, height: 0 };
  const xs = nodes.map((node) => node.position.x);
  const ys = nodes.map((node) => node.position.y);
  const rights = nodes.map((node) => node.position.x + Number(node.width ?? node.data.width ?? 0));
  const bottoms = nodes.map((node) => {
    const dataHeight = "height" in node.data ? node.data.height : 24;
    return node.position.y + Number(node.height ?? dataHeight ?? 0);
  });
  const x = Math.min(...xs);
  const y = Math.min(...ys);
  return { x, y, width: Math.max(...rights) - x, height: Math.max(...bottoms) - y };
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

function clampFreeCanvasZoom(zoom: number): number {
  if (!Number.isFinite(zoom)) return 1;
  return Math.min(MAX_FREE_CANVAS_ZOOM, Math.max(MIN_FREE_CANVAS_ZOOM, zoom));
}

function roundFreeCanvasTransformValue(value: number): number {
  return Math.round(value * 1000) / 1000;
}

function isChartNode(node: PublishedCanvasNode): node is ChartCanvasNode {
  return node.data.type === "chart";
}

function isTextNode(node: PublishedCanvasNode): node is TextCanvasNode {
  return node.data.type === "text";
}

function isStickyNode(node: PublishedCanvasNode): node is StickyCanvasNode {
  return node.data.type === "stickyNote";
}

function isDividerNode(node: PublishedCanvasNode): node is DividerCanvasNode {
  return node.data.type === "divider";
}

function isSectionNode(node: PublishedCanvasNode): node is SectionCanvasNode {
  return node.data.type === "section";
}
