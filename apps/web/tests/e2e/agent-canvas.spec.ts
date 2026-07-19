import { expect, test } from "@playwright/test";

/**
 * Happy-path agent-canvas run on the web-design canvas, with the backend fully
 * mocked at the network layer: outline → approve → canvas ops stream in →
 * blocks appear on the page → run completes → run-level undo removes the page.
 */

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
  "Access-Control-Allow-Headers": "*",
};

const jsonHeaders = {
  ...corsHeaders,
  "Content-Type": "application/json",
};

const RUN_ID = "acr-e2e";
const PAGE_ID = `agent-${RUN_ID}`;
const CONFIRMATION_ID = "dash-e2e";

function sse(events: Array<{ event: string; data: Record<string, unknown> }>): string {
  return events
    .map((item, index) => `id: ${index + 1}\nevent: ${item.event}\ndata: ${JSON.stringify(item.data)}\n\n`)
    .join("");
}

function chartSpec(title: string, rows: Array<Record<string, unknown>>) {
  return {
    engine: "recharts",
    chart_type: "bar",
    title,
    data: rows,
    config: { xKey: "segment", yKey: "metric_value" },
  };
}

const outlineEvents = sse([
  { event: "planning", data: { text: "Planning the dashboard outline..." } },
  {
    event: "confirmation_required",
    data: {
      confirmation_type: "dashboard_outline",
      confirmation_id: CONFIRMATION_ID,
      run_id: RUN_ID,
      canvas_format: "web-design",
      page_title: "销售概览",
      proposed_chart_count: 2,
      max_chart_count: 12,
      sections: [
        {
          key: "s1",
          title: "概览",
          items: [
            { key: "c1", kind: "chart", title: "总人数", description: "员工总数", chart_type: "single_value", size_preset: "kpi" },
            { key: "c2", kind: "chart", title: "部门人数", description: "按部门统计", chart_type: "bar", size_preset: "half" },
          ],
        },
      ],
    },
  },
  {
    event: "final",
    data: {
      status: "awaiting_confirmation",
      confirmation_type: "dashboard_outline",
      confirmation_id: CONFIRMATION_ID,
      run_id: RUN_ID,
      text: "Please review the outline before I build 2 charts.",
    },
  },
]);

const runEvents = sse([
  {
    event: "canvas_op",
    data: {
      run_id: RUN_ID,
      seq: 1,
      op_type: "create_page",
      page_id: PAGE_ID,
      payload: { block_id: `agent-block-${RUN_ID}-1`, page_id: PAGE_ID, title: "销售概览" },
    },
  },
  {
    event: "canvas_op",
    data: {
      run_id: RUN_ID,
      seq: 2,
      op_type: "add_section",
      page_id: PAGE_ID,
      payload: { block_id: `agent-block-${RUN_ID}-2`, section_id: `agent-block-${RUN_ID}-2`, page_id: PAGE_ID, title: "概览" },
    },
  },
  {
    event: "canvas_op",
    data: {
      run_id: RUN_ID,
      seq: 3,
      op_type: "place_chart",
      page_id: PAGE_ID,
      payload: {
        block_id: `agent-block-${RUN_ID}-3`,
        section_id: `agent-block-${RUN_ID}-2`,
        page_id: PAGE_ID,
        title: "总人数",
        chart_type: "bar",
        size_preset: "kpi",
        asset_id: "asset-e2e-1",
        spec: chartSpec("总人数", [{ segment: "total", metric_value: 42 }]),
      },
    },
  },
  {
    event: "canvas_op",
    data: {
      run_id: RUN_ID,
      seq: 4,
      op_type: "place_chart",
      page_id: PAGE_ID,
      payload: {
        block_id: `agent-block-${RUN_ID}-4`,
        section_id: `agent-block-${RUN_ID}-2`,
        page_id: PAGE_ID,
        title: "部门人数",
        chart_type: "bar",
        size_preset: "half",
        asset_id: "asset-e2e-2",
        spec: chartSpec("部门人数", [
          { segment: "HR", metric_value: 24 },
          { segment: "PM", metric_value: 18 },
        ]),
      },
    },
  },
  {
    event: "final",
    data: {
      status: "completed",
      run_id: RUN_ID,
      page_id: PAGE_ID,
      text: "Dashboard completed: 2 charts placed.",
      placed_count: 2,
      failed_count: 0,
      skipped_count: 0,
      tool_steps: 4,
    },
  },
]);

test("agent mode builds a dashboard on the web-design canvas and undo removes it", async ({ page }) => {
  await page.route("http://127.0.0.1:8000/**", async (route) => {
    const request = route.request();
    const method = request.method();
    const url = new URL(request.url());
    const path = url.pathname;

    if (method === "OPTIONS") {
      await route.fulfill({ status: 204, headers: corsHeaders, body: "" });
      return;
    }

    if (path === "/auth/login" && method === "POST") {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify({ access_token: "e2e-token", token_type: "bearer", expires_at: 4102444800 }),
      });
      return;
    }

    if (path === "/auth/me") {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify({
          id: "demo-user",
          email: "demo@example.com",
          display_name: "Demo",
          job_id: null,
          last_login_at: null,
          available_workspaces: [{ workspace_id: "ws-e2e", name: "E2E WS", role: "owner" }],
        }),
      });
      return;
    }

    if (path === "/workspaces" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify({
          workspaces: [
            {
              workspace_id: "ws-e2e",
              name: "E2E WS",
              role: "owner",
              created_at: "2026-01-01T00:00:00Z",
              updated_at: "2026-01-01T00:00:00Z",
            },
          ],
        }),
      });
      return;
    }

    if (path === "/chat/capabilities") {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify({ agent_canvas_mode_enabled: true, web_search_enabled: false }),
      });
      return;
    }

    if (path === "/chat/agent-runs/active") {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify({ run: null }) });
      return;
    }

    if (path === "/chat/stream" && method === "POST") {
      const body = request.postDataJSON() as Record<string, unknown>;
      const payload = body.agent_run_confirmation ? runEvents : outlineEvents;
      await route.fulfill({
        status: 200,
        headers: { ...corsHeaders, "Content-Type": "text/event-stream" },
        body: payload,
      });
      return;
    }

    if (path.endsWith("/canvas-snapshot") && method === "GET") {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify({ snapshot: null }) });
      return;
    }

    if (path.endsWith("/chat/sessions") && method === "GET") {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify({ sessions: [] }) });
      return;
    }

    if (path.endsWith("/messages") && method === "GET") {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify({ messages: [] }) });
      return;
    }

    if (path.endsWith("/chart-assets") && method === "GET") {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify({ assets: [] }) });
      return;
    }

    if (path.startsWith("/workspaces/") && (method === "PUT" || method === "POST" || method === "DELETE")) {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify({}) });
      return;
    }

    await route.fulfill({ status: 404, headers: jsonHeaders, body: JSON.stringify({ code: "NOT_FOUND" }) });
  });

  await page.goto("/");

  // Start a conversation so the composer is available.
  const newConversation = page.getByRole("button", { name: "New conversation" });
  if (await newConversation.isVisible().catch(() => false)) {
    await newConversation.click();
  }

  // Enable Agent mode from the "+" menu.
  await page.getByLabel("Open chat actions").click();
  await page.getByRole("menuitemcheckbox", { name: "Agent build dashboard" }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByText("Agent dashboard mode")).toBeVisible();

  // The default canvas is not web-design: take the one-click switch.
  const formatPrompt = page.getByTestId("agent-canvas-format-prompt");
  if (await formatPrompt.isVisible().catch(() => false)) {
    await page.getByRole("button", { name: "Switch to web design" }).click();
    await expect(formatPrompt).not.toBeVisible();
  }

  await page.getByLabel("Chat Input").fill("生成销售概览仪表盘");
  await page.keyboard.press("Enter");

  // Outline approval card appears and pauses the run.
  const outlineCard = page.getByTestId("agent-run-outline-card");
  await expect(outlineCard).toBeVisible();
  await expect(outlineCard.getByText("销售概览")).toBeVisible();
  await expect(outlineCard.getByText("部门人数")).toBeVisible();

  // Approve: the run streams canvas ops onto a fresh web-design page.
  await outlineCard.getByRole("button", { name: "Generate 2 charts" }).click();

  await expect(page.getByTestId("agent-run-summary-card")).toBeVisible();
  await expect(page.getByText("Dashboard completed: 2 charts placed.")).toBeVisible();

  // The run page exists in the web-design sidebar with the section + charts.
  await expect(page.getByDisplayValue("销售概览")).toBeVisible();
  await expect(page.getByLabel("Chart zone 部门人数")).toBeVisible();

  // Run-level undo removes only the run's page.
  await page.getByRole("button", { name: "Undo this run" }).click();
  await expect(page.getByLabel("Chart zone 部门人数")).not.toBeVisible();
  await expect(page.getByDisplayValue("销售概览")).not.toBeVisible();
  await expect(page.getByTestId("agent-run-summary-card")).toBeVisible();
});
