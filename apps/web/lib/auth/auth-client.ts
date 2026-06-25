import { API_BASE_URL } from "@/lib/api-base";

export type UserInfo = {
  id: string;
  email: string;
  display_name: string;
  job_id: number | null;
  last_login_at: string | null;
  available_workspaces: Array<{ workspace_id: string; name: string; role: string }>;
};

export type AuthResult = {
  access_token: string;
  token_type: string;
  expires_at: number;
  user: {
    id: string;
    email: string;
    display_name: string;
    job_id: number | null;
  };
};

export class AuthError extends Error {
  code: string;
  status: number;
  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "AuthError";
    this.code = code;
    this.status = status;
  }
}

async function readError(response: Response, fallbackCode: string): Promise<AuthError> {
  let code = fallbackCode;
  let message = `Request failed with status ${response.status}`;
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (detail && typeof detail === "object") {
      code = detail.code ?? code;
      message = detail.message ?? message;
    } else if (typeof detail === "string") {
      message = detail;
    }
  } catch {
    // ignore
  }
  return new AuthError(code, message, response.status);
}

export async function apiRegister(payload: {
  email: string;
  password: string;
  display_name: string;
  job_id: number;
}): Promise<AuthResult> {
  const resp = await fetch(`${API_BASE_URL}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  });
  if (!resp.ok) throw await readError(resp, "register_failed");
  return resp.json();
}

export async function apiEmailLogin(payload: {
  email: string;
  password: string;
}): Promise<AuthResult> {
  const resp = await fetch(`${API_BASE_URL}/auth/email-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  });
  if (!resp.ok) throw await readError(resp, "login_failed");
  return resp.json();
}

export async function apiLogout(): Promise<void> {
  await fetch(`${API_BASE_URL}/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
}

export async function apiGetMe(token: string): Promise<UserInfo> {
  const resp = await fetch(`${API_BASE_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
    credentials: "include",
  });
  if (!resp.ok) throw await readError(resp, "me_failed");
  return resp.json();
}
