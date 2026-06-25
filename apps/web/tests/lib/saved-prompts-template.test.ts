import { describe, expect, it } from "vitest";

import {
  capabilitiesToGenerationOptions,
  insertAtSelection,
  parseVariables,
  renderTemplate,
} from "../../lib/saved-prompts/template";

describe("parseVariables", () => {
  it("extracts variables in first-seen order", () => {
    expect(parseVariables("Analyze {department} in {month}")).toEqual({
      ok: true,
      variables: ["department", "month"],
    });
  });

  it("collapses repeated exact variables", () => {
    expect(parseVariables("Compare {department} with {department}")).toEqual({
      ok: true,
      variables: ["department"],
    });
  });

  it("ignores double braces", () => {
    expect(parseVariables("Localized {{not_var}} text")).toEqual({ ok: true, variables: [] });
  });

  it("treats escaped braces as literal", () => {
    const result = parseVariables('JSON like \\{\\"d\\": \\"{department}\\"\\}');
    expect(result).toEqual({ ok: true, variables: ["department"] });
  });

  it("rejects malformed variable names", () => {
    const result = parseVariables("Compare {2026_month}");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errorCode).toBe("PROMPT_VARIABLE_INVALID");
  });

  it("rejects case-ambiguous variables", () => {
    const result = parseVariables("Compare {Department} with {department}");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errorCode).toBe("PROMPT_VARIABLE_AMBIGUOUS");
  });
});

describe("renderTemplate", () => {
  it("substitutes every occurrence of a variable", () => {
    expect(
      renderTemplate("Analyze {department} attrition in {month}", {
        department: "Sales",
        month: "May 2026",
      }),
    ).toBe("Analyze Sales attrition in May 2026");
  });

  it("renders repeated variables from a single value", () => {
    expect(renderTemplate("{x} and {x}", { x: "Q1" })).toBe("Q1 and Q1");
  });

  it("collapses escaped braces to literal braces", () => {
    expect(renderTemplate("\\{x\\} = {v}", { v: "1" })).toBe("{x} = 1");
  });

  it("is case-insensitive when matching values", () => {
    expect(renderTemplate("{Country}", { country: "FR" })).toBe("FR");
  });
});

describe("insertAtSelection", () => {
  it("inserts at the caret with safe spacing", () => {
    const { text, caret } = insertAtSelection("Please ", 7, 7, "summarize this table");
    expect(text).toBe("Please summarize this table");
    expect(caret).toBe(text.length);
  });

  it("adds a space when the preceding char is not whitespace", () => {
    const { text } = insertAtSelection("Please", 6, 6, "go");
    expect(text).toBe("Please go");
  });

  it("replaces the selected range", () => {
    const { text } = insertAtSelection("Analyze old text now", 8, 16, "turnover by department");
    expect(text).toBe("Analyze turnover by department now");
  });

  it("inserts into an empty composer without leading space", () => {
    const { text, caret } = insertAtSelection("", 0, 0, "hello");
    expect(text).toBe("hello");
    expect(caret).toBe(5);
  });
});

describe("capabilitiesToGenerationOptions", () => {
  it("maps known composer options and drops file_upload", () => {
    expect(capabilitiesToGenerationOptions(["multi_chart", "file_upload", "data_labels"])).toEqual([
      "multi_chart",
      "data_labels",
    ]);
  });

  it("de-duplicates", () => {
    expect(capabilitiesToGenerationOptions(["multi_chart", "multi_chart"])).toEqual(["multi_chart"]);
  });
});
