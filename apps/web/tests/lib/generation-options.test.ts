import { describe, expect, it } from "vitest";

import {
  GENERATION_OPTIONS,
  buildGenerationOptionPayload,
  generationOptionIdsFromPayload,
  isGenerationOptionId,
  selectedGenerationOptions,
  toggleGenerationOption,
  type GenerationOptionId,
} from "@/lib/chat/generation-options";

function setOf(...ids: GenerationOptionId[]): Set<GenerationOptionId> {
  return new Set(ids);
}

describe("generation-options registry", () => {
  it("exposes every option with the i18n keys the composer renders", () => {
    for (const option of GENERATION_OPTIONS) {
      expect(option.menuLabelKey).toMatch(/^chat\./);
      expect(option.chipLabelKey).toMatch(/^chat\./);
      expect(option.removeLabelKey).toMatch(/^chat\./);
      expect(option.hintKey).toMatch(/^chat\./);
      expect(option.icon).toBeTypeOf("object"); // a forwardRef icon component
      expect(option.payload).toBeTypeOf("object");
    }
  });

  it("recognizes known option ids", () => {
    expect(isGenerationOptionId("multi_chart")).toBe(true);
    expect(isGenerationOptionId("data_labels")).toBe(true);
    expect(isGenerationOptionId("nope")).toBe(false);
  });

  it("toggles an id on and off without mutating the source set", () => {
    const empty = setOf();
    const withOne = toggleGenerationOption(empty, "multi_chart");
    expect(empty.size).toBe(0); // source untouched
    expect([...withOne]).toEqual(["multi_chart"]);

    const withoutOne = toggleGenerationOption(withOne, "multi_chart");
    expect([...withoutOne]).toEqual([]);
  });

  it("returns active options in registry order regardless of insertion order", () => {
    const selected = setOf("data_labels", "multi_chart");
    const ordered = selectedGenerationOptions(selected).map((option) => option.id);
    expect(ordered).toEqual(["multi_chart", "data_labels"]);
  });

  it("merges payload contributions for the empty, single, and combined sets", () => {
    expect(buildGenerationOptionPayload(setOf())).toEqual({});
    expect(buildGenerationOptionPayload(setOf("multi_chart"))).toEqual({
      generationStrategy: "multi_chart",
    });
    expect(buildGenerationOptionPayload(setOf("data_labels"))).toEqual({
      showDataLabels: true,
    });
    expect(buildGenerationOptionPayload(setOf("multi_chart", "data_labels"))).toEqual({
      generationStrategy: "multi_chart",
      showDataLabels: true,
    });
  });

  it("recovers option ids from a sent payload (round-trips buildGenerationOptionPayload)", () => {
    expect(generationOptionIdsFromPayload({})).toEqual([]);
    expect(generationOptionIdsFromPayload({ generationStrategy: "multi_chart" })).toEqual([
      "multi_chart",
    ]);
    expect(generationOptionIdsFromPayload({ showDataLabels: true })).toEqual(["data_labels"]);
    expect(
      generationOptionIdsFromPayload({ generationStrategy: "multi_chart", showDataLabels: true })
    ).toEqual(["multi_chart", "data_labels"]);
    // a falsey/absent data-labels flag must not be reported as selected
    expect(generationOptionIdsFromPayload({ showDataLabels: false })).toEqual([]);
  });
});
