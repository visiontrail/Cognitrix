"use client";

import { useMemo } from "react";
import { getInMemoryToken } from "./session";

/**
 * Decoded subset of the JWT we care about for role-gating.
 * The backend mints HS256 JWTs with `role` in the payload.
 */
type DecodedTokenPayload = {
  role?: string;
};

function decodeJwtRole(token: string | null): string | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    if (typeof window === "undefined") return null;
    const normalized = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(
      normalized.length + ((4 - (normalized.length % 4)) % 4),
      "=",
    );
    const decoded = window.atob(padded);
    const parsed = JSON.parse(decoded) as DecodedTokenPayload;
    return typeof parsed.role === "string" ? parsed.role.trim().toLowerCase() : null;
  } catch {
    return null;
  }
}

/**
 * Returns the system-level role of the current user, decoded from the JWT.
 * Returns null when not logged in or the token is malformed.
 */
export function useCurrentRole(): string | null {
  const token = getInMemoryToken();
  return useMemo(() => decodeJwtRole(token), [token]);
}

/**
 * Convenience guard: is the current user a superadmin?
 *
 * Superadmins are the only role with `skills:admin` permission on the backend
 * and the only ones who should be able to load the `/admin/skills` page.
 */
export function useIsSuperadmin(): boolean {
  const role = useCurrentRole();
  return role === "superadmin";
}
