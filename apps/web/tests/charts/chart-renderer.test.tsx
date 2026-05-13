import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChartRenderer } from "../../components/genui/chart-renderer";

const { setOptionMock, disposeMock, resizeMock, registerTransformMock } = vi.hoisted(() => ({
  setOptionMock: vi.fn(),
  disposeMock: vi.fn(),
  resizeMock: vi.fn(),
  registerTransformMock: vi.fn(),
}));

vi.mock("echarts", () => ({
  registerTransform: registerTransformMock,
  init: vi.fn(() => ({
    setOption: setOptionMock,
    dispose: disposeMock,
    resize: resizeMock
  }))
}));

vi.mock("echarts-wordcloud", () => ({}), { virtual: true });

describe("ChartRenderer", () => {
  beforeEach(() => {
    setOptionMock.mockClear();
    disposeMock.mockClear();
    resizeMock.mockClear();
    registerTransformMock.mockClear();
  });

  it("builds fallback bar/line/pie options", async () => {
    const { rerender } = render(
      <ChartRenderer
        spec={{
          engine: "recharts",
          chart_type: "bar",
          title: "Bar",
          data: [{ label: "A", metric_value: 2 }],
          config: { xKey: "label", yKey: "metric_value" }
        }}
      />
    );
    expect(screen.getByTestId("echarts-chart")).toBeInTheDocument();
    await waitFor(() => expect(setOptionMock).toHaveBeenCalled());
    expect(setOptionMock.mock.calls.at(-1)?.[0]?.series?.[0]?.type).toBe("bar");

    setOptionMock.mockClear();
    rerender(
      <ChartRenderer
        spec={{
          engine: "recharts",
          chart_type: "line",
          title: "Line",
          data: [{ label: "A", metric_value: 2 }],
          config: { xKey: "label", yKey: "metric_value" }
        }}
      />
    );
    await waitFor(() => expect(setOptionMock).toHaveBeenCalled());
    expect(setOptionMock.mock.calls.at(-1)?.[0]?.series?.[0]?.type).toBe("line");

    setOptionMock.mockClear();
    rerender(
      <ChartRenderer
        spec={{
          engine: "recharts",
          chart_type: "pie",
          title: "Pie",
          data: [{ label: "A", metric_value: 2 }],
          config: { xKey: "label", yKey: "metric_value" }
        }}
      />
    );
    await waitFor(() => expect(setOptionMock).toHaveBeenCalled());
    expect(setOptionMock.mock.calls.at(-1)?.[0]?.series?.[0]?.type).toBe("pie");
  }, 10000);

  it("routes high-volume option to echarts renderer", async () => {
    const option = {
      xAxis: {
        type: "category",
        data: Array.from({ length: 1000 }, (_, index) => `point-${index}`)
      },
      yAxis: { type: "value" },
      series: [
        {
          type: "line",
          data: Array.from({ length: 1000 }, (_, index) => index)
        }
      ]
    };

    render(
      <ChartRenderer
        spec={{
          engine: "echarts",
          chart_type: "line",
          title: "High Volume",
          data: [],
          config: { option }
        }}
      />
    );

    expect(screen.getByTestId("echarts-chart")).toBeInTheDocument();
    await waitFor(() => expect(setOptionMock).toHaveBeenCalled());
    const actual = setOptionMock.mock.calls.at(-1)?.[0] as Record<string, unknown>;
    expect(actual.xAxis).toEqual(option.xAxis);
    expect(actual.yAxis).toEqual(option.yAxis);
    expect(actual.series).toEqual(option.series);
  });

  it("builds a negative bar fallback option", async () => {
    render(
      <ChartRenderer
        spec={{
          engine: "echarts",
          chart_type: "negative_bar",
          title: "Delta",
          data: [
            { label: "Down", metric_value: -2 },
            { label: "Up", metric_value: 3 }
          ],
          config: { xKey: "label", yKey: "metric_value" }
        }}
      />
    );

    expect(screen.getByTestId("echarts-chart")).toBeInTheDocument();
    await waitFor(() => expect(setOptionMock).toHaveBeenCalled());
    const option = setOptionMock.mock.calls.at(-1)?.[0] as Record<string, unknown>;
    expect(option.xAxis).toMatchObject({ type: "value", position: "top" });
    expect(option.yAxis).toMatchObject({ type: "category", axisLabel: { show: false } });
    const series = option.series as Array<Record<string, unknown>>;
    expect(series[0]).toMatchObject({ type: "bar", stack: "Total", label: { show: true, formatter: "{b}" } });
    const data = series[0].data as Array<Record<string, unknown>>;
    expect(data[0]).toMatchObject({ value: -2, label: { position: "right" } });
    expect(data[1]).toMatchObject({ value: 3 });
  });

  it("builds and registers a scatter clustering option", async () => {
    render(
      <ChartRenderer
        spec={{
          engine: "echarts",
          chart_type: "scatter-clustering",
          title: "Clusters",
          data: [
            { employee: "A", tenure: 1, salary: 10 },
            { employee: "B", tenure: 2, salary: 12 },
            { employee: "C", tenure: 8, salary: 30 },
            { employee: "D", tenure: 9, salary: 32 }
          ],
          config: { xKey: "tenure", yKey: "salary", nameKey: "employee" }
        }}
      />
    );

    expect(screen.getByTestId("echarts-chart")).toBeInTheDocument();
    await waitFor(() => expect(setOptionMock).toHaveBeenCalled());
    expect(registerTransformMock).toHaveBeenCalled();
    const option = setOptionMock.mock.calls.at(-1)?.[0] as Record<string, unknown>;
    expect(option.__requiresEchartsStat__).toEqual({ transforms: ["clustering"] });
    const dataset = option.dataset as Array<Record<string, unknown>>;
    expect(dataset[1].transform).toMatchObject({
      type: "ecStat:clustering",
      config: {
        dimensions: [0, 1],
        outputClusterIndexDimension: { index: 3, name: "cluster" }
      }
    });
    expect(option.visualMap).toMatchObject({ type: "piecewise", dimension: 3 });
    const series = option.series as Array<Record<string, unknown>>;
    expect(series[0]).toMatchObject({ type: "scatter", datasetIndex: 1 });
  });
});
