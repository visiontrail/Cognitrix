import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  chatSessionsQueryKey,
  useChatSessions,
  useConfirmIngestionSetup,
  useSendMessage,
} from "../../hooks/use-chat";
import { setInMemoryToken } from "../../lib/auth/session";
import { useAssetStore } from "../../stores/asset-store";
import { useChatStore } from "../../stores/chat-store";
import { useUIStore } from "../../stores/ui-store";
import { useWorkspaceStore } from "../../stores/workspace-store";
import type { ChatSession } from "../../types/chat";
import type { IngestionPlanAwaitingSetup, IngestionUploadResult } from "../../types/ingestion";

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function wrapperFor(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

function session(id: string): ChatSession {
  return {
    id,
    title: "Scoped session",
    createdAt: "2026-05-11T00:00:00.000Z",
    updatedAt: "2026-05-11T00:00:00.000Z",
    messageCount: 1,
  };
}

function sseResponse(frames: string): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(frames));
        controller.close();
      },
    }),
    { status: 200 }
  );
}

const pendingUpload: IngestionUploadResult = {
  uploadId: "upload-1",
  jobId: "job-1",
  workspaceId: "ws-a",
  status: "uploaded",
  fileSummary: {
    fileName: "employees.csv",
    sizeBytes: 10,
    fileHash: "hash",
    storagePath: "uploads/employees.csv",
  },
  sheetSummary: {},
  columnSummary: {},
  samplePreview: [],
};

const pendingSetup: IngestionPlanAwaitingSetup = {
  status: "awaiting_catalog_setup",
  workspaceId: "ws-a",
  jobId: "job-1",
  agentGuess: { businessType: "roster", confidence: 0.8 },
  setupQuestions: [],
  suggestedCatalogSeed: {
    businessType: "roster",
    tableName: "employees",
    humanLabel: "Employees",
    writeMode: "update_existing",
    timeGrain: "none",
    primaryKeys: ["employee_id"],
    matchColumns: ["employee_id"],
    isActiveTarget: true,
    description: "Employee roster",
  },
  humanApproval: {
    required: true,
    mechanism: "frontend_approval_card",
    stage: "catalog_setup",
    question: "",
    options: [],
    recommendedOption: null,
  },
  route: { route: "setup", reason: "missing catalog" },
  toolTrace: [],
};

describe("use-chat workspace isolation", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    window.localStorage.clear();
    setInMemoryToken("test-token", Math.floor(Date.now() / 1000) + 3600);
    useChatStore.getState().clearForUser();
    useWorkspaceStore.setState({
      workspaces: [
        {
          id: "ws-a",
          title: "Workspace A",
          createdAt: "2026-05-11T00:00:00.000Z",
          updatedAt: "2026-05-11T00:00:00.000Z",
          nodeCount: 0,
        },
        {
          id: "ws-b",
          title: "Workspace B",
          createdAt: "2026-05-11T00:00:00.000Z",
          updatedAt: "2026-05-11T00:00:00.000Z",
          nodeCount: 0,
        },
      ],
      activeWorkspaceId: "ws-a",
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      hasUnsavedChanges: false,
    });
    useUIStore.setState({ sendingBySession: {}, isSending: false });
    useChatStore.getState().initForWorkspace("user-1", "ws-a");
    useChatStore.getState().addSession(session("session-a"));
    useChatStore.getState().setActiveSession("session-a");
    useAssetStore.setState({ assets: [] });
  });

  it("keys chat session and message caches by active workspace", async () => {
    const queryClient = makeQueryClient();

    const { result } = renderHook(() => useChatSessions(), { wrapper: wrapperFor(queryClient) });

    await waitFor(() => expect(result.current.data?.map((item) => item.id)).toEqual(["session-a"]));
    expect(queryClient.getQueryData(chatSessionsQueryKey("ws-a"))).toHaveLength(1);

    act(() => {
      useWorkspaceStore.setState({ activeWorkspaceId: "ws-b" });
      useChatStore.getState().initForWorkspace("user-1", "ws-b");
    });

    await waitFor(() => expect(result.current.data).toEqual([]));
    expect(queryClient.getQueryData(chatSessionsQueryKey("ws-b"))).toEqual([]);
    expect(queryClient.getQueryData(chatSessionsQueryKey("ws-a"))).toHaveLength(1);
  });

  it("sends chat requests with active workspace and rejects sessions outside that scope", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse('event: final\ndata: {"text":"done"}\n\n')
    );
    vi.stubGlobal("fetch", fetchMock);
    const queryClient = makeQueryClient();
    const { result } = renderHook(() => useSendMessage(), { wrapper: wrapperFor(queryClient) });

    await act(async () => {
      await result.current.mutateAsync({ sessionId: "session-a", content: "show headcount" });
    });

    const chatCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/chat/stream"));
    expect(chatCall).toBeTruthy();
    const body = JSON.parse(String(chatCall?.[1]?.body));
    expect(body).toEqual(expect.objectContaining({ workspace_id: "ws-a", conversation_id: "session-a" }));

    act(() => {
      useWorkspaceStore.setState({ activeWorkspaceId: "ws-b" });
      useChatStore.getState().initForWorkspace("user-1", "ws-b");
    });

    await expect(result.current.mutateAsync({ sessionId: "session-a", content: "leak" })).rejects.toThrow();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("collects grouped spec events as multi-asset assistant messages", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse([
        'event: spec\ndata: {"multi_chart_group_id":"mcg-1","chart_id":"chart-hr","chart_index":0,"chart_count":2,"chart_key":"hr","chart_label":"HR","spec":{"engine":"recharts","chart_type":"bar","title":"HR","data":[{"segment":"HR","metric_value":2}],"config":{"xKey":"segment","yKey":"metric_value"}}}\n\n',
        'event: spec\ndata: {"multi_chart_group_id":"mcg-1","chart_id":"chart-pm","chart_index":1,"chart_count":2,"chart_key":"pm","chart_label":"PM","spec":{"engine":"recharts","chart_type":"bar","title":"PM","data":[{"segment":"PM","metric_value":1}],"config":{"xKey":"segment","yKey":"metric_value"}}}\n\n',
        'event: final\ndata: {"status":"completed","text":"Generated 2 charts."}\n\n',
      ].join(""))
    );
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useSendMessage(), { wrapper: wrapperFor(makeQueryClient()) });

    await act(async () => {
      await result.current.mutateAsync({ sessionId: "session-a", content: "charts for each department" });
    });

    const assistant = useChatStore.getState().messagesBySession["session-a"].at(-1);
    expect(assistant?.chartAsset?.assetId).toBe("asset-chart-hr");
    expect(assistant?.chartAssets?.map((asset) => asset.assetId)).toEqual(["asset-chart-hr", "asset-chart-pm"]);
    expect(new Set(useAssetStore.getState().assets.map((asset) => asset.id))).toEqual(
      new Set(["asset-chart-hr", "asset-chart-pm"])
    );
  });

  it("sends typed multi-chart confirmation payloads", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse('event: final\ndata: {"status":"canceled","text":"Canceled."}\n\n')
    );
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useSendMessage(), { wrapper: wrapperFor(makeQueryClient()) });

    await act(async () => {
      await result.current.mutateAsync({
        sessionId: "session-a",
        content: "Cancel multi-chart generation",
        multiChartConfirmation: {
          confirmationId: "mchart-1",
          action: "cancel",
        },
      });
    });

    const chatCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/chat/stream"));
    const body = JSON.parse(String(chatCall?.[1]?.body));
    expect(body.multi_chart_confirmation).toEqual({
      confirmation_id: "mchart-1",
      action: "cancel",
      selected_items: null,
    });
  });

  it("sends an explicit generation strategy when multi-chart mode is selected", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse('event: final\ndata: {"status":"completed","text":"Done."}\n\n')
    );
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useSendMessage(), { wrapper: wrapperFor(makeQueryClient()) });

    await act(async () => {
      await result.current.mutateAsync({
        sessionId: "session-a",
        content: "show headcount by department",
        generationStrategy: "multi_chart",
      });
    });

    const chatCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/chat/stream"));
    const body = JSON.parse(String(chatCall?.[1]?.body));
    expect(body.generation_strategy).toBe("multi_chart");
  });

  it("sends ingestion setup confirmation with active workspace and rejects cross-workspace sessions", async () => {
    useChatStore.getState().setPendingIngestionSetup("session-a", { upload: pendingUpload, plan: pendingSetup });
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse(
        'event: decision\ndata: {"status":"awaiting_user_approval","workspace_id":"ws-a","job_id":"job-1","proposal_id":"proposal-1","proposal_json":{"business_type":"roster","confidence":0.9,"recommended_action":"update_existing","candidate_actions":["update_existing"],"target_table":"employees","time_grain":"none","match_columns":["employee_id"],"column_mapping":{},"diff_preview":{"predicted_insert_count":0,"predicted_update_count":1,"predicted_conflict_count":0},"risks":[],"explanation":"ok","sql_draft":"","requires_catalog_setup":false,"created_at":"2026-05-11T00:00:00.000Z"},"human_approval":{"options":["update_existing"],"recommended_option":"update_existing"},"route":{"route":"approval","reason":"ready"},"tool_trace":[]}\n\n'
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useConfirmIngestionSetup(), { wrapper: wrapperFor(makeQueryClient()) });

    await act(async () => {
      await result.current.mutateAsync({
        sessionId: "session-a",
        seed: pendingSetup.suggestedCatalogSeed,
      });
    });

    const setupCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/ingestion/setup/confirm/stream"));
    const setupBody = JSON.parse(String(setupCall?.[1]?.body));
    expect(setupBody).toEqual(expect.objectContaining({ workspace_id: "ws-a", conversation_id: "session-a" }));

    act(() => {
      useWorkspaceStore.setState({ activeWorkspaceId: "ws-b" });
      useChatStore.getState().initForWorkspace("user-1", "ws-b");
    });

    await expect(
      result.current.mutateAsync({ sessionId: "session-a", seed: pendingSetup.suggestedCatalogSeed })
    ).rejects.toThrow();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
