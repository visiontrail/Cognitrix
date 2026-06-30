import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth/auth-client", async () => {
  const actual = await vi.importActual<typeof import("../../lib/auth/auth-client")>(
    "../../lib/auth/auth-client"
  );
  return {
    ...actual,
    apiGetMe: vi.fn(),
    apiLogout: vi.fn(),
  };
});

import { PublicCanvasActions } from "../../components/public/public-canvas-actions";
import { apiGetMe } from "../../lib/auth/auth-client";
import { clearInMemoryToken, setInMemoryToken } from "../../lib/auth/session";
import { I18nProvider } from "../../lib/i18n/context";
import { ThemeProvider } from "../../lib/theme/context";

const apiGetMeMock = vi.mocked(apiGetMe);

describe("PublicCanvasActions", () => {
  afterEach(() => {
    vi.clearAllMocks();
    clearInMemoryToken();
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
    const workspaceButton = screen.getByRole("link", { name: "Back to workspace" });
    const printButton = screen.getByRole("button", { name: "Print" });
    const themeButton = await screen.findByRole("button", {
      name: "Switch published page to dark theme",
    });
    const actionBar = exportButton.closest("[data-public-canvas-control]");

    expect(actionBar).toContainElement(workspaceButton);
    expect(actionBar).toContainElement(printButton);
    expect(actionBar).toContainElement(themeButton);

    await userEvent.click(themeButton);

    await waitFor(() => {
      expect(document.documentElement).toHaveClass("dark");
      expect(document.documentElement.dataset.theme).toBe("dark");
      expect(window.localStorage.getItem("cognitrix.theme")).toBe("dark");
    });
  });

  it("shows the AI Assistant action only when assistant data is available", async () => {
    const user = userEvent.setup();
    const onOpenAssistant = vi.fn();
    const { rerender } = render(
      <ThemeProvider>
        <PublicCanvasActions
          getCanvasElement={() => document.createElement("div")}
          filenameBase="published-canvas"
        />
      </ThemeProvider>
    );

    expect(screen.queryByRole("button", { name: "Open AI Assistant" })).not.toBeInTheDocument();

    rerender(
      <ThemeProvider>
        <PublicCanvasActions
          getCanvasElement={() => document.createElement("div")}
          filenameBase="published-canvas"
          assistantAvailable
          onOpenAssistant={onOpenAssistant}
        />
      </ThemeProvider>
    );

    await user.click(screen.getByRole("button", { name: "Open AI Assistant" }));
    expect(onOpenAssistant).toHaveBeenCalledTimes(1);
  });

  it("shows account menu actions for signed-out public viewers", async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <PublicCanvasActions
          getCanvasElement={() => document.createElement("div")}
          filenameBase="published-canvas"
        />
      </ThemeProvider>
    );

    await user.click(screen.getByRole("button", { name: "Open account menu" }));

    expect(screen.getAllByText("Not signed in").length).toBeGreaterThan(0);
    expect(screen.getByText("Viewing as guest")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Language" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Login" })).toBeInTheDocument();
  });

  it("switches language from the public account menu", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem("cognitrix.locale", "en-US");

    render(
      <ThemeProvider>
        <I18nProvider>
          <PublicCanvasActions
            getCanvasElement={() => document.createElement("div")}
            filenameBase="published-canvas"
          />
        </I18nProvider>
      </ThemeProvider>
    );

    await user.click(screen.getByRole("button", { name: "Open account menu" }));
    await user.click(screen.getByRole("menuitem", { name: "中文（简体）" }));

    await waitFor(() => {
      expect(window.localStorage.getItem("cognitrix.locale")).toBe("zh-CN");
      expect(document.documentElement.lang).toBe("zh-CN");
    });
  });

  it("shows the signed-in user with language and logout actions", async () => {
    const user = userEvent.setup();
    setInMemoryToken("header.payload.signature", Math.floor(Date.now() / 1000) + 3600);
    apiGetMeMock.mockResolvedValue({
      id: "u1",
      email: "ada@example.com",
      display_name: "Ada Lovelace",
      job_id: 1,
      last_login_at: null,
      available_workspaces: [],
    });

    render(
      <ThemeProvider>
        <PublicCanvasActions
          getCanvasElement={() => document.createElement("div")}
          filenameBase="published-canvas"
        />
      </ThemeProvider>
    );

    expect(await screen.findByRole("button", { name: "Open account menu" })).toHaveTextContent("Ada Lovelace");
    await user.click(screen.getByRole("button", { name: "Open account menu" }));

    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Language" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Logout" })).toBeInTheDocument();
  });
});
