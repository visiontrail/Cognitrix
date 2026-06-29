"use client";

import { useState, useCallback, useRef } from "react";
import { Input } from "@/components/ui/input";
import { API_BASE_URL } from "@/lib/api-base";
import { getAuthorizationHeader } from "@/lib/auth/session";
import { useI18n } from "@/lib/i18n/context";

const DEFAULT_AUTH_CONTEXT = {
  userId: process.env.NEXT_PUBLIC_DEFAULT_USER_ID ?? "demo-user",
  projectId: process.env.NEXT_PUBLIC_DEFAULT_PROJECT_ID ?? "demo-project",
  role: process.env.NEXT_PUBLIC_DEFAULT_ROLE ?? "hr",
  department: null,
  clearance: 1,
};

export type UserSearchResult = {
  id: string;
  email_masked: string;
  display_name: string;
  job_label: string;
};

type Props = {
  onSelect: (user: UserSearchResult) => void;
  excludeIds?: string[];
  placeholder?: string;
};

function useDebounce<T extends (...args: Parameters<T>) => void>(fn: T, delay: number): T {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  return useCallback(
    (...args: Parameters<T>) => {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => fn(...args), delay);
    },
    [fn, delay]
  ) as T;
}

export function UserSearchInput({ onSelect, excludeIds = [], placeholder }: Props) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<UserSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [focusedIndex, setFocusedIndex] = useState(-1);

  const doSearch = useCallback(async (q: string) => {
    if (q.length < 2) {
      setResults([]);
      setOpen(false);
      return;
    }
    setLoading(true);
    try {
      const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
      const resp = await fetch(
        `${API_BASE_URL}/users/search?q=${encodeURIComponent(q)}&limit=10`,
        { headers }
      );
      if (!resp.ok) return;
      const data = await resp.json();
      const filtered = (data.users as UserSearchResult[]).filter(
        (u) => !excludeIds.includes(u.id)
      );
      setResults(filtered);
      setOpen(filtered.length > 0);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [excludeIds]);

  const debouncedSearch = useDebounce(doSearch, 300);

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const val = e.target.value;
    setQuery(val);
    setFocusedIndex(-1);
    debouncedSearch(val);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!open) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setFocusedIndex((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setFocusedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && focusedIndex >= 0) {
      e.preventDefault();
      const selected = results[focusedIndex];
      if (selected) {
        onSelect(selected);
        setQuery("");
        setResults([]);
        setOpen(false);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className="relative">
      <Input
        value={query}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        placeholder={placeholder ?? t("collab.userSearchPlaceholder")}
        aria-autocomplete="list"
        aria-expanded={open}
      />
      {loading && (
        <div className="absolute right-2 top-2 text-xs text-[#777166] dark:text-gray-300">...</div>
      )}
      {open && results.length > 0 && (
        <ul
          className="absolute z-[1000] mt-1 max-h-48 w-full overflow-auto rounded-md border border-[#d8d1c1] bg-[#ffffff] shadow-[0_18px_48px_rgba(38,35,28,0.18)] dark:border-white/15 dark:bg-[#1c1c38] dark:shadow-[0_24px_72px_rgba(0,0,0,0.48)]"
          role="listbox"
        >
          {results.map((user, idx) => (
            <li
              key={user.id}
              role="option"
              aria-selected={idx === focusedIndex}
              className={`px-3 py-2 cursor-pointer text-sm transition-colors ${
                idx === focusedIndex ? "bg-warm-sand dark:bg-[#25254d]" : "hover:bg-warm-sand dark:hover:bg-[#25254d]"
              }`}
              onMouseDown={() => {
                onSelect(user);
                setQuery("");
                setResults([]);
                setOpen(false);
              }}
            >
              <span className="font-medium text-[#2f332f] dark:text-white">{user.display_name}</span>
              <span className="ml-2 text-[#777166] dark:text-gray-300">{user.email_masked}</span>
              {user.job_label && (
                <span className="ml-2 text-xs text-[#777166] dark:text-gray-300">·{user.job_label}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
