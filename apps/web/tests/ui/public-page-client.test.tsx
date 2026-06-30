import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PublicPageClient } from "../../components/public/public-page-client";
import { fetchPublicManifest, PublicPageError, streamPublicAssistant } from "../../lib/public/api";

vi.mock("@/lib/public/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/public/api")>("../../lib/public/api");
  return {
    ...actual,
    fetchPublicManifest: vi.fn(),
    fetchPublicChartData: vi.fn(),
    streamPublicAssistant: vi.fn(),
  };
});

vi.mock("@/components/public/published-canvas-renderers", () => ({
  PublishedFreeCanvas: () => <div data-testid="published-free-canvas" />,
  PublishedFixedCanvas: () => <div data-testid="published-fixed-canvas" />,
}));

const fetchPublicManifestMock = vi.mocked(fetchPublicManifest);
const streamPublicAssistantMock = vi.mocked(streamPublicAssistant);

function manifestBase(kind: "free_layout" | "fixed_size" | "web_page") {
  return {
    version: 1,
    published_at: "2026-06-24T00:00:00+00:00",
    manifest: {
      schema_version: 2 as const,
      canvas: { format_id: kind === "web_page" ? "web-design" : "infinite", kind },
      content: { nodes: [], edges: [] },
      layout: {
        grid: { columns: 1, rows: [{ id: "row-1", height: 240 }] },
        zones: [],
        pages: [
          {
            id: "section-1",
            title: "Section 1",
            grid: { columns: 1, rows: [{ id: "row-1", height: 240 }] },
            zones: [],
            textZones: [],
          },
        ],
        activePageId: "section-1",
      },
      sidebar: [{ id: "section-1", label: "Section 1", pageId: "section-1", anchorRowId: "row-1", children: [] }],
      charts: [],
    },
  };
}

describe("PublicPageClient", () => {
  beforeEach(() => {
    fetchPublicManifestMock.mockReset();
    streamPublicAssistantMock.mockReset();
  });

  it("routes free-layout manifests to the free canvas renderer", async () => {
    fetchPublicManifestMock.mockResolvedValue(manifestBase("free_layout"));

    render(<PublicPageClient token="tok" />);

    expect(await screen.findByTestId("published-free-canvas")).toBeInTheDocument();
    expect(screen.queryByText("Section 1")).not.toBeInTheDocument();
  });

  it("routes fixed-size manifests to the fixed canvas renderer", async () => {
    const payload = manifestBase("fixed_size");
    payload.manifest.canvas = {
      format_id: "a4-portrait",
      kind: "fixed_size",
      page: { preset_id: "a4-portrait", width: 794, height: 1123 },
    };
    fetchPublicManifestMock.mockResolvedValue(payload);

    render(<PublicPageClient token="tok" />);

    expect(await screen.findByTestId("published-fixed-canvas")).toBeInTheDocument();
  });

  it("keeps web-page manifests on the sidebar and grid renderer", async () => {
    fetchPublicManifestMock.mockResolvedValue(manifestBase("web_page"));

    render(<PublicPageClient token="tok" />);

    await waitFor(() => {
      expect(screen.getByText("Section 1")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("published-free-canvas")).not.toBeInTheDocument();
  });

  it("opens the public assistant drawer and renders streamed events", async () => {
    const user = userEvent.setup();
    const payload = manifestBase("web_page");
    payload.manifest.assistant = { available: true, chart_count: 1, row_count: 2 };
    fetchPublicManifestMock.mockResolvedValue(payload);
    streamPublicAssistantMock.mockImplementation(async function* (_token, request) {
      expect(request.message).toBe("Summarize the page");
      yield { event: "planning", data: { text: "Inspecting snapshot." } };
      yield {
        event: "tool_use",
        data: { step_id: "step-1", tool_name: "list_snapshot_tables", started_at: 1 },
      };
      yield {
        event: "tool_result",
        data: { step_id: "step-1", status: "success", result: { row_count: 2 }, started_at: 1, completed_at: 2 },
      };
      yield { event: "final", data: { text: "Published answer" } };
    });

    render(<PublicPageClient token="tok" />);

    await user.click(await screen.findByRole("button", { name: "Open AI Assistant" }));
    expect(screen.getByTestId("public-assistant-drawer")).toBeInTheDocument();

    await user.type(screen.getByTestId("public-assistant-input"), "Summarize the page");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Published answer")).toBeInTheDocument();
    expect(screen.queryByText("list_snapshot_tables")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Thought complete/ }));
    expect(screen.getByText("list_snapshot_tables")).toBeInTheDocument();
  });

  it("renders the neutral unavailable state for invalid canvas metadata", async () => {
    const payload = manifestBase("fixed_size");
    payload.manifest.canvas = { format_id: "a4-portrait", kind: "fixed_size" };
    fetchPublicManifestMock.mockResolvedValue(payload);

    render(<PublicPageClient token="tok" />);

    expect(await screen.findByText("Link unavailable")).toBeInTheDocument();
  });

  it("renders the neutral unavailable state when the token is unknown or revoked (404)", async () => {
    // A revoked/unknown public token makes the API reject; the page must show
    // the neutral invalid state without revealing whether the link ever existed.
    fetchPublicManifestMock.mockRejectedValue(new Error("Not found"));

    render(<PublicPageClient token="revoked-token" />);

    expect(await screen.findByText("Link unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("published-free-canvas")).not.toBeInTheDocument();
    expect(screen.queryByTestId("published-fixed-canvas")).not.toBeInTheDocument();
  });

  it("prompts for login when a restricted published page requires authentication", async () => {
    fetchPublicManifestMock.mockRejectedValue(
      new PublicPageError("authentication_required", 401, "authentication_required")
    );

    render(<PublicPageClient token="restricted-token" />);

    expect(await screen.findByText("Login required")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Login to view" })).toHaveAttribute(
      "href",
      "/login?next=%2Fp%2Frestricted-token"
    );
  });

  it("shows a no-access state when the logged-in user is not allowed", async () => {
    fetchPublicManifestMock.mockRejectedValue(
      new PublicPageError("forbidden", 403, "forbidden")
    );

    render(<PublicPageClient token="restricted-token" />);

    expect(await screen.findByText("No access")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to workspace" })).toHaveAttribute("href", "/");
    expect(screen.queryByText("Link unavailable")).not.toBeInTheDocument();
  });
});
