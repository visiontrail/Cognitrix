// Session management: in-memory token + localStorage cache for new email/password auth
// Also keeps the legacy service-token flow for backward compatibility

export type AuthContext = {
  userId: string;
  projectId: string;
  role: string;
  department: string | null;
  clearance: number;
};

type CachedAccessToken = {
  accessToken: string;
  expiresAt: number;
  scopeKey: string;
};

const AUTH_STORAGE_KEY = "cognitrix:access-token:v1";
const NEW_AUTH_STORAGE_KEY = "cognitrix:user-token:v2";
const TOKEN_REFRESH_SKEW_SECONDS = 30;

// In-memory token for new auth (email+password)
let _inMemoryToken: string | null = null;
let _inMemoryExpiresAt = 0;

export function setInMemoryToken(token: string, expiresAt: number): void {
  _inMemoryToken = token;
  _inMemoryExpiresAt = expiresAt;
  // Also persist to localStorage as fallback
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(
        NEW_AUTH_STORAGE_KEY,
        JSON.stringify({ accessToken: token, expiresAt })
      );
    } catch {
      // ignore storage errors
    }
  }
}

export function clearInMemoryToken(): void {
  _inMemoryToken = null;
  _inMemoryExpiresAt = 0;
  if (typeof window !== "undefined") {
    try {
      window.localStorage.removeItem(NEW_AUTH_STORAGE_KEY);
      window.localStorage.removeItem(AUTH_STORAGE_KEY);
    } catch {
      // ignore
    }
  }
}

export function getInMemoryToken(): string | null {
  const now = Math.floor(Date.now() / 1000);
  if (_inMemoryToken && _inMemoryExpiresAt > now + TOKEN_REFRESH_SKEW_SECONDS) {
    return _inMemoryToken;
  }
  // Try localStorage fallback
  if (typeof window !== "undefined") {
    try {
      const raw = window.localStorage.getItem(NEW_AUTH_STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as { accessToken: string; expiresAt: number };
        if (parsed.accessToken && parsed.expiresAt > now + TOKEN_REFRESH_SKEW_SECONDS) {
          _inMemoryToken = parsed.accessToken;
          _inMemoryExpiresAt = parsed.expiresAt;
          return _inMemoryToken;
        }
      }
    } catch {
      // ignore
    }
  }
  return null;
}

export function getActiveAuthContext(fallback: AuthContext): AuthContext {
  const token = getInMemoryToken();
  if (!token) {
    return fallback;
  }

  const payload = decodeJwtPayload(token);
  if (!payload) {
    return fallback;
  }

  const userId = readString(payload.sub);
  const projectId = readString(payload.project_id);
  if (!userId || !projectId) {
    return fallback;
  }

  return {
    userId,
    projectId,
    role: readString(payload.role) || fallback.role,
    department: readNullableString(payload.department),
    clearance: readInteger(payload.clearance, fallback.clearance),
  };
}

export async function getAuthorizationHeader(
  apiBaseUrl: string,
  context: AuthContext
): Promise<Record<string, string>> {
  // Check new auth first
  const userToken = getInMemoryToken();
  if (userToken) {
    return { Authorization: `Bearer ${userToken}` };
  }
  // Fall back to legacy service-token auth
  const token = await getLegacyAccessToken(apiBaseUrl, context);
  return { Authorization: `Bearer ${token}` };
}

export function handleUnauthorized(currentPath?: string): void {
  if (typeof window === "undefined") return;
  const next = encodeURIComponent(currentPath ?? window.location.pathname);
  window.location.href = `/login?next=${next}`;
}

async function getLegacyAccessToken(apiBaseUrl: string, context: AuthContext): Promise<string> {
  const normalized = normalizeAuthContext(context);
  const scopeKey = buildScopeKey(normalized);
  const cached = loadCachedAccessToken();
  if (cached && cached.scopeKey === scopeKey && cached.expiresAt > nowInSeconds() + TOKEN_REFRESH_SKEW_SECONDS) {
    return cached.accessToken;
  }

  const response = await fetch(`${apiBaseUrl}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: normalized.userId,
      project_id: normalized.projectId,
      role: normalized.role,
      department: normalized.department,
      clearance: normalized.clearance,
    }),
  });

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(readErrorMessage(payload, `auth_login_failed_${response.status}`));
  }

  const accessToken = isRecord(payload) ? String(payload.access_token ?? "") : "";
  const expiresAt = isRecord(payload) ? Number(payload.expires_at ?? 0) : 0;
  if (!accessToken || !Number.isFinite(expiresAt) || expiresAt <= 0) {
    throw new Error("auth_login_invalid_payload");
  }

  saveCachedAccessToken({ accessToken, expiresAt, scopeKey });
  return accessToken;
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const parts = token.split(".");
  if (parts.length !== 3) {
    return null;
  }

  try {
    const normalized = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");
    const decoded = window.atob(padded);
    const payload = JSON.parse(decoded) as unknown;
    return isRecord(payload) ? payload : null;
  } catch {
    return null;
  }
}

function readString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function readNullableString(value: unknown): string | null {
  const text = readString(value);
  return text || null;
}

function readInteger(value: unknown, fallback: number): number {
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? Math.max(0, Math.trunc(numeric)) : fallback;
}

function normalizeAuthContext(context: AuthContext): AuthContext {
  return {
    userId: context.userId.trim(),
    projectId: context.projectId.trim(),
    role: context.role.trim().toLowerCase() || "viewer",
    department: context.department?.trim() || null,
    clearance: Number.isFinite(context.clearance) ? Math.max(0, Math.trunc(context.clearance)) : 0,
  };
}

function buildScopeKey(context: AuthContext): string {
  return JSON.stringify([context.userId, context.projectId, context.role, context.department, context.clearance]);
}

function loadCachedAccessToken(): CachedAccessToken | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CachedAccessToken;
    if (
      !parsed ||
      typeof parsed.accessToken !== "string" ||
      typeof parsed.scopeKey !== "string" ||
      typeof parsed.expiresAt !== "number"
    ) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function saveCachedAccessToken(token: CachedAccessToken): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(token));
  } catch {
    // ignore
  }
}

function readErrorMessage(payload: unknown, fallback: string): string {
  if (!isRecord(payload)) return fallback;
  const detail = isRecord(payload.detail) ? payload.detail : null;
  const detailMessage = detail ? String(detail.message ?? "") : "";
  if (detailMessage) return detailMessage;
  const payloadMessage = String(payload.message ?? "");
  return payloadMessage || fallback;
}

function nowInSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
