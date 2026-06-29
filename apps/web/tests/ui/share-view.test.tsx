import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ShareView } from "../../components/workbench/share-view";
import { ThemeProvider } from "../../lib/theme/context";

const fetchMock = vi.fn<typeof fetch>();
const AUTH_EXPIRES_AT = 4102444800;

describe("Share view rehydration UI", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove("dark");
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.removeAttribute("data-theme-mode");
    document.documentElement.style.colorScheme = "";
    fetchMock.mockReset();
  });

  it("rehydrates chart and messages from saved ai_state", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "share-token",
            token_type: "bearer",
            expires_at: AUTH_EXPIRES_AT
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            view_id: "view-1",
            title: "Shared Snapshot",
            current_version: 2,
            owner_user_id: "alice",
            updated_at: "2026-04-08T10:48:00Z",
            ai_state: {
              active_spec: {
                engine: "recharts",
                chart_type: "line",
                title: "Attrition Trend",
                data: [{ month: "2026-01", metric_value: 0.1 }],
                config: { xKey: "month", yKey: "metric_value" }
              },
              messages: [{ id: "m-1", role: "assistant", text: "restored answer" }]
            }
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      );

    render(<ShareView apiBaseUrl="http://localhost:8000" viewId="view-1" />);

    await screen.findByText("Shared Snapshot");
    expect(screen.getByTestId("echarts-chart")).toBeInTheDocument();
    expect(screen.getByText(/restored answer/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/share/view-1",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer share-token"
        })
      })
    );
  });

  it("lets shared-view visitors switch between light and dark themes", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "share-token",
            token_type: "bearer",
            expires_at: AUTH_EXPIRES_AT
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            view_id: "view-1",
            title: "Shared Snapshot",
            current_version: 2,
            owner_user_id: "alice",
            updated_at: "2026-04-08T10:48:00Z",
            ai_state: { messages: [] }
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      );

    render(
      <ThemeProvider>
        <ShareView apiBaseUrl="http://localhost:8000" viewId="view-1" />
      </ThemeProvider>
    );

    const toggle = await screen.findByRole("button", { name: "Switch shared view to dark theme" });
    await userEvent.click(toggle);

    await waitFor(() => {
      expect(document.documentElement).toHaveClass("dark");
      expect(document.documentElement.dataset.theme).toBe("dark");
      expect(window.localStorage.getItem("cognitrix.theme")).toBe("dark");
    });

    await userEvent.click(screen.getByRole("button", { name: "Switch shared view to light theme" }));

    await waitFor(() => {
      expect(document.documentElement).not.toHaveClass("dark");
      expect(document.documentElement.dataset.theme).toBe("light");
      expect(window.localStorage.getItem("cognitrix.theme")).toBe("light");
    });
  });
});
