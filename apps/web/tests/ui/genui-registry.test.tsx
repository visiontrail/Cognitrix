import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GenUIRegistry, hasRegistryEntry } from "../../components/genui/registry";
import { GENUI_REGISTRY_KEYS } from "../../lib/genui/catalog";

describe("GenUI registry", () => {
  it("maps every catalog key to a renderer entry", () => {
    for (const key of GENUI_REGISTRY_KEYS) {
      expect(hasRegistryEntry(key)).toBe(true);
    }
  });

  it("renders a valid spec and blocks an invalid spec", () => {
    render(
      <GenUIRegistry
        rawSpec={{
          engine: "recharts",
          chart_type: "bar",
          title: "Attrition",
          data: [{ department: "RD", metric_value: 10 }],
          config: { xKey: "department", yKey: "metric_value" }
        }}
      />
    );
    expect(screen.getByTestId("echarts-chart")).toBeInTheDocument();

    render(
      <GenUIRegistry
        rawSpec={{
          engine: "unsupported",
          chart_type: "bar",
          title: "Broken",
          data: [],
          config: {}
        }}
      />
    );
    expect(screen.getByText("Unsupported chart spec format")).toBeInTheDocument();
  });
});
