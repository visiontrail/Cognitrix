import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PublicPageClient } from "../../components/public/public-page-client";
import { fetchPublicManifest } from "../../lib/public/api";

vi.mock("@/lib/public/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/public/api")>("../../lib/public/api");
  return {
    ...actual,
    fetchPublicManifest: vi.fn(),
    fetchPublicChartData: vi.fn(),
  };
});

vi.mock("@/components/public/published-canvas-renderers", () => ({
  PublishedFreeCanvas: () => <div data-testid="published-free-canvas" />,
  PublishedFixedCanvas: () => <div data-testid="published-fixed-canvas" />,
}));

const fetchPublicManifestMock = vi.mocked(fetchPublicManifest);

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

  it("renders the neutral unavailable state for invalid canvas metadata", async () => {
    const payload = manifestBase("fixed_size");
    payload.manifest.canvas = { format_id: "a4-portrait", kind: "fixed_size" };
    fetchPublicManifestMock.mockResolvedValue(payload);

    render(<PublicPageClient token="tok" />);

    expect(await screen.findByText("Link unavailable")).toBeInTheDocument();
  });
});
