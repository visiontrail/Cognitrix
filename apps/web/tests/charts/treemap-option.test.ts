import { describe, expect, it } from "vitest";

import { buildRichTreemapFallbackOption, enhanceRichTreemapOption } from "../../lib/charts/treemap-option";

describe("rich treemap option", () => {
  it("builds grouped treemap data with extra metrics", () => {
    const option = buildRichTreemapFallbackOption({
      title: "Cost",
      rows: [
        { department: "Engineering", employee: "Ada", cost: 120, level: "L5" },
        { department: "Engineering", employee: "Grace", cost: 80, level: "L4" },
        { department: "Sales", employee: "Lin", cost: 50, level: "L3" },
      ],
      xKey: "department",
      yKey: "cost",
      nameKey: "employee",
    });

    expect(option.__cognitrixRichTreemap).toBe(true);
    const series = option.series as Array<Record<string, unknown>>;
    const data = series[0].data as Array<Record<string, unknown>>;
    const engineering = data[0];
    expect(engineering.name).toBe("Engineering");
    expect(engineering.value).toEqual([200, 80, 2]);

    const children = engineering.children as Array<Record<string, unknown>>;
    expect(children[0].name).toBe("Ada");
    expect(children[0].rawFields).toEqual([{ name: "level", value: "L5" }]);
  });

  it("injects label and tooltip formatter functions at render time", () => {
    const option = buildRichTreemapFallbackOption({
      title: "Cost",
      rows: [{ department: "Engineering", employee: "Ada", cost: 120 }],
      xKey: "department",
      yKey: "cost",
      nameKey: "employee",
    });

    const enhanced = enhanceRichTreemapOption(option);
    const series = enhanced.series as Array<Record<string, unknown>>;
    const firstSeries = series[0];
    const label = firstSeries.label as Record<string, unknown>;
    const tooltip = enhanced.tooltip as Record<string, unknown>;

    expect(typeof label.formatter).toBe("function");
    expect(typeof tooltip.formatter).toBe("function");
  });
});
