import { API_BASE_URL } from "@/lib/api-base";
import { getInMemoryToken } from "@/lib/auth/session";

export type AdminMeta = {
  actor: { user_id: string; role: string };
  environment: string;
  app_name: string;
  settings_count: number;
  restart_required_count: number;
  skills: { enabled: boolean; directory: string; max_upload_mb: number };
};

export type AdminSetting = {
  key: string;
  category: string;
  type: "boolean" | "integer" | "number" | "path" | "string";
  value: string | number | boolean | null;
  masked_value: string;
  configured: boolean;
  secret: boolean;
  source: "override" | "environment" | "default";
  has_override: boolean;
  restart_required: boolean;
  base_value: string | number | boolean | null;
  description: string;
};

export type UsageSummary = {
  requests: number;
  active_users: number;
  chat_turns: number;
  tool_calls: number;
  errors: number;
  input_tokens: number;
  output_tokens: number;
  avg_latency_ms: number;
  total_users: number;
  enabled_users: number;
};

export type UsageTrend = {
  date: string;
  requests: number;
  chat_turns: number;
  tool_calls: number;
  active_users: number;
  tokens: number;
};

export type UsageOverview = {
  range: { days: number; start: string; end: string };
  summary: UsageSummary;
  trend: UsageTrend[];
};

export type ModelProviderProfile = {
  name: string;
  label: string;
  default_openai_url: string;
  default_anthropic_url: string;
  default_model: string;
  default_fast_model: string;
  models: string[];
  notes: string;
};

export type ModelSlot = {
  slot: "primary" | "backup";
  provider?: string;
  openai_url?: string;
  anthropic_url?: string;
  model?: string;
  fast_model?: string;
  api_key_configured: boolean;
  configured: boolean;
};

export type ModelRouterState = {
  enabled: boolean;
  serving_slot: "primary" | "backup";
  primary_breaker_open: boolean;
  cooldown_remaining_seconds: number;
  failure_threshold: number;
  slow_ttft_ms: number;
  slots: Record<string, ModelSlot & { consecutive_failures: number; samples: unknown[] }>;
};

export type ModelSettings = {
  profiles: ModelProviderProfile[];
  configuration: {
    backup_enabled: boolean;
    router_enabled: boolean;
    failure_threshold: number;
    cooldown_seconds: number;
    slow_ttft_ms: number;
  };
  slots: { primary: ModelSlot; backup: ModelSlot };
  router: ModelRouterState;
  count?: number;
  settings?: AdminSetting[];
};

export type ModelSettingsUpdate = {
  primary_provider: string;
  primary_openai_url: string;
  primary_anthropic_url: string;
  primary_model: string;
  primary_fast_model: string;
  primary_api_key?: string;
  backup_enabled: boolean;
  backup_provider: string;
  backup_openai_url: string;
  backup_anthropic_url: string;
  backup_model: string;
  backup_fast_model: string;
  backup_api_key?: string;
  router_enabled: boolean;
  failure_threshold: number;
  cooldown_seconds: number;
  slow_ttft_ms: number;
};

export type AdminUser = {
  id: string;
  email: string;
  display_name: string;
  job_id: number | null;
  job_label: string;
  status: "active" | "suspended";
  role: string;
  created_at: string;
  last_login_at: string | null;
  workspace_count: number;
  usage: {
    requests: number;
    chat_turns: number;
    tool_calls: number;
    tokens: number;
    last_activity_at: string | null;
  };
};

export type UsageUser = {
  id: string;
  email: string;
  display_name: string;
  status: string;
  requests: number;
  chat_turns: number;
  tool_calls: number;
  tokens: number;
  last_activity_at: string | null;
};

export class AdminControlError extends Error {
  code: string;
  status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "AdminControlError";
    this.code = code;
    this.status = status;
  }
}

export async function getAdminMeta(): Promise<AdminMeta> {
  return request("/admin/control/meta");
}

export async function getAdminSettings(category?: string): Promise<{
  count: number;
  categories: string[];
  settings: AdminSetting[];
}> {
  const suffix = category ? `?category=${encodeURIComponent(category)}` : "";
  return request(`/admin/control/settings${suffix}`);
}

export async function updateAdminSetting(
  key: string,
  value: unknown,
  clear = false,
): Promise<AdminSetting> {
  return request(`/admin/control/settings/${encodeURIComponent(key)}`, {
    method: "PATCH",
    body: JSON.stringify({ value, clear }),
  });
}

export async function resetAdminSetting(key: string): Promise<AdminSetting> {
  return request(`/admin/control/settings/${encodeURIComponent(key)}`, {
    method: "DELETE",
  });
}

export async function getModelSettings(): Promise<ModelSettings> {
  return request("/admin/control/models");
}

export async function updateModelSettings(payload: ModelSettingsUpdate): Promise<ModelSettings> {
  return request("/admin/control/models", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function testModelConnection(payload: {
  target?: "primary" | "backup";
  protocol?: "openai" | "anthropic";
  provider?: string;
  provider_url?: string;
  anthropic_url?: string;
  model?: string;
  api_key?: string;
  timeout_seconds?: number;
} = {}): Promise<{
  ok: boolean;
  target: "primary" | "backup";
  protocol: "openai" | "anthropic";
  provider: string;
  model: string;
  latency_ms: number;
}> {
  return request("/admin/control/models/test", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getAdminUsers(q = ""): Promise<{
  users: AdminUser[];
  page: number;
  page_size: number;
  total: number;
  pages: number;
}> {
  return request(`/admin/control/users?q=${encodeURIComponent(q)}`);
}

export async function setAdminUserRole(userId: string, role: string): Promise<void> {
  await request(`/admin/control/users/${encodeURIComponent(userId)}/role`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

export async function setAdminUserStatus(
  userId: string,
  status: "active" | "suspended",
): Promise<void> {
  await request(`/admin/control/users/${encodeURIComponent(userId)}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export async function getUsageOverview(days = 30): Promise<UsageOverview> {
  return request(`/admin/control/usage/overview?days=${days}`);
}

export async function getUsageUsers(days = 30): Promise<{
  users: UsageUser[];
  page: number;
  page_size: number;
  total: number;
  pages: number;
}> {
  return request(`/admin/control/usage/users?days=${days}&sort=chat_turns&order=desc`);
}

export async function getSkillsMeta(): Promise<{
  enabled: boolean;
  directory: string;
  max_upload_mb: number;
  known_agents: string[];
}> {
  return request("/admin/control/skills/meta");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getInMemoryToken();
  if (!token) {
    throw new AdminControlError("not_authenticated", "Login required", 401);
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw await readError(response);
  }
  return response.json() as Promise<T>;
}

async function readError(response: Response): Promise<AdminControlError> {
  let code = "admin_request_failed";
  let message = `Request failed (${response.status})`;
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (detail && typeof detail === "object") {
      code = String(detail.code ?? code);
      message = String(detail.message ?? message);
    }
  } catch {
    // Keep the sanitized fallback.
  }
  return new AdminControlError(code, message, response.status);
}
