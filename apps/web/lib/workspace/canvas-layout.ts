import type { Node } from "@xyflow/react";
import type { WorkspaceCanvasFormatId, WorkspaceNode } from "@/types/workspace";
import { getCanvasFormatPreset } from "./canvas-formats";

export type CanvasPoint = { x: number; y: number };
export type CanvasSize = { width: number; height: number };

type Rect = { left: number; top: number; right: number; bottom: number };

const PLACEMENT_GAP = 28;
const COLLISION_PADDING = 8;
const FIXED_CANVAS_MARGIN = 40;
const INFINITE_START = { x: 50, y: 50 };
const INFINITE_COLUMNS = 4;
const MAX_SCAN_ROWS = 400;

/**
 * Best-effort read of a node's rendered footprint. React Flow stores the live
 * size on the node (`width`/`height` once resized, `measured` after mount) while
 * the persisted data carries the authored size — we fall back through all of
 * them so collision checks work for freshly-added and restored nodes alike.
 */
function getNodeRect(node: Node): Rect | null {
  const position = node.position;
  if (!position) return null;

  const data = (node.data ?? {}) as { width?: number; height?: number };
  const width = Number(
    node.width ?? (node as { measured?: { width?: number } }).measured?.width ?? data.width ?? 0
  );
  const height = Number(
    node.height ?? (node as { measured?: { height?: number } }).measured?.height ?? data.height ?? 24
  );
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return null;
  }

  return {
    left: position.x,
    top: position.y,
    right: position.x + width,
    bottom: position.y + height,
  };
}

function rectsOverlap(a: Rect, b: Rect): boolean {
  return !(
    a.right + COLLISION_PADDING <= b.left ||
    a.left >= b.right + COLLISION_PADDING ||
    a.bottom + COLLISION_PADDING <= b.top ||
    a.top >= b.bottom + COLLISION_PADDING
  );
}

function collides(candidate: Rect, obstacles: Rect[]): boolean {
  return obstacles.some((rect) => rectsOverlap(candidate, rect));
}

function toCandidateRect(point: CanvasPoint, size: CanvasSize): Rect {
  return {
    left: point.x,
    top: point.y,
    right: point.x + size.width,
    bottom: point.y + size.height,
  };
}

/**
 * Find a position for a new node that does not overlap any existing node, so a
 * freshly-added element is always visible rather than stacked on top of another.
 *
 * The scan walks a grid sized to the new element (plus a gap), left-to-right then
 * top-to-bottom. On fixed-size canvases (A4/Letter/16:9) columns/rows are bounded
 * by the page; on the infinite canvas the grid uses a fixed column count and grows
 * downward. If no free slot is found we drop the element below everything else.
 */
export function findOpenCanvasPosition(
  nodes: Node[] | WorkspaceNode[],
  size: CanvasSize,
  canvasFormatId: WorkspaceCanvasFormatId = "infinite"
): CanvasPoint {
  const obstacles = (nodes as Node[])
    .filter((node) => !node.hidden)
    .map(getNodeRect)
    .filter((rect): rect is Rect => rect !== null);

  const preset = getCanvasFormatPreset(canvasFormatId);
  const stepX = size.width + PLACEMENT_GAP;
  const stepY = size.height + PLACEMENT_GAP;

  const bounded = preset.width != null && preset.height != null;
  const startX = bounded ? FIXED_CANVAS_MARGIN : INFINITE_START.x;
  const startY = bounded ? FIXED_CANVAS_MARGIN : INFINITE_START.y;

  let columns = INFINITE_COLUMNS;
  let maxRows = MAX_SCAN_ROWS;
  if (bounded) {
    const usableWidth = preset.width! - FIXED_CANVAS_MARGIN * 2;
    const usableHeight = preset.height! - FIXED_CANVAS_MARGIN * 2;
    columns = Math.max(1, Math.floor((usableWidth + PLACEMENT_GAP) / stepX));
    maxRows = Math.max(1, Math.floor((usableHeight + PLACEMENT_GAP) / stepY));
  }

  if (obstacles.length === 0) {
    return { x: startX, y: startY };
  }

  for (let row = 0; row < maxRows; row += 1) {
    for (let col = 0; col < columns; col += 1) {
      const candidate = { x: startX + col * stepX, y: startY + row * stepY };
      if (bounded) {
        // Keep the whole element inside the page bounds.
        if (candidate.x + size.width > preset.width! - FIXED_CANVAS_MARGIN + PLACEMENT_GAP) continue;
        if (candidate.y + size.height > preset.height! - FIXED_CANVAS_MARGIN + PLACEMENT_GAP) continue;
      }
      if (!collides(toCandidateRect(candidate, size), obstacles)) {
        return candidate;
      }
    }
  }

  // Fallback: stack below the lowest existing element so it stays reachable.
  const lowestBottom = obstacles.reduce((max, rect) => Math.max(max, rect.bottom), startY);
  return { x: startX, y: lowestBottom + PLACEMENT_GAP };
}
