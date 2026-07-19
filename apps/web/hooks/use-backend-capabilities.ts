"use client";

import { useQuery } from "@tanstack/react-query";
import { API_BASE_URL } from "@/lib/api-base";
import { getActiveAuthContext, getAuthorizationHeader } from "@/lib/auth/session";

export type BackendCapabilities = {
  agentCanvasModeEnabled: boolean;
  webSearchEnabled: boolean;
};

const DEFAULT_CAPABILITIES: BackendCapabilities = {
  agentCanvasModeEnabled: false,
  webSearchEnabled: false,
};

const configuredClearance = Number(process.env.NEXT_PUBLIC_DEFAULT_CLEARANCE ?? 1);
const DEFAULT_AUTH_CONTEXT = {
  userId: process.env.NEXT_PUBLIC_DEFAULT_USER_ID ?? "demo-user",
  projectId: process.env.NEXT_PUBLIC_DEFAULT_PROJECT_ID ?? "demo-project",
  role: process.env.NEXT_PUBLIC_DEFAULT_ROLE ?? "hr",
  department: process.env.NEXT_PUBLIC_DEFAULT_DEPARTMENT ?? "HR",
  clearance: Number.isFinite(configuredClearance) ? Math.max(0, Math.trunc(configuredClearance)) : 1,
};

/**
 * Feature flags reported by the backend (`GET /chat/capabilities`). Optional
 * composer affordances (the Agent-mode toggle) render only when the backend
 * actually supports them, so a disabled deployment shows no dead UI.
 */
export function useBackendCapabilities(): BackendCapabilities {
  const query = useQuery({
    queryKey: ["backend-capabilities"],
    staleTime: Infinity,
    retry: 1,
    queryFn: async (): Promise<BackendCapabilities> => {
      const authContext = getActiveAuthContext(DEFAULT_AUTH_CONTEXT);
      const headers = await getAuthorizationHeader(API_BASE_URL, authContext);
      const response = await fetch(`${API_BASE_URL}/chat/capabilities`, { headers });
      if (!response.ok) return DEFAULT_CAPABILITIES;
      const body = (await response.json()) as Record<string, unknown>;
      return {
        agentCanvasModeEnabled: body.agent_canvas_mode_enabled === true,
        webSearchEnabled: body.web_search_enabled === true,
      };
    },
  });
  return query.data ?? DEFAULT_CAPABILITIES;
}
