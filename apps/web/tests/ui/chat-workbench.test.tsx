import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatWorkbench } from "../../components/workbench/chat-workbench";
import { SESSION_STORAGE_KEY } from "../../lib/chat/session-storage";
import { createSSEEventStream } from "../test-helpers/sse";

const fetchMock = vi.fn<typeof fetch>();
const AUTH_EXPIRES_AT = 4102444800;

function createLoginResponse(accessToken = "token-123") {
  return new Response(
    JSON.stringify({
      access_token: accessToken,
      token_type: "bearer",
      expires_at: AUTH_EXPIRES_AT
    }),
    { status: 200, headers: { "Content-Type": "application/json" } }
  );
}

describe("Chat workbench streaming UI", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    window.localStorage.clear();
    fetchMock.mockReset();
  });

  it("consumes streaming events and renders chat + chart incrementally", async () => {
    fetchMock
      .mockResolvedValueOnce(createLoginResponse())
      .mockResolvedValueOnce(
        new Response(
          createSSEEventStream([
            {
              id: 1,
              event: "planning",
              data: { text: "I will inspect schema and then query safely.", agent_session_id: "agent-session-1" }
            },
            {
              id: 2,
              event: "tool_use",
              data: {
                tool_name: "describe_table",
                step: 1,
                agent_session_id: "agent-session-1",
                arguments: { table: "employees_wide" }
              }
            },
            {
              id: 3,
              event: "tool_result",
              data: {
                tool_name: "describe_table",
                status: "success",
                step: 1,
                agent_session_id: "agent-session-1",
                result: { row_count: 2 }
              }
            },
            {
              id: 4,
              event: "spec",
              data: {
                spec: {
                  engine: "recharts",
                  chart_type: "bar",
                  title: "Attrition Rate",
                  data: [{ department: "RD", metric_value: 0.12 }],
                  config: { xKey: "department", yKey: "metric_value" }
                }
              }
            },
            {
              id: 5,
              event: "final",
              data: { status: "completed", text: "Query completed for metric attrition_rate." }
            }
          ])
        )
      );

    render(<ChatWorkbench apiBaseUrl="http://localhost:8000" />);
    await userEvent.type(screen.getByLabelText("Chat Input"), "show attrition by department");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    await screen.findByText("I will inspect schema and then query safely.");
    await screen.findByText("Query completed for metric attrition_rate.");
    // Charts render through the ECharts surface, so the title lives in the chart
    // option rather than in the DOM — assert the chart itself was mounted.
    expect(await screen.findByTestId("echarts-chart")).toBeInTheDocument();
    expect(screen.getByTestId("tool-status")).toHaveTextContent("describe_table");
    expect(screen.getByTestId("tool-status")).toHaveTextContent("agent-session-1");
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/chat/stream",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer token-123"
        })
      })
    );
  }, 10000);

  it("saves current view and exposes share link", async () => {
    fetchMock
      .mockResolvedValueOnce(createLoginResponse())
      .mockResolvedValueOnce(
        new Response(
          createSSEEventStream([
            {
              id: 1,
              event: "spec",
              data: {
                spec: {
                  engine: "recharts",
                  chart_type: "bar",
                  title: "Headcount",
                  data: [{ department: "HR", metric_value: 10 }],
                  config: { xKey: "department", yKey: "metric_value" }
                }
              }
            },
            { id: 2, event: "final", data: { status: "completed", text: "done" } }
          ])
        )
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            view_id: "view-1",
            share_url: "/share/view-1",
            share_path: "/share/view-1",
            version: 1
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      );

    render(<ChatWorkbench apiBaseUrl="http://localhost:8000" />);
    await userEvent.type(screen.getByLabelText("Chat Input"), "show headcount");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    await screen.findByTestId("echarts-chart");
    await userEvent.click(screen.getByRole("button", { name: "Save & Share" }));

    await screen.findByText("Share Link:");
    expect(screen.getByRole("link", { name: "/share/view-1" })).toHaveAttribute("href", "/share/view-1");
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://localhost:8000/views",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer token-123"
        })
      })
    );
  });

  it("rehydrates the last session from local storage", async () => {
    window.localStorage.setItem(
      SESSION_STORAGE_KEY,
        JSON.stringify({
          conversationId: "conv-1",
          agentSessionId: "agent-session-restored",
          userId: "u-1",
          projectId: "p-1",
          role: "hr",
        department: "HR",
        clearance: 1,
        datasetTable: "employees_wide",
        composer: "restored question",
        messages: [{ id: "m-1", role: "assistant", text: "restored message" }],
        activeSpec: {
          engine: "recharts",
          chart_type: "single_value",
          title: "Restored KPI",
          data: [{ metric_value: 42 }],
          config: { yKey: "metric_value" }
        },
        lastToolEvent: { tool_name: "query_metrics", status: "success" },
        toolTrace: [{ tool_name: "describe_table", status: "success" }]
      })
    );

    fetchMock
      .mockResolvedValueOnce(createLoginResponse())
      .mockResolvedValueOnce(
        new Response(createSSEEventStream([{ id: 1, event: "final", data: { status: "completed", text: "done" } }]))
      );

    render(<ChatWorkbench apiBaseUrl="http://localhost:8000" />);

    await waitFor(() => {
      expect(screen.getByDisplayValue("restored question")).toBeInTheDocument();
      expect(screen.getByText("restored message")).toBeInTheDocument();
      expect(screen.getByTestId("echarts-chart")).toBeInTheDocument();
      expect(screen.getByTestId("tool-status")).toHaveTextContent("describe_table");
      expect(screen.getByTestId("tool-status")).toHaveTextContent("agent-session-restored");
    });

    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    await screen.findByText("done");
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/chat/stream",
      expect.objectContaining({
        body: expect.stringContaining('"conversation_id":"conv-1"')
      })
    );
  });

  it("does not expose the legacy direct Excel upload flow", async () => {
    render(<ChatWorkbench apiBaseUrl="http://localhost:8000" />);

    expect(screen.getByText("旧的自动解析并直接写表流程已关闭。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Upload Excel" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Excel Upload")).not.toBeInTheDocument();
  });
});
