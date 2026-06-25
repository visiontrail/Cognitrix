import { API_BASE_URL } from "@/lib/api-base";
import { getAuthorizationHeader } from "@/lib/auth/session";
import type {
  SavedPrompt,
  SavedPromptCapability,
  SavedPromptCreateInput,
  SavedPromptListParams,
  SavedPromptUpdateInput,
} from "@/lib/saved-prompts/types";

const configuredClearance = Number(process.env.NEXT_PUBLIC_DEFAULT_CLEARANCE ?? 1);
const DEFAULT_CLEARANCE = Number.isFinite(configuredClearance)
  ? Math.max(0, Math.trunc(configuredClearance))
  : 1;
const DEFAULT_AUTH_CONTEXT = {
  userId: process.env.NEXT_PUBLIC_DEFAULT_USER_ID ?? "demo-user",
  projectId: process.env.NEXT_PUBLIC_DEFAULT_PROJECT_ID ?? "demo-project",
  role: process.env.NEXT_PUBLIC_DEFAULT_ROLE ?? "hr",
  department: process.env.NEXT_PUBLIC_DEFAULT_DEPARTMENT ?? "HR",
  clearance: DEFAULT_CLEARANCE,
};

export class SavedPromptApiError extends Error {
  code?: string;
  status: number;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "SavedPromptApiError";
    this.status = status;
    this.code = code;
  }
}

export async function listSavedPrompts(params: SavedPromptListParams = {}): Promise<SavedPrompt[]> {
  const search = new URLSearchParams();
  if (params.query && params.query.trim()) search.set("query", params.query.trim());
  if (params.includeArchived) search.set("include_archived", "true");
  if (params.limit) search.set("limit", String(params.limit));
  const suffix = search.toString() ? `?${search.toString()}` : "";

  const payload = await request(`/saved-prompts${suffix}`, { method: "GET" });
  const prompts = asRecord(payload).prompts;
  if (!Array.isArray(prompts)) return [];
  return prompts.map(mapPrompt).filter((item): item is SavedPrompt => item !== null);
}

export async function createSavedPrompt(input: SavedPromptCreateInput): Promise<SavedPrompt> {
  const payload = await request("/saved-prompts", {
    method: "POST",
    body: JSON.stringify({
      name: input.name,
      body: input.body,
      capabilities: input.capabilities ?? [],
    }),
  });
  return requirePrompt(payload);
}

export async function getSavedPrompt(promptId: string): Promise<SavedPrompt> {
  const payload = await request(`/saved-prompts/${encodeURIComponent(promptId)}`, { method: "GET" });
  return requirePrompt(payload);
}

export async function updateSavedPrompt(
  promptId: string,
  input: SavedPromptUpdateInput,
): Promise<SavedPrompt> {
  const body: Record<string, unknown> = {};
  if (input.name !== undefined) body.name = input.name;
  if (input.body !== undefined) body.body = input.body;
  if (input.capabilities !== undefined) body.capabilities = input.capabilities;
  const payload = await request(`/saved-prompts/${encodeURIComponent(promptId)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  return requirePrompt(payload);
}

export async function archiveSavedPrompt(promptId: string): Promise<SavedPrompt> {
  const payload = await request(`/saved-prompts/${encodeURIComponent(promptId)}`, {
    method: "DELETE",
  });
  return requirePrompt(payload);
}

export async function markSavedPromptUsed(promptId: string): Promise<SavedPrompt> {
  const payload = await request(`/saved-prompts/${encodeURIComponent(promptId)}/use`, {
    method: "POST",
  });
  return requirePrompt(payload);
}

async function request(path: string, init: RequestInit): Promise<unknown> {
  const authHeaders = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const headers: Record<string, string> = { ...authHeaders };
  if (init.body) headers["Content-Type"] = "application/json";

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = extractDetail(payload);
    throw new SavedPromptApiError(
      detail.message || `saved_prompt_request_failed_${response.status}`,
      response.status,
      detail.code,
    );
  }
  return payload;
}

function requirePrompt(payload: unknown): SavedPrompt {
  const prompt = mapPrompt(asRecord(payload).prompt);
  if (!prompt) {
    throw new SavedPromptApiError("saved_prompt_invalid_payload", 500);
  }
  return prompt;
}

function mapPrompt(value: unknown): SavedPrompt | null {
  if (!isRecord(value)) return null;
  const id = String(value.id ?? "");
  if (!id) return null;
  return {
    id,
    name: String(value.name ?? ""),
    body: String(value.body ?? ""),
    variables: asStringList(value.variables),
    capabilities: asStringList(value.capabilities) as SavedPromptCapability[],
    usageCount: Number(value.usage_count ?? 0),
    lastUsedAt: asNullableString(value.last_used_at),
    createdAt: String(value.created_at ?? ""),
    updatedAt: String(value.updated_at ?? ""),
    archivedAt: asNullableString(value.archived_at),
  };
}

function extractDetail(payload: unknown): { code?: string; message?: string } {
  const record = asRecord(payload);
  const detail = record.detail;
  if (isRecord(detail)) {
    return {
      code: typeof detail.code === "string" ? detail.code : undefined,
      message: typeof detail.message === "string" ? detail.message : undefined,
    };
  }
  if (typeof detail === "string") return { message: detail };
  return {};
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

function asNullableString(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function asRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
