"use client";

import { useEffect, useState } from "react";
import { ChartPreview } from "@/components/charts/chart-preview";
import {
  fetchPublicChartData,
  type PublicChartData,
  type PublishedCanvasNode,
  type PublishedManifest,
} from "@/lib/public/api";
import type { ChartSpec } from "@/types/chart";

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
}: {
  token: string;
  manifest: PublishedManifest;
}) {
  const nodes = (manifest.content?.nodes ?? []).filter((node) => !node.hidden);
  const bounds = manifest.canvas?.bounds ?? computeBounds(nodes);
  const left = Math.min(bounds.x, ...nodes.map((node) => node.position.x), 0);
  const top = Math.min(bounds.y, ...nodes.map((node) => node.position.y), 0);
  const width = Math.max(bounds.width + Math.abs(left) + 96, 960);
  const height = Math.max(bounds.height + Math.abs(top) + 96, 640);

  return (
    <div className="h-screen overflow-auto bg-[#f7f4eb] p-8 text-[#2f332f]">
      <div
        className="relative"
        style={{
          width,
          height,
        }}
      >
        {nodes.map((node) => (
          <PublishedNode
            key={node.id}
            token={token}
            node={node}
            offsetX={left < 0 ? Math.abs(left) + 32 : 32}
            offsetY={top < 0 ? Math.abs(top) + 32 : 32}
          />
        ))}
      </div>
    </div>
  );
}

export function PublishedFixedCanvas({
  token,
  manifest,
}: {
  token: string;
  manifest: PublishedManifest;
}) {
  const page = manifest.canvas?.page;
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
    <div className="h-screen overflow-auto bg-[#ebe7dc] p-6 text-[#2f332f]">
      <div className="mx-auto" style={{ width: page.width * scale, height: page.height * scale }}>
        <div
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
        <div className="flex h-full items-center justify-center text-sm text-[#777166]">Loading chart...</div>
      )}
    </section>
  );
}

function PublishedTextNode({ node }: { node: TextCanvasNode }) {
  return (
    <div
      className="h-full overflow-hidden rounded-md border border-[#d8d1c1] bg-white p-4"
      style={{
        color: node.data.color || "#3f3d39",
        fontSize: node.data.fontSize || 18,
        fontWeight: node.data.fontWeight || "normal",
      }}
    >
      <p className="whitespace-pre-wrap">{node.data.content}</p>
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
