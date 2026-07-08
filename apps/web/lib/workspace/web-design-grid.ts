/**
 * Legacy fixed-pixel grid helpers. Only published snapshots created before the
 * fluid 12-column layout still carry pixel column widths; the editor itself no
 * longer produces them.
 */
export const DEFAULT_WEB_DESIGN_COLUMN_WIDTH = 280;
export const MIN_WEB_DESIGN_COLUMN_WIDTH = 120;
export const MAX_WEB_DESIGN_COLUMN_WIDTH = 640;

export type WebDesignGridLike = {
  columns: number;
  columnWidths?: number[];
};

export function normalizeWebDesignColumnWidths(
  columns: number,
  columnWidths: unknown
): number[] {
  const safeColumns = clamp(Math.trunc(Number(columns) || 3), 2, 10);
  const widths = Array.isArray(columnWidths) ? columnWidths : [];

  return Array.from({ length: safeColumns }, (_, index) =>
    clamp(Number(widths[index] ?? DEFAULT_WEB_DESIGN_COLUMN_WIDTH), MIN_WEB_DESIGN_COLUMN_WIDTH, MAX_WEB_DESIGN_COLUMN_WIDTH)
  );
}

export function getWebDesignGridTemplateColumns(grid: WebDesignGridLike): string {
  return normalizeWebDesignColumnWidths(grid.columns, grid.columnWidths)
    .map((width) => `${width}px`)
    .join(" ");
}

export function getWebDesignGridWidth(grid: WebDesignGridLike): number {
  return normalizeWebDesignColumnWidths(grid.columns, grid.columnWidths).reduce(
    (sum, width) => sum + width,
    0
  );
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
