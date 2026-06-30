import React from "react";
import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChartPreview } from "../../components/charts/chart-preview";
import type { ChartSpec } from "../../types/chart";

const { setOptionMock, disposeMock, resizeMock } = vi.hoisted(() => ({
  setOptionMock: vi.fn(),
  disposeMock: vi.fn(),
  resizeMock: vi.fn(),
}));

vi.mock("echarts", () => ({
  init: vi.fn(() => ({
    setOption: setOptionMock,
    dispose: disposeMock,
    resize: resizeMock,
  })),
}));

vi.mock("echarts-wordcloud", () => ({}), { virtual: true });

const pieSpecWithoutLegend: ChartSpec = {
  chartType: "pie",
  title: "Languages",
  echartsOption: {
    title: { text: "Languages", left: "center" },
    tooltip: { trigger: "item" },
    series: [
      {
        type: "pie",
        radius: "50%",
        data: [
          { name: "Mandarin", value: 2 },
          { name: "English", value: 1 },
        ],
        label: { show: true, formatter: "{b}: {c}" },
      },
    ],
  },
};

describe("ChartPreview", () => {
  beforeEach(() => {
    setOptionMock.mockClear();
    disposeMock.mockClear();
    resizeMock.mockClear();
  });

  it("does not create a legend for dark-mode charts that did not request one", async () => {
    render(<ChartPreview spec={pieSpecWithoutLegend} theme="dark" />);

    await waitFor(() => expect(setOptionMock).toHaveBeenCalled());
    const option = setOptionMock.mock.calls.at(-1)?.[0] as Record<string, unknown>;

    expect(Object.prototype.hasOwnProperty.call(option, "legend")).toBe(false);
    expect(option.series).toEqual(pieSpecWithoutLegend.echartsOption.series);
  });

  it("keeps explicit legends readable in dark mode", async () => {
    render(
      <ChartPreview
        theme="dark"
        spec={{
          ...pieSpecWithoutLegend,
          echartsOption: {
            ...pieSpecWithoutLegend.echartsOption,
            legend: { orient: "vertical", left: "left" },
          },
        }}
      />
    );

    await waitFor(() => expect(setOptionMock).toHaveBeenCalled());
    const option = setOptionMock.mock.calls.at(-1)?.[0] as Record<string, unknown>;

    expect(option.legend).toMatchObject({
      orient: "vertical",
      left: "left",
      textStyle: { color: "#e5e7eb" },
    });
  });
});
