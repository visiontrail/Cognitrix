import { describe, expect, it } from "vitest";
import {
  CANVAS_PAGE_GAP,
  MAX_CANVAS_PAGES,
  getCanvasFormatPreset,
  getCanvasPageCount,
  getCanvasPageRects,
  getCanvasPageStride,
  getMaxOccupiedCanvasPage,
  isBoundedCanvasFormat,
} from "@/lib/workspace/canvas-formats";

describe("canvas format page helpers", () => {
  it("tags slide vs document print styles", () => {
    expect(getCanvasFormatPreset("wide-16-9").printStyle).toBe("slide");
    expect(getCanvasFormatPreset("a4-portrait").printStyle).toBe("document");
    expect(getCanvasFormatPreset("a3-portrait").printStyle).toBe("document");
    expect(getCanvasFormatPreset("letter-portrait").printStyle).toBe("document");
  });

  it("only treats fixed presets as bounded/paginated", () => {
    expect(isBoundedCanvasFormat(getCanvasFormatPreset("a4-portrait"))).toBe(true);
    expect(isBoundedCanvasFormat(getCanvasFormatPreset("wide-16-9"))).toBe(true);
    expect(isBoundedCanvasFormat(getCanvasFormatPreset("infinite"))).toBe(false);
    expect(isBoundedCanvasFormat(getCanvasFormatPreset("web-design"))).toBe(false);
  });

  it("clamps the resolved page count", () => {
    expect(getCanvasPageCount("a4-portrait", { "a4-portrait": 3 })).toBe(3);
    expect(getCanvasPageCount("a4-portrait", undefined)).toBe(1);
    expect(getCanvasPageCount("a4-portrait", { "a4-portrait": 0 })).toBe(1);
    expect(getCanvasPageCount("a4-portrait", { "a4-portrait": 999 })).toBe(MAX_CANVAS_PAGES);
    // Unbounded formats never paginate, regardless of stored value.
    expect(getCanvasPageCount("infinite", { infinite: 5 })).toBe(1);
  });

  it("stacks page rects vertically with a gap between them", () => {
    const preset = getCanvasFormatPreset("a4-portrait");
    const stride = getCanvasPageStride(preset);
    expect(stride).toBe(preset.height! + CANVAS_PAGE_GAP);

    const rects = getCanvasPageRects(preset, 3);
    expect(rects).toHaveLength(3);
    expect(rects[0]).toMatchObject({ index: 0, x: 0, y: 0, width: preset.width, height: preset.height });
    expect(rects[1].y).toBe(stride);
    expect(rects[2].y).toBe(stride * 2);

    // Unbounded formats produce no page frames.
    expect(getCanvasPageRects(getCanvasFormatPreset("infinite"), 4)).toEqual([]);
  });

  it("reports the last page touched by content", () => {
    const preset = getCanvasFormatPreset("a4-portrait");
    const stride = getCanvasPageStride(preset);
    expect(getMaxOccupiedCanvasPage([], preset)).toBe(0);
    expect(
      getMaxOccupiedCanvasPage([{ position: { x: 0, y: 0 }, height: 200 }], preset)
    ).toBe(0);
    expect(
      getMaxOccupiedCanvasPage([{ position: { x: 0, y: stride + 10 }, height: 200 }], preset)
    ).toBe(1);
    // Hidden nodes are ignored.
    expect(
      getMaxOccupiedCanvasPage(
        [{ position: { x: 0, y: stride * 4 }, height: 200, hidden: true }],
        preset
      )
    ).toBe(0);
  });
});
