import { API_BASE_URL } from "@/lib/api-base";
import { getAuthorizationHeader } from "@/lib/auth/session";
import { parseSSEStream } from "@/lib/chat/sse";
import { isRecord } from "@/lib/utils";

/**
 * Client surface for agent-canvas runs: wire types for `canvas_op` SSE events,
 * the run-control REST endpoints (active / ops / stop / retry / tail), and the
 * localStorage-backed "skip approval" preference.
 */

export type AgentCanvasOpType =
  | "create_page"
  | "add_section"
  | "add_text_block"
  | "place_chart"
  | "error_placeholder";

export type AgentCanvasWireOp = {
  runId: string;
  seq: number;
  opType: AgentCanvasOpType;
  pageId: string;
  payload: Record<string, unknown>;
};

export type AgentCanvasRunInfo = {
  runId: string;
  workspaceId: string;
  pageId: string;
  status: string;
  lastSeq: number;
};

const AUTO_APPROVE_STORAGE_KEY = "cognitrix.agentCanvas.autoApprove";

const configuredClearance = Number(process.env.NEXT_PUBLIC_DEFAULT_CLEARANCE ?? 1);
const DEFAULT_AUTH_CONTEXT = {
  userId: process.env.NEXT_PUBLIC_DEFAULT_USER_ID ?? "demo-user",
  projectId: process.env.NEXT_PUBLIC_DEFAULT_PROJECT_ID ?? "demo-project",
  role: process.env.NEXT_PUBLIC_DEFAULT_ROLE ?? "hr",
  department: process.env.NEXT_PUBLIC_DEFAULT_DEPARTMENT ?? "HR",
  clearance: Number.isFinite(configuredClearance) ? Math.max(0, Math.trunc(configuredClearance)) : 1,
};

export function getAutoApprovePreference(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(AUTO_APPROVE_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function setAutoApprovePreference(value: boolean): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(AUTO_APPROVE_STORAGE_KEY, value ? "true" : "false");
  } catch {
    // Preference persistence is best-effort.
  }
}

export function parseAgentCanvasWireOp(payload: unknown): AgentCanvasWireOp | null {
  if (!isRecord(payload)) return null;
  const runId = String(payload.run_id ?? "");
  const opType = String(payload.op_type ?? "");
  const pageId = String(payload.page_id ?? "");
  const seq = Number(payload.seq);
  if (!runId || !pageId || !Number.isFinite(seq)) return null;
  if (
    opType !== "create_page" &&
    opType !== "add_section" &&
    opType !== "add_text_block" &&
    opType !== "place_chart" &&
    opType !== "error_placeholder"
  ) {
    return null;
  }
  return {
    runId,
    seq,
    opType,
    pageId,
    payload: isRecord(payload.payload) ? payload.payload : {},
  };
}

async function authHeaders(): Promise<Record<string, string>> {
  return getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
}

export async function fetchActiveAgentRun(workspaceId: string): Promise<AgentCanvasRunInfo | null> {
  const headers = await authHeaders();
  const response = await fetch(
    `${API_BASE_URL}/chat/agent-runs/active?workspace_id=${encodeURIComponent(workspaceId)}`,
    { headers }
  );
  if (!response.ok) return null;
  const body = (await response.json()) as { run?: Record<string, unknown> | null };
  const run = body.run;
  if (!isRecord(run)) return null;
  return {
    runId: String(run.run_id ?? ""),
    workspaceId: String(run.workspace_id ?? ""),
    pageId: String(run.page_id ?? ""),
    status: String(run.status ?? ""),
    lastSeq: Number(run.last_seq ?? 0) || 0,
  };
}

export async function fetchAgentRunOps(
  runId: string,
  afterSeq = 0
): Promise<{ status: string; ops: AgentCanvasWireOp[] }> {
  const headers = await authHeaders();
  const response = await fetch(
    `${API_BASE_URL}/chat/agent-runs/${encodeURIComponent(runId)}/ops?after_seq=${afterSeq}`,
    { headers }
  );
  if (!response.ok) {
    return { status: "unknown", ops: [] };
  }
  const body = (await response.json()) as {
    status?: string;
    page_id?: string;
    ops?: Array<Record<string, unknown>>;
  };
  const pageId = String(body.page_id ?? "");
  const ops = (body.ops ?? [])
    .map((op) =>
      parseAgentCanvasWireOp({
        run_id: runId,
        // Per-op page first: a multi-page run replays onto the pages it was
        // built on. The run-level page id is the fallback for ops written
        // before multi-page runs existed.
        page_id: String(op.page_id ?? (op.payload as Record<string, unknown>)?.page_id ?? pageId),
        seq: op.seq,
        op_type: op.op_type,
        payload: op.payload,
      })
    )
    .filter((op): op is AgentCanvasWireOp => op !== null);
  return { status: String(body.status ?? "unknown"), ops };
}

export async function stopAgentRun(runId: string): Promise<string | null> {
  const headers = await authHeaders();
  const response = await fetch(
    `${API_BASE_URL}/chat/agent-runs/${encodeURIComponent(runId)}/stop`,
    { method: "POST", headers }
  );
  if (!response.ok) return null;
  const body = (await response.json()) as { status?: string };
  return String(body.status ?? "");
}

export async function retryAgentRunItem(
  runId: string,
  seq: number
): Promise<AgentCanvasWireOp | null> {
  const headers = await authHeaders();
  const response = await fetch(
    `${API_BASE_URL}/chat/agent-runs/${encodeURIComponent(runId)}/retry`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify({ seq }),
    }
  );
  if (!response.ok) return null;
  const body = (await response.json()) as { op?: unknown; status?: string };
  return parseAgentCanvasWireOp(body.op);
}

/**
 * Re-attach to a still-running run: streams `canvas_op` payloads after
 * `afterSeq` and resolves with the terminal `final` payload (or null when the
 * stream ended without one).
 */
export async function tailAgentRun(
  runId: string,
  afterSeq: number,
  onOp: (op: AgentCanvasWireOp) => void,
  signal?: AbortSignal
): Promise<Record<string, unknown> | null> {
  const headers = await authHeaders();
  const response = await fetch(
    `${API_BASE_URL}/chat/agent-runs/${encodeURIComponent(runId)}/tail?after_seq=${afterSeq}`,
    { headers, signal }
  );
  if (!response.ok || !response.body) return null;
  let finalPayload: Record<string, unknown> | null = null;
  for await (const event of parseSSEStream(response.body)) {
    if (event.event === "canvas_op") {
      const op = parseAgentCanvasWireOp(event.data);
      if (op) onOp(op);
    } else if (event.event === "final" && isRecord(event.data)) {
      finalPayload = event.data;
    }
  }
  return finalPayload;
}
