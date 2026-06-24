import { describe, expect, it } from "vitest";

import { applyDataLabels } from "@/lib/charts/data-labels";

type AnyOption = Record<string, unknown>;

function firstSeries(option: AnyOption): Record<string, unknown> {
  const series = option.series;
  if (Array.isArray(series)) {
    return series[0] as Record<string, unknown>;
  }
  return series as Record<string, unknown>;
}

function label(series: Record<string, unknown>): Record<string, unknown> {
  return series.label as Record<string, unknown>;
}

describe("applyDataLabels", () => {
  it("turns on value labels for a vertical bar chart", () => {
    const option: AnyOption = {
      xAxis: { type: "category", data: ["A", "B"] },
      yAxis: { type: "value" },
      series: [{ type: "bar", data: [10, 20] }],
    };

    const next = applyDataLabels(option);
    const lbl = label(firstSeries(next));

    expect(lbl.show).toBe(true);
    expect(lbl.position).toBe("top");
    expect(lbl.formatter).toBe("{c}");
  });

  it("positions labels to the right for horizontal bars", () => {
    const option: AnyOption = {
      xAxis: { type: "value" },
      yAxis: { type: "category", data: ["A", "B"] },
      series: [{ type: "bar", data: [10, 20] }],
    };

    const lbl = label(firstSeries(applyDataLabels(option)));
    expect(lbl.position).toBe("right");
  });

  it("places labels inside stacked bars", () => {
    const option: AnyOption = {
      xAxis: { type: "category", data: ["A"] },
      yAxis: { type: "value" },
      series: [
        { type: "bar", stack: "total", data: [10] },
        { type: "bar", stack: "total", data: [20] },
      ],
    };

    const series = (applyDataLabels(option).series as Record<string, unknown>[]);
    expect(label(series[0]).position).toBe("inside");
    expect(label(series[1]).position).toBe("inside");
    expect(label(series[1]).show).toBe(true);
  });

  it("surfaces the raw value on a percentage-only pie label", () => {
    const option: AnyOption = {
      series: [
        {
          type: "pie",
          label: { show: true, formatter: "{b}\n{d}%" },
          data: [{ name: "A", value: 3 }],
        },
      ],
    };

    const lbl = label(firstSeries(applyDataLabels(option)));
    expect(lbl.show).toBe(true);
    expect(lbl.formatter).toBe("{b}: {c} ({d}%)");
  });

  it("adds a name+value formatter to a pie without one", () => {
    const option: AnyOption = {
      series: [{ type: "pie", data: [{ name: "A", value: 3 }] }],
    };

    const lbl = label(firstSeries(applyDataLabels(option)));
    expect(lbl.formatter).toBe("{b}: {c} ({d}%)");
  });

  it("respects an existing string formatter that already shows the value", () => {
    const option: AnyOption = {
      xAxis: { type: "category", data: ["A"] },
      yAxis: { type: "value" },
      series: [{ type: "bar", label: { formatter: "¥{c}" }, data: [10] }],
    };

    const lbl = label(firstSeries(applyDataLabels(option)));
    expect(lbl.formatter).toBe("¥{c}");
    expect(lbl.show).toBe(true);
  });

  it("preserves a function formatter and an explicit position", () => {
    const fn = (params: unknown) => String(params);
    const option: AnyOption = {
      xAxis: { type: "category", data: ["A"] },
      yAxis: { type: "value" },
      series: [{ type: "bar", label: { formatter: fn, position: "insideTop" }, data: [10] }],
    };

    const lbl = label(firstSeries(applyDataLabels(option)));
    expect(lbl.formatter).toBe(fn);
    expect(lbl.position).toBe("insideTop");
    expect(lbl.show).toBe(true);
  });

  it("forces labels back on even when explicitly disabled", () => {
    const option: AnyOption = {
      series: [{ type: "line", label: { show: false }, data: [1, 2, 3] }],
    };

    const lbl = label(firstSeries(applyDataLabels(option)));
    expect(lbl.show).toBe(true);
    expect(lbl.position).toBe("top");
    expect(lbl.formatter).toBe("{c}");
  });

  it("handles a single series object (not an array)", () => {
    const option: AnyOption = {
      series: { type: "funnel", data: [{ name: "A", value: 5 }] },
    };

    const lbl = label(firstSeries(applyDataLabels(option)));
    expect(lbl.show).toBe(true);
    expect(lbl.formatter).toBe("{b}: {c}");
  });

  it("does not inject a {c} formatter for array-valued series like boxplot", () => {
    const option: AnyOption = {
      series: [{ type: "boxplot", data: [[1, 2, 3, 4, 5]] }],
    };

    const lbl = label(firstSeries(applyDataLabels(option)));
    expect(lbl.show).toBe(true);
    expect(lbl.formatter).toBeUndefined();
  });

  it("is a no-op when there is no series and never mutates the input", () => {
    const tableOption: AnyOption = { __table__: true, series: [] };
    expect(applyDataLabels(tableOption)).toBe(tableOption);

    const original: AnyOption = {
      xAxis: { type: "category", data: ["A"] },
      yAxis: { type: "value" },
      series: [{ type: "bar", data: [10] }],
    };
    const snapshot = JSON.stringify(original);
    applyDataLabels(original);
    expect(JSON.stringify(original)).toBe(snapshot);
  });
});
