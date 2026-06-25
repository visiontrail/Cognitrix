"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGetMe, type UserInfo } from "./auth-client";
import { getInMemoryToken } from "./session";

export const SESSION_QUERY_KEY = ["auth", "me"];

export function useSession() {
  const token = getInMemoryToken();
  const query = useQuery<UserInfo | null>({
    queryKey: SESSION_QUERY_KEY,
    queryFn: async () => {
      const t = getInMemoryToken();
      if (!t) return null;
      try {
        return await apiGetMe(t);
      } catch {
        return null;
      }
    },
    enabled: Boolean(token),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const user = query.data ?? null;
  const isLoggedIn = Boolean(user);
  const isLoading = query.isLoading;

  return { user, isLoggedIn, isLoading, query };
}
