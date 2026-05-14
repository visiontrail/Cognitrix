type KpiOptionInput = {
  title: string;
  value: number;
  name: string;
};

export function buildGaugeFallbackOption({ title, value, name }: KpiOptionInput): Record<string, unknown> {
  const max = value > 100 ? Math.ceil(value / 10) * 10 : 100;

  return {
    title: { text: title, left: "center", top: 8 },
    tooltip: { formatter: `${name}: {c}` },
    series: [
      {
        type: "gauge",
        min: 0,
        max,
        startAngle: 205,
        endAngle: -25,
        radius: "76%",
        center: ["50%", "58%"],
        progress: {
          show: true,
          width: 16,
          itemStyle: { color: "#c96442" },
        },
        axisLine: {
          lineStyle: {
            width: 16,
            color: [[1, "#d9d3c4"]],
          },
        },
        pointer: {
          show: true,
          width: 5,
          length: "56%",
          itemStyle: { color: "#4d4c48" },
        },
        axisTick: { show: false },
        splitLine: { length: 10, lineStyle: { color: "#bdb5a6", width: 2 } },
        axisLabel: { color: "#777066", distance: 20 },
        detail: {
          formatter: "{value}",
          offsetCenter: [0, "42%"],
          color: "#141413",
          fontSize: 28,
          fontWeight: 700,
        },
        data: [{ value, name }],
      },
    ],
  };
}

export function buildSingleValueFallbackOption({ title, value, name }: KpiOptionInput): Record<string, unknown> {
  const displayValue = formatKpiValue(value);

  return {
    title: { text: title, left: "center", top: 12 },
    tooltip: { trigger: "item", formatter: `${name}: ${displayValue}` },
    series: [],
    graphic: [
      {
        type: "group",
        left: "center",
        top: "middle",
        children: [
          {
            type: "text",
            left: "center",
            top: -42,
            style: {
              text: displayValue,
              fill: "#141413",
              fontSize: 58,
              fontWeight: 800,
              textAlign: "center",
              textVerticalAlign: "middle",
            },
          },
          {
            type: "text",
            left: "center",
            top: 28,
            style: {
              text: name,
              fill: "#777066",
              fontSize: 14,
              fontWeight: 600,
              textAlign: "center",
              textVerticalAlign: "middle",
            },
          },
        ],
      },
    ],
  };
}

function formatKpiValue(value: number): string {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: Number.isInteger(value) ? 0 : 2,
  }).format(value);
}
