import { describe, expect, it } from "vitest";
import type { Node } from "@xyflow/react";
import { findOpenCanvasPosition } from "@/lib/workspace/canvas-layout";

function rect(node: { position: { x: number; y: number }; width: number; height: number }) {
  return {
    left: node.position.x,
    top: node.position.y,
    right: node.position.x + node.width,
    bottom: node.position.y + node.height,
  };
}

function overlaps(
  a: { position: { x: number; y: number }; width: number; height: number },
  b: { position: { x: number; y: number }; width: number; height: number }
) {
  const ra = rect(a);
  const rb = rect(b);
  return !(ra.right <= rb.left || ra.left >= rb.right || ra.bottom <= rb.top || ra.top >= rb.bottom);
}

function makeNode(x: number, y: number, width: number, height: number): Node {
  return {
    id: `n-${x}-${y}`,
    type: "chartNode",
    position: { x, y },
    width,
    height,
    data: { width, height },
  } as Node;
}

describe("findOpenCanvasPosition", () => {
  it("places the first element at the canvas origin", () => {
    expect(findOpenCanvasPosition([], { width: 520, height: 380 }, "infinite")).toEqual({
      x: 50,
      y: 50,
    });
  });

  it("does not overlap an existing element on the infinite canvas", () => {
    const existing = makeNode(50, 50, 520, 380);
    const size = { width: 520, height: 380 };
    const position = findOpenCanvasPosition([existing], size, "infinite");
    const candidate = { position, ...size };
    expect(overlaps(candidate, { position: existing.position, width: 520, height: 380 })).toBe(false);
  });

  it("finds a free slot among several scattered elements", () => {
    const nodes = [
      makeNode(50, 50, 520, 380),
      makeNode(598, 50, 520, 380),
      makeNode(50, 458, 520, 380),
    ];
    const size = { width: 520, height: 380 };
    const position = findOpenCanvasPosition(nodes, size, "infinite");
    const candidate = { position, ...size };
    for (const node of nodes) {
      expect(overlaps(candidate, { position: node.position, width: 520, height: 380 })).toBe(false);
    }
  });

  it("ignores hidden nodes when searching for space", () => {
    const hidden = { ...makeNode(50, 50, 520, 380), hidden: true } as Node;
    const position = findOpenCanvasPosition([hidden], { width: 520, height: 380 }, "infinite");
    expect(position).toEqual({ x: 50, y: 50 });
  });

  it("keeps elements inside fixed-size (A4) page bounds", () => {
    // A4 portrait is 794×1123; place several text blocks and ensure all stay in bounds.
    const size = { width: 480, height: 220 };
    const placed: Node[] = [];
    for (let i = 0; i < 4; i += 1) {
      const position = findOpenCanvasPosition(placed, size, "a4-portrait");
      expect(position.x).toBeGreaterThanOrEqual(0);
      expect(position.y).toBeGreaterThanOrEqual(0);
      expect(position.x + size.width).toBeLessThanOrEqual(794);
      placed.push(makeNode(position.x, position.y, size.width, size.height));
    }
    // No two placed elements overlap.
    for (let i = 0; i < placed.length; i += 1) {
      for (let j = i + 1; j < placed.length; j += 1) {
        expect(
          overlaps(
            { position: placed[i].position, width: size.width, height: size.height },
            { position: placed[j].position, width: size.width, height: size.height }
          )
        ).toBe(false);
      }
    }
  });
});
