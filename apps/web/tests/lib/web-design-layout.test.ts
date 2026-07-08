import { describe, expect, it } from "vitest";

import {
  GRID_COLS,
  GRID_ROW_UNIT,
  clampRect,
  collides,
  compactLayout,
  findSlot,
  isFluidGrid,
  layoutBottom,
  migrateLegacyPage,
  moveItem,
  pageToLayoutItems,
  resizeItem,
  type LayoutItem,
} from "../../lib/workspace/web-design-layout";
import type { WebDesignPage } from "../../types/workspace";

function item(id: string, x: number, y: number, w: number, h: number, kind: LayoutItem["kind"] = "chart"): LayoutItem {
  return { id, kind, x, y, w, h };
}

describe("web-design layout engine", () => {
  it("detects rect collisions", () => {
    expect(collides(item("a", 0, 0, 6, 5), item("b", 5, 4, 6, 5))).toBe(true);
    expect(collides(item("a", 0, 0, 6, 5), item("b", 6, 0, 6, 5))).toBe(false);
  });

  it("clamps rects to the 12-column grid", () => {
    expect(clampRect({ x: 10, y: -2, w: 6, h: 2 })).toEqual({ x: 6, y: 0, w: 6, h: 2 });
    expect(clampRect({ x: 0, y: 0, w: 40, h: 1 })).toEqual({ x: 0, y: 0, w: GRID_COLS, h: 1 });
    expect(clampRect({ x: 2, y: 1, w: 1, h: 1 }, 3, 3)).toEqual({ x: 2, y: 1, w: 3, h: 3 });
  });

  it("compacts blocks upward without overlap", () => {
    const compacted = compactLayout([item("a", 0, 4, 6, 2), item("b", 0, 10, 6, 2), item("c", 6, 7, 6, 2)]);
    expect(compacted.find((entry) => entry.id === "a")).toMatchObject({ y: 0 });
    expect(compacted.find((entry) => entry.id === "b")).toMatchObject({ y: 2 });
    expect(compacted.find((entry) => entry.id === "c")).toMatchObject({ y: 0 });
  });

  it("pushes colliding blocks down when moving and keeps the moved block pinned", () => {
    const layout = [item("a", 0, 0, 6, 5), item("b", 6, 0, 6, 5)];
    const moved = moveItem(layout, "b", 0, 0);
    expect(moved.find((entry) => entry.id === "b")).toMatchObject({ x: 0, y: 0 });
    expect(moved.find((entry) => entry.id === "a")).toMatchObject({ x: 0, y: 5 });
  });

  it("keeps unrelated blocks in place on move", () => {
    const layout = [item("a", 0, 0, 6, 5), item("b", 6, 0, 6, 5), item("c", 0, 5, 12, 2)];
    const moved = moveItem(layout, "b", 6, 1);
    expect(moved.find((entry) => entry.id === "a")).toMatchObject({ x: 0, y: 0 });
    // c gets pushed below the pinned block's new bottom edge
    expect(moved.find((entry) => entry.id === "c")!.y).toBeGreaterThanOrEqual(6);
  });

  it("resizes with per-kind minimums and pushes neighbors", () => {
    const layout = [item("a", 0, 0, 6, 5), item("b", 0, 5, 6, 2)];
    const resized = resizeItem(layout, "a", 6, 7, 3, 3);
    expect(resized.find((entry) => entry.id === "a")).toMatchObject({ h: 7 });
    expect(resized.find((entry) => entry.id === "b")).toMatchObject({ y: 7 });

    const clamped = resizeItem(layout, "a", 1, 1, 3, 3);
    expect(clamped.find((entry) => entry.id === "a")).toMatchObject({ w: 3, h: 3 });
  });

  it("finds the first free slot in reading order", () => {
    const layout = [item("a", 0, 0, 6, 5)];
    expect(findSlot(layout, 6, 5)).toEqual({ x: 6, y: 0 });
    expect(findSlot([item("a", 0, 0, 12, 4)], 6, 5)).toEqual({ x: 0, y: 4 });
    expect(findSlot([], 6, 5)).toEqual({ x: 0, y: 0 });
  });

  it("reports the layout bottom", () => {
    expect(layoutBottom([item("a", 0, 0, 6, 5), item("b", 0, 5, 6, 3)])).toBe(8);
    expect(layoutBottom([])).toBe(0);
  });

  it("migrates a legacy fixed-pixel page to fluid 12-column units", () => {
    const legacy: WebDesignPage = {
      id: "section-1",
      title: "Section 1",
      grid: {
        columns: 3,
        columnWidths: [280, 280, 280],
        rows: [
          { id: "row-1", height: 400 },
          { id: "row-2", height: 400 },
        ],
      },
      zones: [
        { id: "z1", nodeId: "n1", chartId: "c1", column: 0, row: 0, colSpan: 1, rowSpan: 1 },
        { id: "z2", nodeId: "n2", chartId: "c2", column: 1, row: 0, colSpan: 2, rowSpan: 1 },
        { id: "z3", nodeId: "n3", chartId: "c3", column: 0, row: 1, colSpan: 3, rowSpan: 1 },
      ],
      textZones: [],
    };

    const migrated = migrateLegacyPage(legacy);
    expect(isFluidGrid(migrated.grid)).toBe(true);
    expect(migrated.grid.columns).toBe(GRID_COLS);
    expect(migrated.grid.rowUnit).toBe(GRID_ROW_UNIT);

    const [z1, z2, z3] = migrated.zones;
    expect([z1.column, z1.colSpan]).toEqual([0, 4]);
    expect([z2.column, z2.colSpan]).toEqual([4, 8]);
    expect(z3.colSpan).toBe(12);
    // Second legacy row starts below the first (400px ≈ 6 units)
    expect(z3.row).toBe(z1.row + z1.rowSpan);
    // No overlaps after migration
    const items = pageToLayoutItems(migrated);
    for (const a of items) {
      for (const b of items) {
        if (a.id === b.id) continue;
        expect(collides(a, b)).toBe(false);
      }
    }
  });

  it("leaves fluid pages untouched apart from normalization", () => {
    const fluid: WebDesignPage = {
      id: "section-1",
      title: "Section 1",
      grid: { columns: 12, rowUnit: 72, rows: [] },
      zones: [{ id: "z1", nodeId: "n1", chartId: "c1", column: 3, row: 2, colSpan: 6, rowSpan: 5 }],
      textZones: [],
    };
    const migrated = migrateLegacyPage(fluid);
    expect(migrated.zones[0]).toMatchObject({ column: 3, row: 2, colSpan: 6, rowSpan: 5 });
  });
});
