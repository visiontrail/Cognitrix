// API client for the super-admin /admin/skills endpoints.
//
// Returns shapes match the FastAPI router in apps/api/admin_skills.py.

import { API_BASE_URL } from "@/lib/api-base";
import { getInMemoryToken } from "@/lib/auth/session";

export type AgentName = "WriteIngestionAgent" | "QueryAgent" | "ChartQueryAgent";

export const KNOWN_AGENT_NAMES: AgentName[] = [
  "WriteIngestionAgent",
  "QueryAgent",
  "ChartQueryAgent",
];

export type SkillManifest = {
  name?: string;
  description?: string;
  version?: string;
  [key: string]: unknown;
};

export type Skill = {
  id: string;
  name: string;
  version: string;
  sha256: string;
  status: "enabled" | "disabled";
  uploaded_by: string;
  uploaded_at: number;
  bundle_dir: string;
  manifest: SkillManifest;
  load_error: string | null;
  assignments: AgentName[];
};

export type SkillsListResponse = {
  count: number;
  skills: Skill[];
};

export class AdminSkillsError extends Error {
  code: string;
  status: number;
  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "AdminSkillsError";
    this.code = code;
    this.status = status;
  }
}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const token = getInMemoryToken();
  if (!token) {
    throw new AdminSkillsError("not_authenticated", "Login required", 401);
  }
  return {
    Authorization: `Bearer ${token}`,
    ...(extra ?? {}),
  };
}

async function readError(response: Response, fallbackCode: string): Promise<AdminSkillsError> {
  let code = fallbackCode;
  let message = `Request failed (${response.status})`;
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (detail && typeof detail === "object") {
      code = detail.code ?? code;
      message = detail.message ?? message;
    }
  } catch {
    // ignore body-parse failures
  }
  return new AdminSkillsError(code, message, response.status);
}

export async function listSkills(): Promise<SkillsListResponse> {
  const resp = await fetch(`${API_BASE_URL}/admin/skills`, {
    headers: authHeaders(),
    credentials: "include",
  });
  if (!resp.ok) throw await readError(resp, "list_failed");
  return (await resp.json()) as SkillsListResponse;
}

export async function getSkill(skillId: string): Promise<Skill> {
  const resp = await fetch(
    `${API_BASE_URL}/admin/skills/${encodeURIComponent(skillId)}`,
    { headers: authHeaders(), credentials: "include" },
  );
  if (!resp.ok) throw await readError(resp, "get_failed");
  return (await resp.json()) as Skill;
}

export async function uploadSkill(file: File): Promise<Skill> {
  const body = new FormData();
  body.append("file", file, file.name);
  const resp = await fetch(`${API_BASE_URL}/admin/skills`, {
    method: "POST",
    headers: authHeaders(), // Content-Type is set by the browser for FormData.
    credentials: "include",
    body,
  });
  if (!resp.ok) throw await readError(resp, "upload_failed");
  return (await resp.json()) as Skill;
}

export async function setSkillStatus(
  skillId: string,
  status: "enabled" | "disabled",
): Promise<Skill> {
  const resp = await fetch(
    `${API_BASE_URL}/admin/skills/${encodeURIComponent(skillId)}`,
    {
      method: "PATCH",
      headers: authHeaders({ "Content-Type": "application/json" }),
      credentials: "include",
      body: JSON.stringify({ status }),
    },
  );
  if (!resp.ok) throw await readError(resp, "status_update_failed");
  return (await resp.json()) as Skill;
}

export async function deleteSkill(skillId: string): Promise<void> {
  const resp = await fetch(
    `${API_BASE_URL}/admin/skills/${encodeURIComponent(skillId)}`,
    {
      method: "DELETE",
      headers: authHeaders(),
      credentials: "include",
    },
  );
  if (!resp.ok) throw await readError(resp, "delete_failed");
}

export async function assignSkill(skillId: string, agentName: AgentName): Promise<void> {
  const resp = await fetch(
    `${API_BASE_URL}/admin/skills/${encodeURIComponent(skillId)}/assignments`,
    {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      credentials: "include",
      body: JSON.stringify({ agent_name: agentName }),
    },
  );
  if (!resp.ok) throw await readError(resp, "assign_failed");
}

export async function unassignSkill(skillId: string, agentName: AgentName): Promise<void> {
  const resp = await fetch(
    `${API_BASE_URL}/admin/skills/${encodeURIComponent(skillId)}/assignments/${encodeURIComponent(agentName)}`,
    {
      method: "DELETE",
      headers: authHeaders(),
      credentials: "include",
    },
  );
  if (!resp.ok) throw await readError(resp, "unassign_failed");
}
