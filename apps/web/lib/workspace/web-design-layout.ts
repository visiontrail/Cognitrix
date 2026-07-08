import type { WebDesignGridConfig, WebDesignPage } from "@/types/workspace";

/**
 * Fluid unit-grid layout engine for the Web Page Design canvas.
 *
 * Blocks live on an implicit 12-column grid (react-grid-layout semantics):
 * positions are integer units {x, y, w, h}; rows are created on demand and
 * vertical compaction pulls blocks up so the page never keeps dead gaps.
 * Column widths are fractions of the container, so published pages are
 * responsive instead of a fixed pixel table.
 */

export const GRID_COLS = 12;
export const GRID_ROW_UNIT = 72;
export const GRID_GAP = 16;

export const CHART_DEFAULT_W = 6;
export const CHART_DEFAULT_H = 5;
export const CHART_MIN_W = 3;
export const CHART_MIN_H = 3;
export const TEXT_MIN_W = 2;
export const TEXT_MIN_H = 1;

export type GridRect = { x: number; y: number; w: number; h: number };

export type LayoutItem = GridRect & {
  id: string;
  kind: "chart" | "text";
};

export function gridUnitsToPx(units: number, unitPx: number, gapPx: number): number {
  return Math.max(0, units * unitPx + Math.max(0, units - 1) * gapPx);
}

export function rowUnitOf(grid: WebDesignGridConfig | undefined): number {
  const unit = Number(grid?.rowUnit);
  return Number.isFinite(unit) && unit >= 24 && unit <= 200 ? Math.round(unit) : GRID_ROW_UNIT;
}

export function isFluidGrid(grid: WebDesignGridConfig | undefined | null): boolean {
  return Boolean(grid && Number.isFinite(Number(grid.rowUnit)));
}

export function collides(a: GridRect, b: GridRect): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

export function layoutBottom(items: readonly GridRect[]): number {
  return items.reduce((max, item) => Math.max(max, item.y + item.h), 0);
}

export function clampRect(rect: GridRect, minW = 1, minH = 1): GridRect {
  const w = Math.min(GRID_COLS, Math.max(minW, Math.round(rect.w)));
  const h = Math.max(minH, Math.round(rect.h));
  const x = Math.min(GRID_COLS - w, Math.max(0, Math.round(rect.x)));
  const y = Math.max(0, Math.round(rect.y));
  return { x, y, w, h };
}

function sortByPosition<T extends LayoutItem>(items: readonly T[]): T[] {
  return [...items].sort((a, b) => (a.y === b.y ? a.x - b.x : a.y - b.y));
}

/**
 * Vertical compaction: in reading order, pull every block up as far as it can
 * go without overlapping an already-placed block.
 */
export function compactLayout<T extends LayoutItem>(items: readonly T[]): T[] {
  const placed: T[] = [];
  for (const item of sortByPosition(items)) {
    let y = Math.max(0, item.y);
    while (y > 0 && !placed.some((other) => collides({ ...item, y: y - 1 }, other))) {
      y -= 1;
    }
    while (placed.some((other) => collides({ ...item, y }, other))) {
      y += 1;
    }
    placed.push({ ...item, y });
  }
  const order = new Map(placed.map((item) => [item.id, item]));
  return items.map((item) => order.get(item.id) ?? item);
}

/**
 * Push every block that overlaps `pinned` straight down until nothing
 * overlaps, keeping the pinned block exactly where the user put it.
 */
function resolveCollisions<T extends LayoutItem>(items: readonly T[], pinnedId: string): T[] {
  const result = items.map((item) => ({ ...item }));
  const pinned = result.find((item) => item.id === pinnedId);
  if (!pinned) return result;

  let guard = result.length * result.length + result.length;
  let moved = true;
  while (moved && guard > 0) {
    moved = false;
    guard -= 1;
    for (const item of sortByPosition(result)) {
      if (item.id === pinnedId) continue;
      const blockers = result.filter((other) => other.id !== item.id && collides(item, other));
      if (!blockers.length) continue;
      item.y = Math.max(...blockers.map((other) => other.y + other.h));
      moved = true;
    }
  }
  return result;
}

/**
 * Compaction that keeps one block pinned in place — used while an item is
 * being dragged/resized so the preview does not yank it away from the cursor.
 */
function compactAround<T extends LayoutItem>(items: readonly T[], pinnedId: string): T[] {
  const pinned = items.find((item) => item.id === pinnedId);
  if (!pinned) return compactLayout(items);
  const placed: T[] = [{ ...pinned }];
  for (const item of sortByPosition(items)) {
    if (item.id === pinnedId) continue;
    let y = Math.max(0, item.y);
    while (y > 0 && !placed.some((other) => collides({ ...item, y: y - 1 }, other))) {
      y -= 1;
    }
    while (placed.some((other) => collides({ ...item, y }, other))) {
      y += 1;
    }
    placed.push({ ...item, y });
  }
  const byId = new Map(placed.map((item) => [item.id, item]));
  return items.map((item) => byId.get(item.id) ?? item);
}

export function applyRect<T extends LayoutItem>(
  items: readonly T[],
  id: string,
  rect: GridRect,
  minW = 1,
  minH = 1
): T[] {
  const target = items.find((item) => item.id === id);
  if (!target) return [...items];
  const next = clampRect(rect, minW, minH);
  if (target.x === next.x && target.y === next.y && target.w === next.w && target.h === next.h) {
    return [...items];
  }
  const updated = items.map((item) => (item.id === id ? { ...item, ...next } : { ...item }));
  return compactAround(resolveCollisions(updated, id), id);
}

export function moveItem<T extends LayoutItem>(items: readonly T[], id: string, x: number, y: number): T[] {
  const target = items.find((item) => item.id === id);
  if (!target) return [...items];
  return applyRect(items, id, { ...target, x, y });
}

export function resizeItem<T extends LayoutItem>(
  items: readonly T[],
  id: string,
  w: number,
  h: number,
  minW = 1,
  minH = 1
): T[] {
  const target = items.find((item) => item.id === id);
  if (!target) return [...items];
  return applyRect(items, id, { ...target, w, h }, minW, minH);
}

/**
 * Row-major scan for the first slot that fits a new block, falling back to
 * the bottom of the page. This is how charts and text blocks are inserted:
 * no manual cell picking, the layout finds space by itself.
 */
export function findSlot(items: readonly GridRect[], w: number, h: number): { x: number; y: number } {
  const width = Math.min(GRID_COLS, Math.max(1, w));
  const bottom = layoutBottom(items);
  for (let y = 0; y <= bottom; y += 1) {
    for (let x = 0; x + width <= GRID_COLS; x += 1) {
      const candidate = { x, y, w: width, h };
      if (!items.some((item) => collides(candidate, item))) {
        return { x, y };
      }
    }
  }
  return { x: 0, y: bottom };
}

export type PageLayoutItems = {
  charts: LayoutItem[];
  texts: LayoutItem[];
};

export function pageToLayoutItems(page: Pick<WebDesignPage, "zones" | "textZones">): LayoutItem[] {
  const charts: LayoutItem[] = page.zones.map((zone) => ({
    id: zone.id,
    kind: "chart",
    x: zone.column,
    y: zone.row,
    w: zone.colSpan,
    h: zone.rowSpan,
  }));
  const texts: LayoutItem[] = (page.textZones ?? []).map((zone) => ({
    id: zone.id,
    kind: "text",
    x: zone.column,
    y: zone.row,
    w: zone.colSpan,
    h: zone.rowSpan,
  }));
  return [...charts, ...texts];
}

export function layoutItemsToPage<T extends Pick<WebDesignPage, "zones" | "textZones">>(
  page: T,
  items: readonly LayoutItem[]
): T {
  const byId = new Map(items.map((item) => [item.id, item]));
  return {
    ...page,
    zones: page.zones.map((zone) => {
      const item = byId.get(zone.id);
      return item ? { ...zone, column: item.x, row: item.y, colSpan: item.w, rowSpan: item.h } : zone;
    }),
    textZones: (page.textZones ?? []).map((zone) => {
      const item = byId.get(zone.id);
      return item ? { ...zone, column: item.x, row: item.y, colSpan: item.w, rowSpan: item.h } : zone;
    }),
  };
}

export function minSizeFor(kind: LayoutItem["kind"]): { minW: number; minH: number } {
  return kind === "chart" ? { minW: CHART_MIN_W, minH: CHART_MIN_H } : { minW: TEXT_MIN_W, minH: TEXT_MIN_H };
}

/**
 * Convert a legacy fixed-pixel grid page (2-10 columns, explicit pixel rows)
 * into fluid 12-column units. Old saves and published snapshots keep working;
 * the first edit after loading rewrites them in the new format.
 */
export function migrateLegacyPage(page: WebDesignPage): WebDesignPage {
  if (isFluidGrid(page.grid)) {
    return {
      ...page,
      grid: { columns: GRID_COLS, rowUnit: rowUnitOf(page.grid), rows: [] },
      textZones: page.textZones ?? [],
    };
  }

  const legacyColumns = Math.min(10, Math.max(1, Math.trunc(Number(page.grid?.columns) || 3)));
  const factor = GRID_COLS / legacyColumns;
  const legacyRows = Array.isArray(page.grid?.rows) && page.grid.rows.length ? page.grid.rows : [{ id: "row-1", height: 400 }];
  const rowUnits = legacyRows.map((row) => Math.max(1, Math.round((Number(row.height) || 400) / GRID_ROW_UNIT)));
  const rowStarts: number[] = [];
  let acc = 0;
  for (const units of rowUnits) {
    rowStarts.push(acc);
    acc += units;
  }
  const unitsBetween = (startRow: number, span: number): number => {
    let total = 0;
    for (let i = startRow; i < Math.min(legacyRows.length, startRow + span); i += 1) {
      total += rowUnits[i] ?? rowUnits[rowUnits.length - 1] ?? 4;
    }
    return Math.max(1, total);
  };
  const convert = <Z extends { column: number; row: number; colSpan: number; rowSpan: number }>(zone: Z): Z => {
    const legacyRow = Math.max(0, Math.trunc(zone.row));
    const rect = clampRect({
      x: Math.round(zone.column * factor),
      y: rowStarts[Math.min(legacyRow, rowStarts.length - 1)] ?? acc,
      w: Math.max(1, Math.round(zone.colSpan * factor)),
      h: unitsBetween(legacyRow, Math.max(1, Math.trunc(zone.rowSpan))),
    });
    return { ...zone, column: rect.x, row: rect.y, colSpan: rect.w, rowSpan: rect.h };
  };

  const migrated: WebDesignPage = {
    ...page,
    grid: { columns: GRID_COLS, rowUnit: GRID_ROW_UNIT, rows: [] },
    zones: page.zones.map(convert),
    textZones: (page.textZones ?? []).map(convert),
  };
  return layoutItemsToPage(migrated, compactLayout(pageToLayoutItems(migrated)));
}

export function createFluidGrid(): WebDesignGridConfig {
  return { columns: GRID_COLS, rowUnit: GRID_ROW_UNIT, rows: [] };
}
