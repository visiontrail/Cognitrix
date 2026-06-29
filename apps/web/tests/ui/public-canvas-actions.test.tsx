import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { PublicCanvasActions } from "../../components/public/public-canvas-actions";
import { ThemeProvider } from "../../lib/theme/context";

describe("PublicCanvasActions", () => {
  afterEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove("dark");
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.removeAttribute("data-theme-mode");
    document.documentElement.style.colorScheme = "";
  });

  it("places the theme toggle with export and print controls", async () => {
    render(
      <ThemeProvider>
        <PublicCanvasActions
          getCanvasElement={() => document.createElement("div")}
          filenameBase="published-canvas"
        />
      </ThemeProvider>
    );

    const exportButton = screen.getByRole("button", { name: "Export PNG" });
    const printButton = screen.getByRole("button", { name: "Print" });
    const themeButton = await screen.findByRole("button", {
      name: "Switch published page to dark theme",
    });
    const actionBar = exportButton.closest("[data-public-canvas-control]");

    expect(actionBar).toContainElement(printButton);
    expect(actionBar).toContainElement(themeButton);

    await userEvent.click(themeButton);

    await waitFor(() => {
      expect(document.documentElement).toHaveClass("dark");
      expect(document.documentElement.dataset.theme).toBe("dark");
      expect(window.localStorage.getItem("cognitrix.theme")).toBe("dark");
    });
  });
});
