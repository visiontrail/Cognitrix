import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "../../components/ui/tooltip";
import { ChartMessageCard, MultiChartMessageGroup } from "../../components/chat/chart-message-card";
import { useAssetStore } from "../../stores/asset-store";
import { useChatStore } from "../../stores/chat-store";
import { useWorkspaceStore } from "../../stores/workspace-store";
import type { ChartAsset } from "../../types/chart";

const toBlobMock = vi.fn();
const clipboardWriteMock = vi.fn();
const fetchMock = vi.fn();

vi.mock("html-to-image", () => ({
  toBlob: (...args: unknown[]) => toBlobMock(...args),
}));

vi.mock("@/components/charts/chart-preview", () => ({
  ChartPreview: ({ spec }: { spec: { title: string } }) => (
    <div data-testid="chart-preview">{spec.title}</div>
  ),
}));

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

vi.mock("@/lib/auth/session", () => ({
  getAppMode: () => "designer",
  getActiveAuthContext: () => ({
    userId: "demo-user",
    projectId: "demo-project",
    role: "hr",
    department: "HR",
    clearance: 1,
  }),
  getAuthorizationHeader: () => Promise.resolve({ Authorization: "Bearer test-token" }),
}));

const chartAsset: ChartAsset = {
  id: "asset-1",
  title: "Headcount",
  chartType: "bar",
  spec: {
    chartType: "bar",
    title: "Headcount",
    echartsOption: {
      xAxis: { type: "category", data: ["HR"] },
      yAxis: { type: "value" },
      series: [{ type: "bar", data: [12] }],
    },
  },
  sourceMeta: {
    sessionId: "session-1",
    messageId: "message-1",
    prompt: "show headcount by department",
  },
  createdAt: "2026-05-14T00:00:00.000Z",
  updatedAt: "2026-05-14T00:00:00.000Z",
};

const secondChartAsset: ChartAsset = {
  ...chartAsset,
  id: "asset-2",
  title: "PM Headcount",
  sourceMeta: {
    ...chartAsset.sourceMeta,
    messageId: "message-2",
  },
};

function renderCard() {
  return render(
    <TooltipProvider>
      <textarea data-chat-composer="true" aria-label="Composer" />
      <ChartMessageCard assetId={chartAsset.id} title={chartAsset.title} chartType={chartAsset.chartType} />
    </TooltipProvider>
  );
}

describe("ChartMessageCard", () => {
  beforeEach(() => {
    toBlobMock.mockResolvedValue(new Blob(["png"], { type: "image/png" }));
    clipboardWriteMock.mockResolvedValue(undefined);
    class ClipboardItemMock {
      constructor(public readonly items: Record<string, Blob>) {}
    }
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        write: clipboardWriteMock,
      },
    });
    Object.defineProperty(window, "ClipboardItem", {
      configurable: true,
      value: ClipboardItemMock,
    });
    Object.defineProperty(globalThis, "ClipboardItem", {
      configurable: true,
      value: ClipboardItemMock,
    });
    fetchMock.mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    useAssetStore.setState({ assets: [chartAsset] });
    useChatStore.setState({
      composerText: "",
      sessions: [
        {
          id: "session-1",
          title: "Session",
          createdAt: "2026-05-14T00:00:00.000Z",
          updatedAt: "2026-05-14T00:00:00.000Z",
          messageCount: 2,
          lastMessage: "old answer",
        },
      ],
      messagesBySession: {
        "session-1": [
          {
            id: "message-1",
            sessionId: "session-1",
            role: "assistant",
            content: "old answer",
            timestamp: "2026-05-14T00:00:00.000Z",
          },
        ],
      },
      traceByMessageId: {
        "message-1": {
          state: "collapsed",
          startedAt: 0,
          steps: [],
        },
      },
    });
    useWorkspaceStore.setState({
      activeWorkspaceId: "workspace-1",
      nodes: [],
      edges: [],
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    useAssetStore.setState({ assets: [] });
    useChatStore.setState({
      sessions: [],
      messagesBySession: {},
      pendingIngestionBySession: {},
      pendingIngestionSetupBySession: {},
      pendingMultiChartBySession: {},
      composerText: "",
      traceByMessageId: {},
    });
    useWorkspaceStore.setState({ activeWorkspaceId: null, nodes: [], edges: [] });
  });

  it("copies the rendered chart to the clipboard as a PNG", async () => {
    renderCard();

    await userEvent.click(screen.getByRole("button", { name: "Copy as PNG image" }));

    await waitFor(() => {
      expect(toBlobMock).toHaveBeenCalledWith(
        expect.any(HTMLElement),
        expect.objectContaining({
          backgroundColor: "#f5f0e8",
          pixelRatio: 2,
        })
      );
      expect(clipboardWriteMock).toHaveBeenCalledTimes(1);
    });
  });

  it("restores the chart source prompt to the composer without sending it", async () => {
    renderCard();

    await userEvent.click(screen.getByRole("button", { name: "Regenerate" }));

    await waitFor(() => {
      expect(useChatStore.getState().composerText).toBe("show headcount by department");
    });
    expect(useChatStore.getState().messagesBySession["session-1"]).toEqual([]);
    expect(useChatStore.getState().traceByMessageId["message-1"]).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/chat/session/reset"),
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"conversation_id":"session-1"'),
      })
    );
    await waitFor(() => {
      expect(screen.getByLabelText("Composer")).toHaveFocus();
    });
  });

  it("does not render the old full-screen action", () => {
    renderCard();

    expect(screen.queryByRole("button", { name: /full screen/i })).not.toBeInTheDocument();
  });

  it("adds all generated chart assets to the workspace", async () => {
    useAssetStore.setState({ assets: [chartAsset, secondChartAsset] });

    render(
      <TooltipProvider>
        <MultiChartMessageGroup
          assets={[
            { assetId: chartAsset.id, title: chartAsset.title, chartType: chartAsset.chartType },
            { assetId: secondChartAsset.id, title: secondChartAsset.title, chartType: secondChartAsset.chartType },
          ]}
        />
      </TooltipProvider>
    );

    await userEvent.click(screen.getByRole("button", { name: /Add all/i }));

    const nodes = useWorkspaceStore.getState().nodes;
    expect(nodes).toHaveLength(2);
    expect(nodes.map((node) => node.data.assetId)).toEqual(["asset-1", "asset-2"]);
    // Charts are packed side-by-side with a gap so they never overlap.
    expect(nodes.map((node) => node.position)).toEqual([
      { x: 50, y: 50 },
      { x: 598, y: 50 },
    ]);
  });
});
