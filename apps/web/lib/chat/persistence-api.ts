// Server-side persistence for chat sessions, messages, and chart assets.
//
// These three categories used to live only in browser localStorage, so they did
// not follow the user to another browser or device. This module talks to the
// `/workspaces/{id}/chat/...` and `/workspaces/{id}/chart-assets` endpoints so
// the data is durable and cross-device. localStorage remains the fast local
// cache; the server is the source of truth across devices.

import { getAuthorizationHeader } from "@/lib/auth/session";
import { API_BASE_URL } from "@/lib/api-base";
import type { ChatSession, ChatMessage } from "@/types/chat";
import type { ChartAsset } from "@/types/chart";

const DEFAULT_AUTH_CONTEXT = {
  userId: process.env.NEXT_PUBLIC_DEFAULT_USER_ID ?? "demo-user",
  projectId: process.env.NEXT_PUBLIC_DEFAULT_PROJECT_ID ?? "demo-project",
  role: process.env.NEXT_PUBLIC_DEFAULT_ROLE ?? "hr",
  department: process.env.NEXT_PUBLIC_DEFAULT_DEPARTMENT ?? "HR",
  clearance: Number(process.env.NEXT_PUBLIC_DEFAULT_CLEARANCE ?? 1) || 1,
};

async function authHeaders(extra?: Record<string, string>): Promise<Record<string, string>> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  return { ...headers, ...(extra ?? {}) };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

// -- chat sessions ----------------------------------------------------------

export async function fetchServerSessions(workspaceId: string): Promise<ChatSession[]> {
  const response = await fetch(
    `${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}/chat/sessions`,
    { method: "GET", headers: await authHeaders() }
  );
  if (!response.ok) {
    throw new Error(`fetch_sessions_failed_${response.status}`);
  }
  const payload = await readJson(response);
  const sessions = isRecord(payload) && Array.isArray(payload.sessions) ? payload.sessions : [];
  return sessions.filter((item): item is ChatSession => isRecord(item) && typeof item.id === "string");
}

export async function putServerSession(workspaceId: string, session: ChatSession): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}/chat/sessions/${encodeURIComponent(session.id)}`,
    {
      method: "PUT",
      headers: await authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        title: session.title,
        lastMessage: session.lastMessage ?? "",
        messageCount: session.messageCount,
        createdAt: session.createdAt,
        updatedAt: session.updatedAt,
      }),
    }
  );
  if (!response.ok && response.status !== 409) {
    throw new Error(`put_session_failed_${response.status}`);
  }
}

export async function deleteServerSession(workspaceId: string, sessionId: string): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}/chat/sessions/${encodeURIComponent(sessionId)}`,
    { method: "DELETE", headers: await authHeaders() }
  );
  if (!response.ok) {
    throw new Error(`delete_session_failed_${response.status}`);
  }
}

// -- chat messages ----------------------------------------------------------

export async function fetchServerMessages(
  workspaceId: string,
  sessionId: string
): Promise<ChatMessage[]> {
  const response = await fetch(
    `${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
    { method: "GET", headers: await authHeaders() }
  );
  if (!response.ok) {
    throw new Error(`fetch_messages_failed_${response.status}`);
  }
  const payload = await readJson(response);
  const messages = isRecord(payload) && Array.isArray(payload.messages) ? payload.messages : [];
  return messages.filter((item): item is ChatMessage => isRecord(item) && typeof item.id === "string");
}

export async function putServerMessages(
  workspaceId: string,
  sessionId: string,
  messages: ChatMessage[]
): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
    {
      method: "PUT",
      headers: await authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ messages }),
    }
  );
  if (!response.ok) {
    throw new Error(`put_messages_failed_${response.status}`);
  }
}

// -- chart assets -----------------------------------------------------------

export async function fetchServerAssets(workspaceId: string): Promise<ChartAsset[]> {
  const response = await fetch(
    `${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}/chart-assets`,
    { method: "GET", headers: await authHeaders() }
  );
  if (!response.ok) {
    throw new Error(`fetch_assets_failed_${response.status}`);
  }
  const payload = await readJson(response);
  const assets = isRecord(payload) && Array.isArray(payload.assets) ? payload.assets : [];
  return assets.filter((item): item is ChartAsset => isRecord(item) && typeof item.id === "string");
}

export async function putServerAsset(workspaceId: string, asset: ChartAsset): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}/chart-assets/${encodeURIComponent(asset.id)}`,
    {
      method: "PUT",
      headers: await authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ asset }),
    }
  );
  if (!response.ok && response.status !== 409) {
    throw new Error(`put_asset_failed_${response.status}`);
  }
}

// -- merge helpers ----------------------------------------------------------
//
// Hydration runs server + local together. Merges are union-based and idempotent
// so the frequent TanStack Query refetches/invalidations never clobber the live
// working copy on the active device, while a fresh device gets the full set from
// the server.

function timeValue(iso: string | undefined): number {
  if (!iso) return 0;
  const parsed = Date.parse(iso);
  return Number.isFinite(parsed) ? parsed : 0;
}

/** Union by id; on conflict keep the session with the newer updatedAt. Sorted newest-first. */
export function mergeSessions(server: ChatSession[], local: ChatSession[]): ChatSession[] {
  const byId = new Map<string, ChatSession>();
  for (const session of [...server, ...local]) {
    const existing = byId.get(session.id);
    if (!existing || timeValue(session.updatedAt) >= timeValue(existing.updatedAt)) {
      byId.set(session.id, session);
    }
  }
  return Array.from(byId.values()).sort((a, b) => timeValue(b.updatedAt) - timeValue(a.updatedAt));
}

/**
 * Messages within a session are append-only and identified by id. The device
 * with more messages is the authoritative one: a fresh device has 0 local and
 * takes the server's full set; the active device mid-turn has more local than
 * the last committed server set and keeps its own.
 */
export function mergeMessages(server: ChatMessage[], local: ChatMessage[]): ChatMessage[] {
  return server.length > local.length ? server : local;
}

/** Union by id; assets are immutable once created, so either copy is fine on conflict. */
export function mergeAssets(server: ChartAsset[], local: ChartAsset[]): ChartAsset[] {
  const byId = new Map<string, ChartAsset>();
  for (const asset of [...local, ...server]) {
    if (!byId.has(asset.id)) {
      byId.set(asset.id, asset);
    }
  }
  return Array.from(byId.values());
}
